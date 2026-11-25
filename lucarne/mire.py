"""Mire et capture pour la mesure du retard réel (calculs dans retard).

La mire est une fenêtre plein écran sur la sortie branchée sur la carte ; la carte est lue en même temps par un
petit pipeline GStreamer (même mode que la lecture) qui réduit chaque image à 64 × 36 en niveaux de gris pour lire
la luminance du centre. Tout est piloté depuis la boucle GLib ; GStreamer remet ses images dans ses propres fils.
"""
import time

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gst", "1.0")
from gi.repository import Gdk, GLib, Gst, Gtk  # noqa: E402

from .mesure import caps_gst  # noqa: E402
from .retard import Front, apparier, fronts, luminance_centre, resumer  # noqa: E402

BASCULES = 20               # changements de la mire mesurés
PERIODE_S = 0.4             # un changement toutes les 0,4 s : moins de trois par seconde
CHAUFFE_S = 1.0             # la carte tourne déjà depuis ce temps avant le premier changement
DELAI_PREMIERE_IMAGE_S = 6
LARGEUR, HAUTEUR = 64, 36   # taille réduite de l'image analysée
TEXTE = "Lucarne mesure le retard de la carte · Échap pour arrêter"


class Mire(Gtk.Window):
    """Carré central noir ou blanc sur fond gris, plein écran sur un écran donné."""

    def __init__(self, moniteur, sur_echap):
        super().__init__(title="Lucarne — mire", decorated=False)
        self.blanc = False
        self.zone = Gtk.DrawingArea(hexpand=True, vexpand=True)
        self.zone.set_draw_func(self._dessiner)
        self.set_child(self.zone)
        touches = Gtk.EventControllerKey()
        touches.connect("key-pressed", lambda _c, cle, *_: cle == Gdk.KEY_Escape and (sur_echap() or True))
        self.add_controller(touches)
        self.fullscreen_on_monitor(moniteur)

    def _dessiner(self, _zone, cr, largeur, hauteur):
        cr.set_source_rgb(0.5, 0.5, 0.5)
        cr.paint()
        cote = hauteur * 0.5
        v = 1.0 if self.blanc else 0.0
        cr.set_source_rgb(v, v, v)
        cr.rectangle((largeur - cote) / 2, (hauteur - cote) / 2, cote, cote)
        cr.fill()
        cr.set_source_rgb(0.25, 0.25, 0.25)
        cr.set_font_size(max(14, hauteur / 50))
        etendue = cr.text_extents(TEXTE)
        cr.move_to((largeur - etendue.width) / 2, hauteur - etendue.height * 3)
        cr.show_text(TEXTE)


