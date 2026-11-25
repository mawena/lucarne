"""Fenêtre de Lucarne : choix de la carte, du mode, du son et de la sortie ; bouton Regarder / Arrêter.

Pendant la lecture : capture d'image et enregistrement (boutons, ou touches S et R dans l'image). Hors lecture :
test de vitesse et mesure du retard réel avec la mire.
"""
from datetime import datetime
import os
import re
import threading
import time

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gst", "1.0")
from gi.repository import Adw, Gdk, Gio, GLib, Gst, Gtk  # noqa: E402

from . import appareils  # noqa: E402
from .commandes import TAMPON_SON_MIN, TAMPON_SON_MAX
from .config import Reglages, identifiant_carte
from .enregistrement import (MARGE_ARRET, Enregistreur, dossier_images, dossier_videos, nom_libre, place_libre,
                             relancer_en_attente, texte_duree, texte_taille)
from .lecture import Lecture
from .mesure import Resultat, choisir, mesurer_mode, modes_a_tester
from .modes import mode_depuis_cle, mode_par_defaut
from .retard import ResultatRetard

DELAI_RAFRAICHIR_MS = 300
RETARD_BLUETOOTH = "Sortie Bluetooth : le son arrive environ 200 ms après l'image."
ECRAN_CARTE = re.compile(r"2109|MS21|MACROSILICON|capture", re.IGNORECASE)   # écran « carte de capture » probable


def _court(chemin):
    maison = os.path.expanduser("~")
    return "~" + chemin[len(maison):] if chemin.startswith(maison + os.sep) else chemin


def _nom_ecran(ecran):
    modele = " ".join(x for x in (ecran.get_manufacturer(), ecran.get_model()) if x)
    g = ecran.get_geometry()
    taille = f"{g.width} × {g.height}"
    return f"{ecran.get_connector() or 'Écran'} — {modele} ({taille})" if modele else \
        f"{ecran.get_connector() or 'Écran'} ({taille})"


