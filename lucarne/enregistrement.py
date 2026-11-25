"""Enregistrement de ce qui passe à l'écran : brut pendant la lecture, compressé ensuite par la file Gagarine.

Pendant l'enregistrement, rien ne doit retarder l'image :

- l'image est copiée telle que la carte l'envoie (MJPEG) par mpv lui-même (propriété ``stream-record``), sans
  décodage ni compression de plus ;
- le son de la carte est enregistré en FLAC par un petit pipeline GStreamer (pulsesrc), à côté du renvoi vers le
  casque.

Ces fichiers bruts sont gros (≈ 24 Go/h en 720×480, ≈ 70 Go/h en 1080p). Ils vont dans <Vidéos>/Lucarne/brut avec
une description JSON, puis sont compressés en H.264 + AAC dès la fin de l'enregistrement par ``lucarne --compresser``
(module compression), lancé à part par systemd-run et passé par la file Gagarine en priorité « fond ».

Calage du son : mpv remet l'horloge de la vidéo à zéro au début de l'enregistrement. Le son démarre donc d'abord et
l'heure de son premier échantillon est gardée (horloge monotone, celle de GStreamer) ; le début de la vidéo est
estimé au moment où mpv confirme l'enregistrement, moins un intervalle d'image. La compression coupe le début du son
d'autant (decalage_s).
"""
from dataclasses import dataclass, asdict
from datetime import datetime
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

from gi.repository import GLib

GIO = 1024 ** 3
PLACE_MIN_DEPART = 4 * GIO      # en dessous, l'enregistrement ne démarre pas
MARGE_ARRET = 2 * GIO           # en dessous, l'enregistrement en cours s'arrête
PILOTES_VAAPI = {"i915", "xe", "amdgpu", "radeon"}
DELAI_SON_MAX_S = 1.5           # sans premier échantillon de son après ce délai, la vidéo démarre quand même
DELAI_REPONSE_MPV_S = 3


def _dossier_utilisateur(repertoire, secours):
    base = GLib.get_user_special_dir(repertoire) or os.path.expanduser(secours)
    return os.path.join(base, "Lucarne")


def dossier_videos():
    return _dossier_utilisateur(GLib.UserDirectory.DIRECTORY_VIDEOS, "~/Videos")


def dossier_images():
    return _dossier_utilisateur(GLib.UserDirectory.DIRECTORY_PICTURES, "~/Pictures")


def nom_libre(dossier, instant, extensions, autres=()):
    """« Lucarne 2026-11-25 08-19-00 », suivi de « (2) », « (3) »… si un fichier de ce nom existe déjà.

    extensions : extensions à vérifier dans dossier ; autres : couples (dossier, extension) à vérifier aussi.
    """
    base = "Lucarne " + instant.strftime("%Y-%m-%d %H-%M-%S")
    n = 1
    while True:
        nom = base if n == 1 else f"{base} ({n})"
        chemins = [os.path.join(dossier, nom + e) for e in extensions]
        chemins += [os.path.join(d, nom + e) for d, e in autres]
        if not any(os.path.exists(c) for c in chemins):
            return nom
        n += 1


def place_libre(dossier):
    """Octets libres pour l'utilisateur sur le disque du dossier (ou de son plus proche parent existant)."""
    while dossier and not os.path.exists(dossier):
        dossier = os.path.dirname(dossier)
    etat = os.statvfs(dossier or "/")
    return etat.f_bavail * etat.f_frsize


def texte_taille(octets):
    if octets >= GIO:
        return f"{octets / GIO:.1f} Go".replace(".", ",")
    return f"{octets / 1024 ** 2:.0f} Mo"


def texte_duree(secondes):
    secondes = int(secondes)
    h, m, s = secondes // 3600, secondes // 60 % 60, secondes % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


