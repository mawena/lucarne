"""Modes d'une carte de capture : format, résolution et images par seconde.

Les modes sont lus dans les « caps » GStreamer de la carte, par exemple :
``image/jpeg, width=(int)1920, height=(int)1080, framerate=(fraction){ 60/1, 50/1, 30/1 }``.
Pour chaque format et chaque résolution, on ne garde que la cadence la plus haute : c'est elle qui donne le moins de
retard (une image arrive toutes les 1/ips secondes).
"""
from dataclasses import dataclass
from fractions import Fraction
import re

# Nom GStreamer -> nom attendu par le démultiplexeur v4l2 de FFmpeg (option input_format de mpv)
FORMATS_BRUTS = {"YUY2": "yuyv422", "NV12": "nv12"}
NOMS_FORMATS = {"mjpeg": "MJPEG", "yuyv422": "YUYV (brut)", "nv12": "NV12 (brut)"}


@dataclass(frozen=True, order=True)
class Mode:
    format: str        # « mjpeg », « yuyv422 » ou « nv12 »
    largeur: int
    hauteur: int
    ips: Fraction      # images par seconde (la plus haute annoncée pour ce format et cette résolution)

    @property
    def cle(self):
        """Identifiant stable, gardé dans les réglages : « mjpeg-1920x1080-60 »."""
        return f"{self.format}-{self.largeur}x{self.hauteur}-{_texte_ips(self.ips, '_')}"

    @property
    def libelle(self):
        return f"{self.largeur} × {self.hauteur} · {_texte_ips(self.ips, ',')} i/s · {NOMS_FORMATS[self.format]}"

    @property
    def pixels(self):
        return self.largeur * self.hauteur

    @property
    def compresse(self):
        return self.format == "mjpeg"


def _texte_ips(ips, virgule):
    if ips.denominator == 1:
        return str(ips.numerator)
    return f"{float(ips):.2f}".rstrip("0").rstrip(".").replace(".", virgule)


def mode_depuis_cle(cle, modes):
    """Retrouve un mode par sa clé parmi ceux d'une carte, ou None."""
    return next((m for m in modes if m.cle == cle), None)


_CHAMP_ENTIER = r"{nom}=\(int\)(\d+)"
_FRACTION = re.compile(r"(\d+)/(\d+)")


def _cadences(structure):
    """Toutes les cadences d'une structure : une valeur, une liste { a, b } ou un intervalle [ a, b ]."""
    m = re.search(r"framerate=\(fraction\)(\{[^}]*\}|\[[^\]]*\]|\d+/\d+)", structure)
    if not m:
        return []
    return [Fraction(int(n), int(d)) for n, d in _FRACTION.findall(m.group(1)) if int(d) and int(n)]


def _format(structure):
    if structure.startswith("image/jpeg"):
        return "mjpeg"
    if structure.startswith("video/x-raw"):
        m = re.search(r"format=\(string\)(\w+)", structure)
        if m:
            return FORMATS_BRUTS.get(m.group(1))
    return None


def parser_caps(texte):
    """Liste des modes (un par format et résolution, à la cadence la plus haute), du plus rapide au plus lent."""
    meilleurs = {}
    for structure in texte.split(";"):
        structure = structure.strip()
        fmt = _format(structure)
        largeur = re.search(_CHAMP_ENTIER.format(nom="width"), structure)
        hauteur = re.search(_CHAMP_ENTIER.format(nom="height"), structure)
        cadences = _cadences(structure)
        if not (fmt and largeur and hauteur and cadences):
            continue
        cle = (fmt, int(largeur.group(1)), int(hauteur.group(1)))
        ips = max(cadences)
        if ips > meilleurs.get(cle, Fraction(0)):
            meilleurs[cle] = ips
    modes = [Mode(f, l, h, ips) for (f, l, h), ips in meilleurs.items()]
    # MJPEG d'abord, puis cadence décroissante, puis résolution décroissante
    return sorted(modes, key=lambda m: (not m.compresse, -m.ips, -m.pixels))


def mode_par_defaut(modes):
    """Sans test : la cadence la plus haute, puis la plus grande résolution à cette cadence (MJPEG de préférence)."""
    if not modes:
        return None
    return min(modes, key=lambda m: (-m.ips, not m.compresse, -m.pixels))
