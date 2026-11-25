"""Test de la carte : pour chaque mode, ce que la carte livre vraiment et ce que coûte chaque image.

Chaque mode est ouvert dans un petit pipeline GStreamer (v4l2src, décodage JPEG si besoin, fakesink sans
synchronisation) pendant une seconde et demie, après une demi-seconde de chauffe. On mesure :

- la cadence réelle (une carte annonce parfois 60 i/s et en livre 30) ;
- l'attente : temps entre l'horodatage de l'image par le noyau (fin de la réception USB) et sa remise au programme ;
- le décodage : temps passé dans jpegdec (nul pour un format brut).

La latence estimée d'un mode = un intervalle d'image (la carte envoie une image complète) + attente + décodage.
C'est une comparaison entre modes, pas le retard total de bout en bout : l'encodage dans la carte et l'affichage
(compositeur, écran) s'y ajoutent, à peu près pareils pour tous les modes.
"""
from dataclasses import dataclass, asdict
from fractions import Fraction
import statistics
import time

CHAUFFE_S = 0.5
DUREE_S = 1.5
TOLERANCE_MS = 1.0      # deux modes à moins d'1 ms l'un de l'autre : on prend la plus grande résolution
ATTENTE_MAX_MS = 500.0  # au-delà, l'horodatage n'est pas fiable : on l'ignore


@dataclass(frozen=True)
class Resultat:
    cle: str                 # clé du mode (Mode.cle)
    ips_reel: float          # images par seconde réellement reçues (0 : le mode n'a rien donné)
    attente_ms: float        # médiane de l'attente (horodatage noyau -> programme)
    decodage_ms: float       # médiane du décodage
    octets: int              # taille moyenne d'une image reçue
    erreur: str = ""

    @property
    def valide(self):
        return self.ips_reel > 0 and not self.erreur

    @property
    def latence_ms(self):
        """Latence estimée (voir l'en-tête du module) ; infinie si le mode ne marche pas."""
        if not self.valide:
            return float("inf")
        return 1000.0 / self.ips_reel + self.attente_ms + self.decodage_ms

    def vers_dict(self):
        return asdict(self)

    @classmethod
    def depuis_dict(cls, d):
        return cls(**{k: d[k] for k in ("cle", "ips_reel", "attente_ms", "decodage_ms", "octets", "erreur") if k in d})


def choisir(modes, resultats):
    """Mode le plus rapide d'après les résultats ; entre modes à TOLERANCE_MS près, la plus grande résolution."""
    par_cle = {r.cle: r for r in resultats if r.valide}
    candidats = [m for m in modes if m.cle in par_cle]
    if not candidats:
        return None
    meilleure = min(par_cle[m.cle].latence_ms for m in candidats)
    proches = [m for m in candidats if par_cle[m.cle].latence_ms <= meilleure + TOLERANCE_MS]
    return max(proches, key=lambda m: (m.pixels, m.compresse, -par_cle[m.cle].latence_ms))


def caps_gst(mode):
    """Caps GStreamer d'un mode ; la cadence doit être une fraction (« 60/1 »), « 60 » serait lu comme un entier."""
    ips = f"{mode.ips.numerator}/{mode.ips.denominator}"
    if mode.compresse:
        return f"image/jpeg,width={mode.largeur},height={mode.hauteur},framerate={ips}"
    gst = {"yuyv422": "YUY2", "nv12": "NV12"}[mode.format]
    return f"video/x-raw,format={gst},width={mode.largeur},height={mode.hauteur},framerate={ips}"


def mesurer_mode(chemin, mode, arret=None):
    """Mesure un mode sur la carte /dev/videoN. Bloquant (≈ 2 s) : à lancer hors du fil de l'interface.

    arret : fonction sans argument qui renvoie True pour interrompre le test au plus vite.
    """
    import gi
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst
    Gst.init(None)

    decodeur = "jpegdec name=dec ! " if mode.compresse else ""
    description = (f"v4l2src device={chemin} name=src ! {caps_gst(mode)} ! {decodeur}"
                   "fakesink name=fin sync=false async=false")
    try:
        pipeline = Gst.parse_launch(description)
    except Exception as e:          # élément absent (jpegdec, v4l2src) : rien à mesurer
        return Resultat(mode.cle, 0.0, 0.0, 0.0, 0, f"pipeline : {e}")

    src = pipeline.get_by_name("src")
    dec = pipeline.get_by_name("dec")
    debut = {"t": None}
    arrivees, attentes, decodages, tailles = [], [], [], []
    entree_dec = {}

    def sur_image(pad, info):
        maintenant = time.monotonic()
        if debut["t"] is None:
            debut["t"] = maintenant
        if maintenant - debut["t"] < CHAUFFE_S:
            return Gst.PadProbeReturn.OK
        tampon = info.get_buffer()
        arrivees.append(maintenant)
        tailles.append(tampon.get_size())
        horloge = src.get_clock()
        if horloge is not None and tampon.pts != Gst.CLOCK_TIME_NONE:
            courant = horloge.get_time() - src.get_base_time()
            attente = (courant - tampon.pts) / 1e6
            if 0 <= attente <= ATTENTE_MAX_MS:
                attentes.append(attente)
        if dec is not None:
            entree_dec[tampon.pts] = time.perf_counter()
        return Gst.PadProbeReturn.OK

    def sur_decode(pad, info):
        t0 = entree_dec.pop(info.get_buffer().pts, None)
        if t0 is not None:
            decodages.append((time.perf_counter() - t0) * 1000)
        return Gst.PadProbeReturn.OK

    src.get_static_pad("src").add_probe(Gst.PadProbeType.BUFFER, sur_image)
    if dec is not None:
        dec.get_static_pad("src").add_probe(Gst.PadProbeType.BUFFER, sur_decode)

    erreur = ""
    bus = pipeline.get_bus()
    pipeline.set_state(Gst.State.PLAYING)
    limite = time.monotonic() + CHAUFFE_S + DUREE_S + 3.0      # 3 s de marge pour l'ouverture de la carte
    while time.monotonic() < limite:
        if arret and arret():
            erreur = "interrompu"
            break
        message = bus.timed_pop_filtered(50 * Gst.MSECOND, Gst.MessageType.ERROR | Gst.MessageType.EOS)
        if message and message.type == Gst.MessageType.ERROR:
            erreur = message.parse_error()[0].message
            break
        if debut["t"] is not None and time.monotonic() - debut["t"] >= CHAUFFE_S + DUREE_S:
            break
    pipeline.set_state(Gst.State.NULL)

    if len(arrivees) >= 2:
        ips = (len(arrivees) - 1) / (arrivees[-1] - arrivees[0])
    else:
        ips = 0.0
        erreur = erreur or "aucune image reçue"
    return Resultat(
        cle=mode.cle,
        ips_reel=round(ips, 2),
        attente_ms=round(statistics.median(attentes), 2) if attentes else 0.0,
        decodage_ms=round(statistics.median(decodages), 2) if decodages else 0.0,
        octets=int(statistics.fmean(tailles)) if tailles else 0,
        erreur=erreur,
    )


def modes_a_tester(modes):
    """Modes candidats : à la cadence annoncée la plus haute de la carte, et ceux à 90 % de cette cadence.

    Un mode plus lent ne peut pas gagner : son seul intervalle d'image dépasse déjà la latence des plus rapides.
    """
    if not modes:
        return []
    plus_haute = max(m.ips for m in modes)
    return [m for m in modes if m.ips >= plus_haute * Fraction(9, 10)]
