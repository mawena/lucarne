"""Mesure du retard réel, de bout en bout, avec une mire envoyée par câble à la carte.

Montage : une sortie HDMI du PC est branchée sur l'entrée de la carte, à la place de la source habituelle. Lucarne
affiche en plein écran sur cette sortie un carré qui passe du noir au blanc toutes les 400 ms, sur fond gris (moins
de trois changements par seconde : sans danger pour les personnes sensibles aux flashs). Pour chaque changement :

- l'heure où il est arrivé à l'écran est donnée par GTK (heure de présentation de l'image, horloge monotone) ;
- l'heure où la carte a livré la première image qui le montre est notée à son arrivée dans le programme.

La différence (médiane sur une vingtaine de changements) est le retard de la carte : sortie HDMI, réception et
compression dans la carte, USB, remise au programme. Lucarne y ajoute ensuite le décodage de l'image et son affichage
(environ un rafraîchissement de l'écran) : c'est le retard total entre la source et ton écran.

Ce module ne contient que les calculs ; la mire et la capture sont dans mire.
"""
from dataclasses import dataclass, asdict
import statistics

CONTRASTE_MIN = 40      # écart minimal de luminance (sur 255) entre le noir et le blanc vus par la carte
RETARD_MAX_S = 0.35     # au-delà, le front vu ne peut pas venir de ce changement (il en arrive un toutes les 0,4 s)
MESURES_MIN = 5         # en dessous, le résultat n'est pas fiable


@dataclass(frozen=True)
class Front:
    instant: float          # secondes, horloge monotone
    blanc: bool             # vrai : passage au blanc


def fronts(echantillons, contraste_min=CONTRASTE_MIN):
    """Changements noir/blanc vus par la carte, à partir de [(instant, luminance du centre)] dans l'ordre.

    Le seuil est à mi-chemin entre le plus sombre et le plus clair vus ; sans assez d'écart, la carte ne voit pas
    la mire et la liste est vide.
    """
    if len(echantillons) < 2:
        return []
    luminances = [l for _, l in echantillons]
    bas, haut = min(luminances), max(luminances)
    if haut - bas < contraste_min:
        return []
    seuil = (bas + haut) / 2
    etat = luminances[0] > seuil
    resultat = []
    for instant, luminance in echantillons[1:]:
        blanc = luminance > seuil
        if blanc != etat:
            resultat.append(Front(instant, blanc))
            etat = blanc
    return resultat


def apparier(bascules, vus, retard_max_s=RETARD_MAX_S):
    """Retards en secondes : pour chaque changement de la mire, le premier front de même sens vu ensuite."""
    retards = []
    j = 0
    for bascule in bascules:
        while j < len(vus) and vus[j].instant < bascule.instant:
            j += 1
        if j < len(vus) and vus[j].blanc == bascule.blanc and vus[j].instant - bascule.instant <= retard_max_s:
            retards.append(vus[j].instant - bascule.instant)
            j += 1
    return retards


@dataclass(frozen=True)
class ResultatRetard:
    mode: str               # clé du mode mesuré
    carte_ms: float         # médiane : changement à l'écran -> image livrée par la carte
    min_ms: float
    max_ms: float
    decodage_ms: float      # médiane du décodage de l'image
    affichage_ms: float     # un rafraîchissement de l'écran où Lucarne affiche l'image
    mesures: int
    presentation: bool      # heures de présentation données par le compositeur (sinon estimées par GTK)

    @property
    def total_ms(self):
        return self.carte_ms + self.decodage_ms + self.affichage_ms

    def vers_dict(self):
        return asdict(self)

    @classmethod
    def depuis_dict(cls, d):
        try:
            return cls(**{k: d[k] for k in cls.__dataclass_fields__})
        except (KeyError, TypeError):
            return None


def resumer(retards_s, decodages_ms, affichage_ms, mode, presentation):
    """Résultat d'une mesure, ou None s'il y a trop peu de changements retrouvés."""
    if len(retards_s) < MESURES_MIN:
        return None
    retards_ms = [r * 1000 for r in retards_s]
    return ResultatRetard(
        mode=mode,
        carte_ms=round(statistics.median(retards_ms), 1),
        min_ms=round(min(retards_ms), 1),
        max_ms=round(max(retards_ms), 1),
        decodage_ms=round(statistics.median(decodages_ms), 1) if decodages_ms else 0.0,
        affichage_ms=round(affichage_ms, 1),
        mesures=len(retards_ms),
        presentation=presentation,
    )


def luminance_centre(octets, largeur, hauteur, pas=None, part=0.2):
    """Luminance moyenne du rectangle central (part de la largeur et de la hauteur) d'une image en niveaux de gris."""
    pas = pas or largeur
    l, h = max(1, int(largeur * part)), max(1, int(hauteur * part))
    x0, y0 = (largeur - l) // 2, (hauteur - h) // 2
    total = 0
    for y in range(y0, y0 + h):
        debut = y * pas + x0
        total += sum(octets[debut:debut + l])
    return total / (l * h)