@dataclass
class Brut:
    """Un enregistrement brut en attente de compression, décrit dans <dossier>/brut/<nom>.json."""
    nom: str                    # « Lucarne 2026-11-25 08-19-00 »
    dossier: str                # dossier des vidéos finies (<Vidéos>/Lucarne)
    video: str                  # MJPEG copié par mpv (.mkv)
    son: str = ""               # FLAC ; vide sans son
    decalage_s: float = 0.0     # début de la vidéo moins début du son (positif : le son a commencé avant)
    erreur: str = ""            # rempli quand la compression a échoué : on ne la relance plus toute seule

    @property
    def sortie(self):
        return os.path.join(self.dossier, self.nom + ".mp4")

    @property
    def description(self):
        return os.path.join(self.dossier, "brut", self.nom + ".json")

    def enregistrer(self):
        os.makedirs(os.path.dirname(self.description), exist_ok=True)
        provisoire = self.description + ".tmp"
        with open(provisoire, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, ensure_ascii=False, indent=2)
        os.replace(provisoire, self.description)

    @classmethod
    def charger(cls, chemin):
        """Brut décrit par un fichier JSON, ou None s'il est illisible."""
        try:
            with open(chemin, encoding="utf-8") as f:
                donnees = json.load(f)
            return cls(**{k: v for k, v in donnees.items() if k in cls.__dataclass_fields__})
        except (OSError, ValueError, TypeError):
            return None


def en_attente(dossier):
    """Enregistrements bruts pas encore compressés (sans échec noté), du plus ancien au plus récent."""
    bruts = (Brut.charger(c) for c in sorted(glob.glob(os.path.join(dossier, "brut", "*.json"))))
    return [b for b in bruts if b is not None and not b.erreur and os.path.exists(b.video)]


# --- Compression ---------------------------------------------------------------------------------------------------

def trouver_rendu(racine="/sys/class/drm"):
    """Nœud de rendu d'une puce graphique qui sait compresser en H.264 par VA-API (Intel, AMD), ou None."""
    for chemin in sorted(glob.glob(os.path.join(racine, "renderD*"))):
        pilote = os.path.basename(os.path.realpath(os.path.join(chemin, "device", "driver")))
        if pilote in PILOTES_VAAPI:
            return "/dev/dri/" + os.path.basename(chemin)
    return None


def filtre_son(decalage_s):
    """Filtre FFmpeg qui cale le son sur l'image : coupe son début, ou le retarde s'il a commencé après."""
    if decalage_s >= 0.0005:
        return f"atrim=start={decalage_s:.3f},asetpts=PTS-STARTPTS"
    if decalage_s <= -0.0005:
        return f"adelay={round(-decalage_s * 1000)}:all=1"
    return None