def _ouvrir(chemin):
    try:
        Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(chemin).get_uri(), None)
    except GLib.Error:
        pass


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
        self._mesure = None             # MesureRetard en cours
        self.enregistreur = None
        self._mode_lecture = None
        self.ecrans = []
        self.lecture = Lecture(self._lecture_finie, self._son_perdu, self._touche)

        self._construire()
        self._surveiller_cartes()
        self._surveiller_son()
        self._surveiller_ecrans()
        self._rafraichir_cartes()
        self._rafraichir_son()
        self.connect("close-request", self._fermeture)
        GLib.idle_add(lambda: relancer_en_attente([dossier_videos(), self._dossier_videos()]) and False)

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

        self.ligne_retard = Adw.ExpanderRow(title="Retard réel")
        self.ligne_ecran = Adw.ComboRow(title="Écran branché sur la carte", model=Gtk.StringList(),
                                        use_subtitle=True)
        self.ligne_ecran.connect("notify::selected", self._ecran_choisi)
        self.ligne_retard.add_row(self.ligne_ecran)
        mire = Adw.ActionRow(title="Mire par câble",
                             subtitle="Branche une sortie HDMI du PC sur l'entrée de la carte : un carré y clignote "
                                      "une dizaine de secondes, puis le retard s'affiche.")
        self.attente_retard = Gtk.Spinner(visible=False)
        mire.add_suffix(self.attente_retard)
        self.bouton_retard = Gtk.Button(label="Mesurer", valign=Gtk.Align.CENTER)
        self.bouton_retard.connect("clicked", self._mesurer_ou_annuler)
        mire.add_suffix(self.bouton_retard)
        self.ligne_retard.add_row(mire)
        image.add(self.ligne_retard)

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

        prises = Adw.PreferencesGroup(title="Capture et enregistrement",
                                      description="Pendant la lecture. Dans l'image : S pour une capture, R pour "
                                                  "enregistrer ou arrêter.")
        self.ligne_capture = Adw.ActionRow(title="Capture d'image", subtitle=self._texte_capture())
        self.bouton_capture = Gtk.Button(label="Capturer", valign=Gtk.Align.CENTER)
        self.bouton_capture.connect("clicked", self._capturer)
        self.ligne_capture.add_suffix(self.bouton_capture)
        prises.add(self.ligne_capture)

        self.ligne_enr = Adw.ActionRow(title="Enregistrement", subtitle=self._texte_enr_repos())
        self.bouton_enr = Gtk.Button(label="Enregistrer", valign=Gtk.Align.CENTER)
        self.bouton_enr.connect("clicked", self._enregistrer_ou_arreter)
        self.ligne_enr.add_suffix(self.bouton_enr)
        prises.add(self.ligne_enr)

        self.ligne_maniere = Adw.ComboRow(title="Manière d'enregistrer", use_subtitle=True, model=Gtk.StringList.new([
            "Brut, puis compressé : rien ne tourne pendant l'enregistrement, gros fichier temporaire",
            "Compressé en direct : petit fichier, la puce graphique compresse pendant l'enregistrement"]))
        self.ligne_maniere.set_selected(1 if self.reglages.enregistrement_direct else 0)
        self.ligne_maniere.connect("notify::selected", self._maniere_choisie)
        prises.add(self.ligne_maniere)

        self.ligne_dossier_images = self._ligne_dossier("Dossier des captures", "dossier_images", dossier_images)
        prises.add(self.ligne_dossier_images)
        self.ligne_dossier_videos = self._ligne_dossier("Dossier des vidéos", "dossier_videos", dossier_videos)
        prises.add(self.ligne_dossier_videos)
        page.add(prises)
        return page

    def _dossier_images(self):
        return dossier_images(self.reglages.dossier_images)

    def _dossier_videos(self):
        return dossier_videos(self.reglages.dossier_videos)

    def _texte_capture(self):
        return f"PNG dans {_court(self._dossier_images())}"

    def _texte_enr_repos(self):
        if self.reglages.enregistrement_direct:
            return f"Compressé en direct (≈ 2 à 4 Go/h), MP4 dans {_court(self._dossier_videos())}"
        return (f"Brut pendant l'enregistrement (≈ 24 Go/h en 720 × 480, 70 Go/h en 1080p), puis compressé en MP4 "
                f"dans {_court(self._dossier_videos())} par la file Gagarine")

    def _ligne_dossier(self, titre, champ, par_defaut):
        """Rangée d'un dossier : chemin en sous-titre, « Changer… » et retour au dossier par défaut."""
        ligne = Adw.ActionRow(title=titre, subtitle=_court(par_defaut(getattr(self.reglages, champ))))
        defaut = Gtk.Button(icon_name="edit-undo-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Dossier par défaut")
        defaut.add_css_class("flat")
        defaut.set_visible(bool(getattr(self.reglages, champ)))
        changer = Gtk.Button(label="Changer…", valign=Gtk.Align.CENTER)

        def appliquer(chemin):
            setattr(self.reglages, champ, chemin)
            self._enregistrer()
            ligne.set_subtitle(_court(par_defaut(chemin)))
            defaut.set_visible(bool(chemin))
            self.ligne_capture.set_subtitle(self._texte_capture())
            self._mettre_a_jour_boutons()

        def choisi(dialogue, resultat):
            try:
                dossier = dialogue.select_folder_finish(resultat)
            except GLib.Error:
                return                              # annulé
            if dossier is not None and dossier.get_path():
                appliquer(dossier.get_path())

        def ouvrir(*_):
            dialogue = Gtk.FileDialog(title=titre, modal=True)
            actuel = par_defaut(getattr(self.reglages, champ))
            if os.path.isdir(actuel):
                dialogue.set_initial_folder(Gio.File.new_for_path(actuel))
            dialogue.select_folder(self, None, choisi)
        changer.connect("clicked", ouvrir)
        defaut.connect("clicked", lambda *_: appliquer(""))
        ligne.add_suffix(defaut)
        ligne.add_suffix(changer)
        return ligne

    def _maniere_choisie(self, *_):
        self.reglages.enregistrement_direct = self.ligne_maniere.get_selected() == 1
        self._enregistrer()
        self._mettre_a_jour_boutons()

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

    def _surveiller_ecrans(self):
        self._modele_ecrans = Gdk.Display.get_default().get_monitors()
        self._modele_ecrans.connect("items-changed", lambda *_: self._plus_tard("ecrans", self._rafraichir_ecrans))
        self._rafraichir_ecrans()

    def _ecran_fenetre(self):
        surface = self.get_surface()
        return Gdk.Display.get_default().get_monitor_at_surface(surface) if surface else None

    def _rafraichir_ecrans(self):
        self.ecrans = [self._modele_ecrans.get_item(i) for i in range(self._modele_ecrans.get_n_items())]
        index = next((i for i, e in enumerate(self.ecrans) if e.get_connector() == self.reglages.ecran_mire), None)
        if index is None:
            index = next((i for i, e in enumerate(self.ecrans) if ECRAN_CARTE.search(_nom_ecran(e))), None)
        if index is None:
            ici = self._ecran_fenetre()
            index = next((i for i, e in enumerate(self.ecrans) if e != ici), 0)
        self._maj = True
        self._remplir(self.ligne_ecran, [_nom_ecran(e) for e in self.ecrans], index)
        self._maj = False

    def _ecran_choisi(self, *_):
        i = self.ligne_ecran.get_selected()
        if not self._maj and 0 <= i < len(self.ecrans):
            self.reglages.ecran_mire = self.ecrans[i].get_connector() or ""
            self._enregistrer()

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
        self._afficher_retard()

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
            def fin():
                self.lecture.arreter()
                self._mettre_a_jour_boutons()
            if self.enregistreur and self.enregistreur.en_cours:
                self.bouton.set_sensitive(False)
                self.enregistreur.arreter(puis=fin)
            else:
                fin()
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
        self._mode_lecture = mode
        self._mettre_a_jour_boutons()

    def _lecture_finie(self, erreur):
        if self.enregistreur is not None:
            self.enregistreur.mpv_termine()
        if erreur:
            if "busy" in erreur.lower() or "occupé" in erreur.lower():
                erreur = "la carte est déjà utilisée par un autre programme"
            self.annoncer(f"Image arrêtée : {erreur}")
        self._mettre_a_jour_boutons()

    def _son_perdu(self, texte):
        self.annoncer(f"Son coupé : {texte}")

    def _mettre_a_jour_boutons(self):
        en_cours = self.lecture.en_cours
        test = self._test is not None or self._mesure is not None
        enregistre = bool(self.enregistreur and self.enregistreur.en_cours)
        self.bouton.set_label("Arrêter" if en_cours else "Regarder")
        for classe, active in (("suggested-action", not en_cours), ("destructive-action", en_cours)):
            (self.bouton.add_css_class if active else self.bouton.remove_css_class)(classe)
        self.bouton.set_sensitive(bool(self.cartes) and not test)
        for ligne in (self.ligne_carte, self.ligne_mode):
            ligne.set_sensitive(not en_cours and not test)
        self.ligne_plein.set_sensitive(not test)
        self.bouton_test.set_sensitive(bool(self.cartes) and not en_cours and self._mesure is None)
        self.bouton_retard.set_sensitive(bool(self.cartes) and not en_cours and self._test is None)
        self.bouton_capture.set_sensitive(en_cours)
        self.bouton_enr.set_sensitive(en_cours)
        for ligne in (self.ligne_maniere, self.ligne_dossier_videos):
            ligne.set_sensitive(not enregistre)
        self.bouton_enr.set_label("Arrêter l'enregistrement" if enregistre else "Enregistrer")
        (self.bouton_enr.add_css_class if enregistre else self.bouton_enr.remove_css_class)("destructive-action")
        if not enregistre:
            self.ligne_enr.set_subtitle(self._texte_enr_repos())

    # --- Capture et enregistrement ------------------------------------------------------------------------------

    def _touche(self, action):
        if action == "capture":
            self._capturer()
        elif action == "enregistrement":
            self._enregistrer_ou_arreter()

    def _capturer(self, *_):
        if not self.lecture.en_cours:
            return
        dossier = self._dossier_images()
        try:
            os.makedirs(dossier, exist_ok=True)
        except OSError as e:
            self.annoncer(f"Capture impossible : {e.strerror}")
            return
        chemin = os.path.join(dossier, nom_libre(dossier, datetime.now(), [".png"]) + ".png")

        def fait(erreur, _donnee):
            if erreur:
                self.annoncer(f"Capture ratée : {erreur}")
                return
            self.lecture.afficher("Image enregistrée")
            toast = Adw.Toast(title=GLib.markup_escape_text(f"Image enregistrée : {os.path.basename(chemin)}"),
                              button_label="Ouvrir", timeout=5)
            toast.connect("button-clicked", lambda *_: _ouvrir(chemin))
            self.toasts.add_toast(toast)
        self.lecture.commande("screenshot-to-file", chemin, "video", rappel=fait, asynchrone=True)

    def _enregistrer_ou_arreter(self, *_):
        if self.enregistreur and self.enregistreur.en_cours:
            self.enregistreur.arreter(puis=self._mettre_a_jour_boutons)
            return
        if not self.lecture.en_cours or self._mode_lecture is None:
            return
        source = self.source()
        self.enregistreur = Enregistreur(self.lecture, 1 / float(self._mode_lecture.ips), self._enregistrement_fini,
                                         direct=self.reglages.enregistrement_direct)
        try:
            self.enregistreur.demarrer(source.nom if source else None, self._dossier_videos())
        except OSError as e:
            self.enregistreur = None
            self.annoncer(f"Enregistrement impossible : {e.strerror or e}")
            return
        self.lecture.afficher("● Enregistrement")
        GLib.timeout_add_seconds(1, self._suivre_enregistrement)
        self._suivre_enregistrement()
        self._mettre_a_jour_boutons()

    def _suivre_enregistrement(self):
        enr = self.enregistreur
        if enr is None or not enr.en_cours:
            return GLib.SOURCE_REMOVE
        libre = place_libre(os.path.dirname(enr.brut.video))
        self.ligne_enr.set_subtitle(f"● {texte_duree(time.monotonic() - enr.debut)} · {texte_taille(enr.taille())}"
                                    f" · reste {texte_taille(libre)} sur le disque")
        if libre < MARGE_ARRET:
            self.annoncer("Disque presque plein : enregistrement arrêté")
            enr.arreter(puis=self._mettre_a_jour_boutons)
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def _enregistrement_fini(self, brut, erreur):
        enr = self.enregistreur
        if enr is not None and enr.erreur_direct:
            self.annoncer(f"Compression en direct arrêtée : {enr.erreur_direct}")
        if enr is not None and enr.erreur_son:
            self.annoncer(f"Son non enregistré : {enr.erreur_son}")
        if brut is None:
            self.annoncer(f"Enregistrement perdu : {erreur}")
        elif erreur:
            self.annoncer(f"Enregistrement gardé brut dans {_court(os.path.dirname(brut.video))}, compression non "
                          f"lancée : {erreur}")
        else:
            self.lecture.afficher("Enregistrement fini")
            self.annoncer(f"Enregistrement fini : le MP4 arrivera dans {_court(brut.dossier)} (une notification "
                          "le dira)")
        self._mettre_a_jour_boutons()

    # --- Retard réel (mire) -------------------------------------------------------------------------------------

    def _afficher_retard(self):
        carte = self.carte()
        donnees = self.reglages.retards.get(identifiant_carte(carte)) if carte else None
        resultat = ResultatRetard.depuis_dict(donnees) if donnees else None
        if resultat is None:
            self.ligne_retard.set_subtitle("Pas encore mesuré : il faut brancher une sortie HDMI du PC sur la carte")
            return
        mode = mode_depuis_cle(resultat.mode, carte.modes)
        self.ligne_retard.set_subtitle(
            f"≈ {resultat.total_ms:.0f} ms de la source à l'écran, dont {resultat.carte_ms:.0f} ms dans la carte "
            f"({mode.libelle if mode else resultat.mode})")

    def _mesurer_ou_annuler(self, *_):
        if self._mesure is not None:
            self._mesure.annuler()
            return
        carte, mode, i = self.carte(), self.mode(), self.ligne_ecran.get_selected()
        if carte is None or mode is None or not 0 <= i < len(self.ecrans):
            return
        from .mire import MesureRetard, duree_rafraichissement_ms
        self._mesure = MesureRetard(carte, mode, self.ecrans[i], duree_rafraichissement_ms(self._ecran_fenetre()),
                                    lambda resultat, erreur: self._mesure_finie(carte, resultat, erreur))
        self.bouton_retard.set_label("Annuler")
        self.attente_retard.set_visible(True)
        self.attente_retard.start()
        self._mettre_a_jour_boutons()
        self._mesure.demarrer()

    def _mesure_finie(self, carte, resultat, erreur):
        self._mesure = None
        self.attente_retard.stop()
        self.attente_retard.set_visible(False)
        self.bouton_retard.set_label("Mesurer")
        if erreur:
            self.annoncer(f"Mesure du retard : {erreur}")
        else:
            self.reglages.retards[identifiant_carte(carte)] = resultat.vers_dict()
            self._enregistrer()
            self._afficher_retard()
            self.ligne_retard.set_expanded(True)
            self.annoncer(f"Retard réel ≈ {resultat.total_ms:.0f} ms (carte {resultat.carte_ms:.0f} ms, de "
                          f"{resultat.min_ms:.0f} à {resultat.max_ms:.0f} ; décodage {resultat.decodage_ms:.0f} ms ; "
                          f"affichage {resultat.affichage_ms:.0f} ms)")
        self._mettre_a_jour_boutons()

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
        if self.enregistreur and self.enregistreur.en_cours:
            self.enregistreur.arreter(puis=self.close)     # fichiers terminés et compression lancée, puis on ferme
            return True
        if self._mesure is not None:
            self._mesure.annuler()
        if self._test is not None:
            self._test[1].set()
        self.lecture.arreter()
        self.moniteur.stop()
        if self._abonnement is not None:
            self._abonnement.force_exit()
        self._enregistrer()
        return False
