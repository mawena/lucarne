"""Fenêtre de Lucarne : choix de la carte, du mode, du son et de la sortie ; bouton Regarder / Arrêter."""
import threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gst", "1.0")
from gi.repository import Adw, Gio, GLib, Gst, Gtk  # noqa: E402

from . import appareils  # noqa: E402
from .commandes import TAMPON_SON_MIN, TAMPON_SON_MAX
from .config import Reglages, identifiant_carte
from .lecture import Lecture
from .mesure import Resultat, choisir, mesurer_mode, modes_a_tester
from .modes import mode_depuis_cle, mode_par_defaut

DELAI_RAFRAICHIR_MS = 300
RETARD_BLUETOOTH = "Sortie Bluetooth : le son arrive environ 200 ms après l'image."


def _texte_latence(resultat):
    if resultat is None:
        return "non testé"
    if not resultat.valide:
        return "ne marche pas"
    reel = f"{resultat.ips_reel:.0f} i/s reçues"
    return f"≈ {resultat.latence_ms:.0f} ms · {reel}"


class Fenetre(Adw.ApplicationWindow):
    def __init__(self, application):
        super().__init__(application=application, title="Lucarne", default_width=520, default_height=720)
        self.reglages = Reglages.charger()
        self.cartes, self.sources, self.sorties = [], [], []
        self.sortie_defaut = None
        self._maj = False               # vrai pendant qu'on remplit les listes : on ignore leurs signaux
        self._rafraichir_id = {}
        self._test = None               # (fil, drapeau d'arrêt) pendant un test
        self.lecture = Lecture(self._lecture_finie, self._son_perdu)

        self._construire()
        self._surveiller_cartes()
        self._surveiller_son()
        self._rafraichir_cartes()
        self._rafraichir_son()
        self.connect("close-request", self._fermeture)

    # --- Construction -------------------------------------------------------------------------------------------

    def _construire(self):
        vue = Adw.ToolbarView()
        entete = Adw.HeaderBar()
        menu = Gio.Menu()
        menu.append("À propos de Lucarne", "app.about")
        menu.append("Quitter", "app.quit")
        entete.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, tooltip_text="Menu"))
        vue.add_top_bar(entete)
        self.banniere = Adw.Banner(title=RETARD_BLUETOOTH)
        vue.add_top_bar(self.banniere)

        self.pile = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.pile.add_named(Adw.StatusPage(
            icon_name="camera-video-symbolic", title="Aucune carte de capture",
            description="Branche la carte HDMI-USB : elle apparaîtra ici toute seule."), "vide")
        self.pile.add_named(self._page_reglages(), "reglages")
        self.toasts = Adw.ToastOverlay(child=self.pile)
        vue.set_content(self.toasts)

        self.bouton = Gtk.Button(label="Regarder", halign=Gtk.Align.CENTER)
        self.bouton.add_css_class("pill")
        self.bouton.add_css_class("suggested-action")
        self.bouton.set_size_request(220, -1)
        self.bouton.connect("clicked", self._regarder_ou_arreter)
        bas = Gtk.Box(margin_top=12, margin_bottom=18, halign=Gtk.Align.CENTER)
        bas.append(self.bouton)
        vue.add_bottom_bar(bas)
        self.set_content(vue)

    def _page_reglages(self):
        page = Adw.PreferencesPage()

        image = Adw.PreferencesGroup(title="Image")
        self.ligne_carte = Adw.ComboRow(title="Carte", model=Gtk.StringList())
        self.ligne_carte.connect("notify::selected", self._carte_choisie)
        image.add(self.ligne_carte)

        self.ligne_mode = Adw.ComboRow(title="Mode", model=Gtk.StringList(), use_subtitle=True)
        self.ligne_mode.connect("notify::selected", self._mode_choisi)
        image.add(self.ligne_mode)

        self.ligne_test = Adw.ActionRow(title="Test de vitesse",
                                        subtitle="Mesure chaque mode de la carte et choisit le plus rapide")
        self.attente_test = Gtk.Spinner(visible=False)
        self.ligne_test.add_suffix(self.attente_test)
        self.bouton_test = Gtk.Button(label="Tester", valign=Gtk.Align.CENTER)
        self.bouton_test.connect("clicked", self._tester_ou_annuler)
        self.ligne_test.add_suffix(self.bouton_test)
        image.add(self.ligne_test)

        self.ligne_plein = Adw.SwitchRow(title="Plein écran au lancement",
                                         subtitle="F ou double-clic dans l'image pour basculer",
                                         active=self.reglages.plein_ecran)
        self.ligne_plein.connect("notify::active", self._plein_ecran_choisi)
        image.add(self.ligne_plein)
        page.add(image)

        son = Adw.PreferencesGroup(title="Son")
        self.ligne_source = Adw.ComboRow(title="Son de la carte", model=Gtk.StringList(), use_subtitle=True)
        self.ligne_source.connect("notify::selected", self._son_choisi)
        son.add(self.ligne_source)

        self.ligne_sortie = Adw.ComboRow(title="Sortie", model=Gtk.StringList(), use_subtitle=True)
        self.ligne_sortie.connect("notify::selected", self._sortie_choisie)
        son.add(self.ligne_sortie)

        self.ligne_tampon = Adw.SpinRow.new_with_range(TAMPON_SON_MIN, TAMPON_SON_MAX, 5)
        self.ligne_tampon.set_title("Tampon du son (ms)")
        self.ligne_tampon.set_subtitle("Plus court : moins de retard. Trop court : craquements.")
        self.ligne_tampon.set_value(self.reglages.tampon_son_ms)
        self.ligne_tampon.connect("notify::value", self._tampon_choisi)
        son.add(self.ligne_tampon)
        page.add(son)
        return page

    # --- Surveillance des appareils -----------------------------------------------------------------------------

    def _surveiller_cartes(self):
        self.moniteur = Gst.DeviceMonitor()
        self.moniteur.add_filter("Video/Source", None)
        self.moniteur.get_bus().add_watch(GLib.PRIORITY_DEFAULT, self._message_moniteur)
        self.moniteur.start()

    def _message_moniteur(self, _bus, message):
        if message.type in (Gst.MessageType.DEVICE_ADDED, Gst.MessageType.DEVICE_REMOVED):
            self._plus_tard("cartes", self._rafraichir_cartes)
        return GLib.SOURCE_CONTINUE

    def _surveiller_son(self):
        """``pactl subscribe`` : chaque sortie ou source ajoutée, retirée ou changée relit la liste du son."""
        try:
            self._abonnement = Gio.Subprocess.new(["pactl", "subscribe"], Gio.SubprocessFlags.STDOUT_PIPE)
        except GLib.Error:
            self._abonnement = None
            return
        self._flux = Gio.DataInputStream.new(self._abonnement.get_stdout_pipe())
        self._flux.read_line_async(GLib.PRIORITY_DEFAULT, None, self._ligne_pactl)

    def _ligne_pactl(self, flux, resultat):
        try:
            ligne, _ = flux.read_line_finish_utf8(resultat)
        except GLib.Error:
            return
        if ligne is None:
            return                                  # pactl s'est arrêté
        if any(mot in ligne for mot in ("sink", "source", "server", "card")) and "sink-input" not in ligne \
                and "source-output" not in ligne:
            self._plus_tard("son", self._rafraichir_son)
        flux.read_line_async(GLib.PRIORITY_DEFAULT, None, self._ligne_pactl)

    def _plus_tard(self, nom, fonction):
        """Regroupe les événements en rafale (un branchement en produit plusieurs) en un seul rafraîchissement."""
        if nom in self._rafraichir_id:
            return

        def lancer():
            del self._rafraichir_id[nom]
            fonction()
            return GLib.SOURCE_REMOVE
        self._rafraichir_id[nom] = GLib.timeout_add(DELAI_RAFRAICHIR_MS, lancer)

    # --- Listes ---------------------------------------------------------------------------------------------------

    @staticmethod
    def _remplir(ligne, textes, selection):
        ligne.set_model(Gtk.StringList.new(textes))
        ligne.set_selected(selection if 0 <= selection < len(textes) else 0)

    def _rafraichir_cartes(self):
        precedente = self.carte()
        self.cartes = appareils.lister_cartes(self.moniteur)
        voulue = precedente.nom if precedente else self.reglages.carte
        # La carte qui a un son sur le même appareil USB passe devant (une webcam n'en a généralement pas)
        sources = self.sources or appareils.lister_sources()
        self.cartes.sort(key=lambda c: (appareils.associer_son(c, sources) is None, c.chemin))
        index = next((i for i, c in enumerate(self.cartes) if c.nom == voulue), 0)
        self._maj = True
        self._remplir(self.ligne_carte, [c.nom for c in self.cartes], index)
        self._maj = False
        self.pile.set_visible_child_name("reglages" if self.cartes else "vide")
        if precedente is None or self.carte() != precedente:
            self._carte_changee()
        self._mettre_a_jour_boutons()

    def _rafraichir_son(self):
        self.sources = appareils.lister_sources()
        self.sorties = appareils.lister_sorties()
        self.sortie_defaut = appareils.sortie_par_defaut()
        source_avant = self.source()
        self._maj = True
        self._remplir_sources(source_avant.nom if source_avant else None)
        defaut = next((s for s in self.sorties if s.nom == self.sortie_defaut), None)
        textes = [f"Sortie du système ({defaut.description})" if defaut else "Sortie du système"]
        textes += [s.description for s in self.sorties]
        index = next((i + 1 for i, s in enumerate(self.sorties) if s.nom == self.reglages.sortie), 0)
        self._remplir(self.ligne_sortie, textes, index)
        self._maj = False
        self._mettre_a_jour_banniere()

    def _remplir_sources(self, nom_voulu=None):
        """Sources du son : « Aucun » puis les sources ; par défaut celle du même appareil USB que la carte."""
        if nom_voulu is None:
            associee = appareils.associer_son(self.carte(), self.sources)
            nom_voulu = associee.nom if associee else None
        textes = ["Aucun (image seule)"] + [s.description for s in self.sources]
        index = next((i + 1 for i, s in enumerate(self.sources) if s.nom == nom_voulu), 0)
        self._remplir(self.ligne_source, textes, index)

    def _remplir_modes(self):
        carte = self.carte()
        if carte is None:
            self._remplir(self.ligne_mode, [], 0)
            return
        resultats = self.resultats(carte)
        par_cle = {r.cle: r for r in resultats}
        auto = choisir(carte.modes, resultats)
        if auto:
            premier = f"Automatique, le plus rapide : {auto.libelle} — {_texte_latence(par_cle.get(auto.cle))}"
        else:
            defaut = mode_par_defaut(carte.modes)
            premier = f"Automatique : {defaut.libelle} — non testé"
        textes = [premier] + [f"{m.libelle} — {_texte_latence(par_cle.get(m.cle))}" for m in carte.modes]
        index = 0
        if self.reglages.mode:
            mode = mode_depuis_cle(self.reglages.mode, carte.modes)
            index = carte.modes.index(mode) + 1 if mode else 0
        self._maj = True
        self._remplir(self.ligne_mode, textes, index)
        self._maj = False

    # --- Sélection courante -----------------------------------------------------------------------------------------

    def carte(self):
        i = self.ligne_carte.get_selected()
        return self.cartes[i] if 0 <= i < len(self.cartes) else None

    def mode(self):
        carte = self.carte()
        if carte is None:
            return None
        i = self.ligne_mode.get_selected()
        if 1 <= i <= len(carte.modes):
            return carte.modes[i - 1]
        return choisir(carte.modes, self.resultats(carte)) or mode_par_defaut(carte.modes)

    def source(self):
        i = self.ligne_source.get_selected()
        return self.sources[i - 1] if 1 <= i <= len(self.sources) else None

    def sortie(self):
        """Sortie choisie, ou None pour la sortie du système."""
        i = self.ligne_sortie.get_selected()
        return self.sorties[i - 1] if 1 <= i <= len(self.sorties) else None

    def resultats(self, carte):
        return [Resultat.depuis_dict(d) for d in self.reglages.tests.get(identifiant_carte(carte), [])]

    # --- Réactions aux choix ------------------------------------------------------------------------------------

    def _carte_changee(self):
        carte = self.carte()
        if carte:
            self.reglages.carte = carte.nom
        self._remplir_modes()
        self._maj = True
        self._remplir_sources()
        self._maj = False

    def _carte_choisie(self, *_):
        if not self._maj:
            self.reglages.mode = ""
            self._carte_changee()
            self._enregistrer()

    def _mode_choisi(self, *_):
        if self._maj:
            return
        carte, i = self.carte(), self.ligne_mode.get_selected()
        self.reglages.mode = carte.modes[i - 1].cle if carte and 1 <= i <= len(carte.modes) else ""
        self._enregistrer()

    def _plein_ecran_choisi(self, *_):
        self.reglages.plein_ecran = self.ligne_plein.get_active()
        self._enregistrer()

    def _son_choisi(self, *_):
        if not self._maj and self.lecture.en_cours:
            self._relancer_son()

    def _sortie_choisie(self, *_):
        if self._maj:
            return
        sortie = self.sortie()
        self.reglages.sortie = sortie.nom if sortie else ""
        self._enregistrer()
        self._mettre_a_jour_banniere()
        if self.lecture.en_cours:
            self._relancer_son()

    def _tampon_choisi(self, *_):
        self.reglages.tampon_son_ms = int(self.ligne_tampon.get_value())
        self._enregistrer()
        if self.lecture.en_cours:
            self._relancer_son()

    def _relancer_son(self):
        source, sortie = self.source(), self.sortie()
        self.lecture.changer_son(source.nom if source else None, sortie.nom if sortie else None,
                                 self.reglages.tampon_son_ms)

    def _mettre_a_jour_banniere(self):
        sortie = self.sortie() or next((s for s in self.sorties if s.nom == self.sortie_defaut), None)
        self.banniere.set_revealed(bool(sortie and sortie.bluetooth and self.source()))

    def _enregistrer(self):
        try:
            self.reglages.enregistrer()
        except OSError as e:
            self.annoncer(f"Réglages non enregistrés : {e.strerror}")

    def annoncer(self, texte):
        self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(texte), timeout=5))

    # --- Lecture ------------------------------------------------------------------------------------------------------

    def _regarder_ou_arreter(self, *_):
        if self.lecture.en_cours:
            self.lecture.arreter()
            self._mettre_a_jour_boutons()
            return
        carte, mode = self.carte(), self.mode()
        if carte is None or mode is None:
            return
        source, sortie = self.source(), self.sortie()
        try:
            self.lecture.demarrer(carte, mode, source.nom if source else None, sortie.nom if sortie else None,
                                  self.reglages.tampon_son_ms, self.reglages.plein_ecran)
        except GLib.Error as e:
            self.annoncer(f"mpv n'a pas pu démarrer : {e.message}")
        self._mettre_a_jour_boutons()

    def _lecture_finie(self, erreur):
        if erreur:
            if "busy" in erreur.lower() or "occupé" in erreur.lower():
                erreur = "la carte est déjà utilisée par un autre programme"
            self.annoncer(f"Image arrêtée : {erreur}")
        self._mettre_a_jour_boutons()

    def _son_perdu(self, texte):
        self.annoncer(f"Son coupé : {texte}")

    def _mettre_a_jour_boutons(self):
        en_cours = self.lecture.en_cours
        test = self._test is not None
        self.bouton.set_label("Arrêter" if en_cours else "Regarder")
        for classe, active in (("suggested-action", not en_cours), ("destructive-action", en_cours)):
            (self.bouton.add_css_class if active else self.bouton.remove_css_class)(classe)
        self.bouton.set_sensitive(bool(self.cartes) and not test)
        for ligne in (self.ligne_carte, self.ligne_mode):
            ligne.set_sensitive(not en_cours and not test)
        self.ligne_plein.set_sensitive(not test)
        self.bouton_test.set_sensitive(bool(self.cartes) and not en_cours)

    # --- Test de vitesse ------------------------------------------------------------------------------------------

    def _tester_ou_annuler(self, *_):
        if self._test is not None:
            self._test[1].set()
            return
        carte = self.carte()
        if carte is None:
            return
        modes = modes_a_tester(carte.modes)
        arret = threading.Event()
        fil = threading.Thread(target=self._tester, args=(carte, modes, arret), daemon=True)
        self._test = (fil, arret)
        self.bouton_test.set_label("Annuler")
        self.attente_test.set_visible(True)
        self.attente_test.start()
        self._mettre_a_jour_boutons()
        fil.start()

    def _tester(self, carte, modes, arret):
        """Fil du test : mesure les modes un par un et rend la main à l'interface par GLib.idle_add."""
        resultats = []
        for n, mode in enumerate(modes, 1):
            if arret.is_set():
                break
            GLib.idle_add(self.ligne_test.set_subtitle, f"Mode {n} sur {len(modes)} : {mode.libelle}")
            resultat = mesurer_mode(carte.chemin, mode, arret.is_set)
            resultats.append(resultat)
            if resultat.erreur and "busy" in resultat.erreur.lower():
                break                                   # la carte est prise ailleurs : inutile de continuer
        GLib.idle_add(self._test_fini, carte, modes, resultats, arret.is_set())

    def _test_fini(self, carte, modes, resultats, annule):
        self._test = None
        self.attente_test.stop()
        self.attente_test.set_visible(False)
        self.bouton_test.set_label("Tester")
        occupee = any("busy" in r.erreur.lower() for r in resultats)
        meilleur = choisir(modes, resultats)
        if annule:
            self.ligne_test.set_subtitle("Test annulé")
        elif occupee:
            self.ligne_test.set_subtitle("La carte est utilisée par un autre programme : ferme-le, puis recommence")
        elif meilleur is None:
            self.ligne_test.set_subtitle("Aucun mode n'a donné d'image : la source HDMI est-elle allumée ?")
        else:
            resultat = next(r for r in resultats if r.cle == meilleur.cle)
            self.ligne_test.set_subtitle(f"Le plus rapide : {meilleur.libelle} (≈ {resultat.latence_ms:.0f} ms)")
            self.reglages.tests[identifiant_carte(carte)] = [r.vers_dict() for r in resultats]
            self.reglages.mode = ""                     # le test fait repasser en automatique
            self._enregistrer()
            if self.carte() == carte:
                self._remplir_modes()
        self._mettre_a_jour_boutons()
        return GLib.SOURCE_REMOVE

    # --- Fermeture --------------------------------------------------------------------------------------------------

    def _fermeture(self, *_):
        if self._test is not None:
            self._test[1].set()
        self.lecture.arreter()
        self.moniteur.stop()
        if self._abonnement is not None:
            self._abonnement.force_exit()
        self._enregistrer()
        return False