def commandes_compression(brut, rendu=None):
    """Commandes ffmpeg à essayer dans l'ordre : VA-API si une puce le permet, puis x264 (processeur).

    Le résultat est écrit dans <sortie>.part, renommé seulement si ffmpeg a réussi.
    """
    def construire(avant_entrees, options_video):
        argv = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y", *avant_entrees, "-i", brut.video]
        if brut.son:
            argv += ["-i", brut.son]
        argv += ["-map", "0:v:0"]
        if brut.son:
            argv += ["-map", "1:a:0"]
        argv += options_video
        if brut.son:
            filtre = filtre_son(brut.decalage_s)
            if filtre:
                argv += ["-af", filtre]
            argv += ["-c:a", "aac", "-b:a", "192k", "-shortest"]
        return argv + ["-movflags", "+faststart", "-f", "mp4", brut.sortie + ".part"]

    commandes = []
    if rendu:
        commandes.append(construire(["-vaapi_device", rendu],
                                    ["-vf", "format=nv12,hwupload", "-c:v", "h264_vaapi", "-qp", "23"]))
    commandes.append(construire([], ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p"]))
    return commandes


def dans_la_file(argv, nom, gagarine=None):
    """Passe une commande lourde par la file Gagarine (priorité « fond ») ; sans Gagarine, en priorité basse."""
    gagarine = gagarine if gagarine is not None else shutil.which("gagarine")
    if gagarine:
        return [gagarine, "file", f"lucarne {nom}", "1", "4", "--priorite", "fond", "--", *argv]
    return ["nice", "-n", "19", *argv]


def lanceur_lucarne():
    """Commande qui relance Lucarne : le script lancé (dépôt ou /usr/bin), sinon « lucarne » dans le PATH."""
    script = os.path.realpath(sys.argv[0]) if sys.argv and sys.argv[0] else ""
    if os.path.basename(script) == "lucarne" and os.path.isfile(script):
        return [sys.executable, script]
    return ["lucarne"]


def commande_lancement(brut, lanceur):
    """systemd-run : la compression continue même si Lucarne est fermée, et ne tourne jamais deux fois."""
    unite = "lucarne-compression-" + re.sub(r"[^0-9A-Za-z]+", "-", brut.nom.removeprefix("Lucarne ")).strip("-").lower()
    return ["systemd-run", "--user", "--collect", "--quiet", f"--unit={unite}",
            f"--description=Lucarne : compression de {brut.nom}", *lanceur, "--compresser", brut.description]


def lancer_compression(brut, lanceur=None):
    """Lance la compression à part ; renvoie un texte d'erreur, vide si elle est partie."""
    try:
        r = subprocess.run(commande_lancement(brut, lanceur or lanceur_lucarne()), stdout=subprocess.DEVNULL,
                           stderr=subprocess.PIPE, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as e:
        return str(e)
    if r.returncode == 0:
        return ""
    lignes = [l for l in r.stderr.splitlines() if l.strip()]
    return lignes[-1] if lignes else f"systemd-run a échoué (code {r.returncode})"


def relancer_en_attente():
    """Au lancement : relance la compression des enregistrements restés bruts (Lucarne ou le PC arrêtés avant la
    fin). Une compression déjà en cours n'est pas doublée : systemd-run refuse une unité qui existe déjà."""
    for brut in en_attente(dossier_videos()):
        lancer_compression(brut)


# --- Enregistrement en cours ------------------------------------------------------------------------------------------

class Enregistreur:
    """Un enregistrement pendant la lecture. Tout se passe dans le fil GLib.

    sur_fin(brut, erreur) : l'enregistrement est fini. brut est None s'il n'y a rien à garder ; sinon erreur dit
    seulement si la compression n'a pas pu être lancée.
    """

    def __init__(self, lecture, intervalle_image_s, sur_fin):
        self.lecture = lecture
        self._intervalle = intervalle_image_s
        self._sur_fin = sur_fin
        self.brut = None
        self.debut = None               # heure monotone du début, pour la durée affichée
        self.en_cours = False
        self.erreur_son = ""
        self._pipeline = None
        self._debut_son = None
        self._debut_video = None
        self._video_lancee = False
        self._fini = False

    def demarrer(self, source):
        """Démarre le son puis l'image. Lève OSError si le dossier est inaccessible ou le disque trop plein."""
        dossier = dossier_videos()
        dossier_brut = os.path.join(dossier, "brut")
        os.makedirs(dossier_brut, exist_ok=True)
        libre = place_libre(dossier_brut)
        if libre < PLACE_MIN_DEPART:
            raise OSError(f"il ne reste que {texte_taille(libre)} sur le disque")
        nom = nom_libre(dossier, datetime.now(), [".mp4"], [(dossier_brut, ".mkv"), (dossier_brut, ".json")])
        self.brut = Brut(nom, dossier, os.path.join(dossier_brut, nom + ".mkv"),
                         os.path.join(dossier_brut, nom + ".flac") if source else "")
        self.en_cours = True
        self.debut = time.monotonic()
        if source and self._demarrer_son(source):
            GLib.timeout_add(int(DELAI_SON_MAX_S * 1000), self._demarrer_video)
        else:
            self.brut.son = ""
            self._demarrer_video()

    def taille(self):
        total = 0
        for chemin in (self.brut.video, self.brut.son) if self.brut else ():
            try:
                total += os.path.getsize(chemin) if chemin else 0
            except OSError:
                pass
        return total

    def arreter(self, puis=None):
        """Fin demandée : mpv ferme le fichier vidéo, puis le son est terminé et la compression lancée."""
        if not self.en_cours:
            if puis:
                puis()
            return
        fait = {"v": False}

        def terminer(*_):
            if fait["v"]:
                return GLib.SOURCE_REMOVE
            fait["v"] = True
            self._terminer()
            if puis:
                puis()
            return GLib.SOURCE_REMOVE
        self.lecture.commande("set_property", "stream-record", "", rappel=terminer)
        GLib.timeout_add_seconds(DELAI_REPONSE_MPV_S, terminer)

    def mpv_termine(self):
        """mpv s'est arrêté : il a déjà fermé le fichier vidéo."""
        if self.en_cours:
            self._terminer()

    # --- Son ---

    def _demarrer_son(self, source):
        from gi.repository import Gst
        try:
            pipeline = Gst.parse_launch("pulsesrc name=src ! audioconvert ! audio/x-raw,format=S16LE ! flacenc ! "
                                        "filesink name=fin")
        except GLib.Error as e:
            self.erreur_son = e.message
            return False
        pipeline.get_by_name("src").set_property("device", source)
        pipeline.get_by_name("fin").set_property("location", self.brut.son)
        pipeline.use_clock(Gst.SystemClock.obtain())        # horloge monotone, comme time.monotonic()

        def premier(pad, info):
            tampon = info.get_buffer()
            if tampon.pts != Gst.CLOCK_TIME_NONE:
                self._debut_son = (pipeline.get_base_time() + tampon.pts) / Gst.SECOND
                GLib.idle_add(self._demarrer_video)
            return Gst.PadProbeReturn.REMOVE
        pipeline.get_by_name("src").get_static_pad("src").add_probe(Gst.PadProbeType.BUFFER, premier)
        pipeline.get_bus().add_watch(GLib.PRIORITY_DEFAULT, self._message_son)
        if pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            pipeline.set_state(Gst.State.NULL)
            self.erreur_son = "le son de la carte ne s'ouvre pas"
            return False
        self._pipeline = pipeline
        return True

    def _message_son(self, _bus, message):
        from gi.repository import Gst
        if message.type == Gst.MessageType.ERROR and self._pipeline is not None:
            self.erreur_son = message.parse_error()[0].message
            self._pipeline.set_state(Gst.State.NULL)
            self._pipeline = None
            self._demarrer_video()
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def _arreter_son(self):
        """Termine le FLAC proprement (fin de flux), en attendant au plus 2 s."""
        from gi.repository import Gst
        pipeline, self._pipeline = self._pipeline, None
        if pipeline is None:
            return
        bus = pipeline.get_bus()
        bus.remove_watch()                  # on lit la fin de flux ici, sans la boucle GLib
        pipeline.send_event(Gst.Event.new_eos())
        bus.timed_pop_filtered(2 * Gst.SECOND, Gst.MessageType.EOS | Gst.MessageType.ERROR)
        pipeline.set_state(Gst.State.NULL)

    # --- Image ---

    def _demarrer_video(self):
        if self._video_lancee or not self.en_cours:
            return GLib.SOURCE_REMOVE
        self._video_lancee = True
        envoi = time.monotonic()

        def reponse(erreur, _donnee):
            if erreur:
                self._echec(f"mpv n'enregistre pas : {erreur}")
                return
            # mpv copie le premier paquet reçu après la commande ; il a été pris par la carte une image plus tôt
            self._debut_video = (envoi + time.monotonic()) / 2 - self._intervalle
        self.lecture.commande("set_property", "stream-record", self.brut.video, rappel=reponse)
        return GLib.SOURCE_REMOVE

    # --- Fin ---

    def _echec(self, erreur):
        if self._fini:
            return
        self._fini = True
        self.en_cours = False
        self._arreter_son()
        for chemin in (self.brut.video, self.brut.son):
            if chemin and os.path.exists(chemin):
                os.unlink(chemin)
        self._sur_fin(None, erreur)

    def _terminer(self):
        if self._fini:
            return
        self._fini = True
        self.en_cours = False
        self._arreter_son()
        brut = self.brut
        if not (os.path.exists(brut.video) and os.path.getsize(brut.video) > 0):
            if brut.son and os.path.exists(brut.son):
                os.unlink(brut.son)
            self._sur_fin(None, "aucune image n'a été enregistrée")
            return
        if brut.son and not (os.path.exists(brut.son) and os.path.getsize(brut.son) > 0):
            brut.son = ""
        if brut.son and self._debut_son is not None and self._debut_video is not None:
            brut.decalage_s = round(self._debut_video - self._debut_son, 4)
        try:
            brut.enregistrer()
        except OSError as e:
            self._sur_fin(brut, f"description non écrite : {e.strerror}")
            return
        self._sur_fin(brut, lancer_compression(brut))
