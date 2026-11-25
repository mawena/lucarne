"""Réglages gardés entre deux lancements, dans $XDG_CONFIG_HOME/lucarne/reglages.json.

Les résultats du test de chaque carte y sont aussi gardés (clé : nom de la carte), pour ne pas
refaire le test à chaque lancement.
"""
from dataclasses import dataclass, field, asdict
import json
import os

from .commandes import TAMPON_SON_MS


def chemin_reglages():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "lucarne", "reglages.json")


@dataclass
class Reglages:
    carte: str = ""                 # nom de la dernière carte choisie
    mode: str = ""                  # clé du mode choisi ; vide = automatique (le plus rapide)
    sortie: str = ""                # nœud de la sortie audio ; vide = sortie par défaut du système
    tampon_son_ms: int = TAMPON_SON_MS
    plein_ecran: bool = False
    tests: dict = field(default_factory=dict)   # identifiant de carte -> liste de Resultat.vers_dict()
    retards: dict = field(default_factory=dict)  # identifiant de carte -> ResultatRetard.vers_dict() (dernière mesure)
    ecran_mire: str = ""            # connecteur de l'écran branché sur la carte pour la mesure du retard

    @classmethod
    def charger(cls, chemin=None):
        chemin = chemin or chemin_reglages()
        try:
            with open(chemin, encoding="utf-8") as f:
                donnees = json.load(f)
        except (OSError, ValueError):
            return cls()
        if not isinstance(donnees, dict):
            return cls()
        connus = {k: v for k, v in donnees.items() if k in cls.__dataclass_fields__}
        try:
            return cls(**connus)
        except TypeError:
            return cls()

    def enregistrer(self, chemin=None):
        chemin = chemin or chemin_reglages()
        os.makedirs(os.path.dirname(chemin), exist_ok=True)
        provisoire = chemin + ".tmp"
        with open(provisoire, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, ensure_ascii=False, indent=2)
        os.replace(provisoire, chemin)


def identifiant_carte(carte):
    """Identifiant stable d'une carte : son nom (fabricant et produit USB), le même sur n'importe quel port."""
    return carte.nom