class MesureRetard:
    """Une mesure : demarrer(), annuler(). sur_fin(resultat, erreur) est appelé une fois, dans le fil GLib."""

    def __init__(self, carte, mode, moniteur, affichage_ms, sur_fin):
        self.carte, self.mode, self.moniteur = carte, mode, moniteur
        self.affichage_ms = affichage_ms
        self._sur_fin = sur_fin
        self._pipeline = None
        self._mire = None
        self._arrivees = {}         # pts -> heure d'arrivée (fils GStreamer)
        self._echantillons = []     # (heure d'arrivée, luminance du centre)
        self._decodages = []
        self._bascules = []         # Front à l'heure de présentation
        self._en_attente = []       # (compteur d'image, blanc, heure estimée) dont la présentation n'est pas connue
        self._exactes = 0
        self._prochaine = None
        self._premiere = False
        self._fini = False
        self._minuteries = []

    # --- Lancement ---

    def demarrer(self):
        decodeur = "jpegdec name=dec ! " if self.mode.compresse else ""
        description = (f"v4l2src name=src ! {caps_gst(self.mode)} ! {decodeur}videoconvert ! videoscale ! "
                       f"video/x-raw,format=GRAY8,width={LARGEUR},height={HAUTEUR} ! "
                       "appsink name=fin emit-signals=true sync=false max-buffers=8 drop=false")
        try:
            self._pipeline = Gst.parse_launch(description)
        except GLib.Error as e:
            self._finir(None, f"pipeline : {e.message}")
            return
        src = self._pipeline.get_by_name("src")
        src.set_property("device", self.carte.chemin)
        src.get_static_pad("src").add_probe(Gst.PadProbeType.BUFFER, self._arrivee)
        dec = self._pipeline.get_by_name("dec")
        if dec is not None:
            dec.get_static_pad("src").add_probe(Gst.PadProbeType.BUFFER, self._decode)
        self._pipeline.get_by_name("fin").connect("new-sample", self._image)
        self._pipeline.get_bus().add_watch(GLib.PRIORITY_DEFAULT, self._message)
        self._pipeline.set_state(Gst.State.PLAYING)

        self._mire = Mire(self.moniteur, self.annuler)
        self._mire.present()
        self._minuteries.append(GLib.timeout_add_seconds(DELAI_PREMIERE_IMAGE_S, self._sans_image))

    def annuler(self):
        self._finir(None, "mesure annulée")

    # --- Fils GStreamer ---

    def _arrivee(self, _pad, info):
        self._arrivees[info.get_buffer().pts] = time.monotonic()
        return Gst.PadProbeReturn.OK

    def _decode(self, _pad, info):
        t0 = self._arrivees.get(info.get_buffer().pts)
        if t0 is not None:
            self._decodages.append((time.monotonic() - t0) * 1000)
        return Gst.PadProbeReturn.OK

    def _image(self, puits):
        echantillon = puits.emit("pull-sample")
        tampon = echantillon.get_buffer()
        arrivee = self._arrivees.pop(tampon.pts, time.monotonic())
        ok, carte = tampon.map(Gst.MapFlags.READ)
        if ok:
            try:
                pas = (LARGEUR + 3) // 4 * 4          # les lignes GRAY8 sont alignées sur 4 octets
                self._echantillons.append((arrivee, luminance_centre(carte.data, LARGEUR, HAUTEUR, pas)))
            finally:
                tampon.unmap(carte)
        if not self._premiere:
            self._premiere = True
            GLib.idle_add(self._premiere_image)
        return Gst.FlowReturn.OK

    def _message(self, _bus, message):
        if message.type == Gst.MessageType.ERROR:
            texte = message.parse_error()[0].message
            if "busy" in texte.lower():
                texte = "la carte est utilisée par un autre programme (arrête la lecture)"
            self._finir(None, texte)
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    # --- Mire ---

    def _sans_image(self):
        if not self._premiere:
            self._finir(None, "la carte ne donne pas d'image")
        return GLib.SOURCE_REMOVE

    def _premiere_image(self):
        if not self._fini:
            self._minuteries.append(GLib.timeout_add(int(CHAUFFE_S * 1000), self._commencer))
        return GLib.SOURCE_REMOVE

    def _commencer(self):
        if not self._fini:
            self._mire.zone.add_tick_callback(self._tic)
        return GLib.SOURCE_REMOVE

    def _tic(self, zone, horloge):
        """À chaque image de l'écran : relève les présentations connues, et change la mire quand c'est l'heure."""
        if self._fini:
            return GLib.SOURCE_REMOVE
        self._relever(horloge)
        maintenant = horloge.get_frame_time() / 1e6
        if self._prochaine is None:
            self._prochaine = maintenant
        nombre = len(self._bascules) + len(self._en_attente)
        if nombre < BASCULES and maintenant >= self._prochaine:
            self._mire.blanc = not self._mire.blanc
            zone.queue_draw()
            intervalle = (horloge.get_refresh_info(0)[0] or 16667) / 1e6
            self._en_attente.append((horloge.get_frame_counter(), self._mire.blanc, maintenant + intervalle))
            self._prochaine += PERIODE_S
        if nombre >= BASCULES and not self._en_attente:
            # dernier changement présenté : on laisse à la carte le temps de le livrer
            self._minuteries.append(GLib.timeout_add(int(PERIODE_S * 1000), self._analyser))
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def _relever(self, horloge):
        restants = []
        for compteur, blanc, estimee in self._en_attente:
            temps = horloge.get_timings(compteur)
            if temps is not None and not temps.get_complete():
                restants.append((compteur, blanc, estimee))
                continue
            presentation = temps.get_presentation_time() if temps is not None else 0
            if presentation:
                self._exactes += 1
            self._bascules.append(Front(presentation / 1e6 if presentation else estimee, blanc))
        self._en_attente = restants

    # --- Résultat ---

    def _analyser(self):
        vus = fronts(list(self._echantillons))
        if not vus:
            self._finir(None, "la carte ne voit pas la mire : la sortie choisie est-elle branchée sur la carte ?")
            return GLib.SOURCE_REMOVE
        retards = apparier(self._bascules, vus)
        presentation = self._exactes >= len(self._bascules) / 2
        resultat = resumer(retards, list(self._decodages), self.affichage_ms, self.mode.cle, presentation)
        if resultat is None:
            self._finir(None, f"trop peu de changements retrouvés ({len(retards)} sur {len(self._bascules)})")
        else:
            self._finir(resultat, "")
        return GLib.SOURCE_REMOVE

    def _finir(self, resultat, erreur):
        if self._fini:
            return
        self._fini = True
        for minuterie in self._minuteries:
            if GLib.MainContext.default().find_source_by_id(minuterie):     # pas encore passée
                GLib.source_remove(minuterie)
        if self._pipeline is not None:
            self._pipeline.set_state(Gst.State.NULL)
            self._pipeline = None
        if self._mire is not None:
            self._mire.destroy()
            self._mire = None
        self._sur_fin(resultat, erreur)


def duree_rafraichissement_ms(moniteur):
    """Durée d'une image de l'écran (16,7 ms à 60 Hz)."""
    frequence = moniteur.get_refresh_rate() if moniteur is not None else 0      # en millihertz
    return 1e6 / frequence if frequence else 1000 / 60
