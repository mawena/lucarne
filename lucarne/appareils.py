"""Appareils du poste : cartes de capture (image), sources audio (son de la carte) et sorties audio.

- Cartes : moniteur de périphériques GStreamer (classe « Video/Source »), qui donne aussi les modes annoncés.
- Son : ``pactl -f json`` (PipeWire par sa couche PulseAudio).
- Association : une carte HDMI-USB expose l'image et le son sur deux interfaces du même appareil USB ; on relie la
  carte à la source audio dont le chemin sysfs passe par le même appareil USB.
"""
from dataclasses import dataclass, field
import json
import os
import re
import subprocess

from .modes import parser_caps

_INTERFACE_USB = re.compile(r"^\d+-[\d.]+:\d+\.\d+$")   # « 3-3:1.2 » : interface 2 de l'appareil 3-3


@dataclass(frozen=True)
class Carte:
    nom: str
    chemin: str                     # /dev/videoN
    usb: str | None = None          # appareil USB dans sysfs (« /devices/…/usb3/3-3 »)
    modes: tuple = field(default=(), compare=False)


@dataclass(frozen=True)
class Audio:
    nom: str                        # nom du nœud PipeWire (« alsa_input.usb-… », « bluez_output.… »)
    description: str
    usb: str | None = None
    bluetooth: bool = False


def appareil_usb(chemin_sysfs):
    """Appareil USB qui contient un chemin sysfs, sans le préfixe /sys, ou None s'il n'est pas sur USB.

    « /sys/devices/pci0000:00/0000:00:14.0/usb3/3-3/3-3:1.0 » -> « /devices/pci0000:00/0000:00:14.0/usb3/3-3 »
    """
    if not chemin_sysfs:
        return None
    if chemin_sysfs.startswith("/sys/"):
        chemin_sysfs = chemin_sysfs[len("/sys"):]
    parties = chemin_sysfs.split("/")
    for i, partie in enumerate(parties):
        if _INTERFACE_USB.match(partie):
            return "/".join(parties[:i])
    return None


def _sysfs_video(chemin):
    """Chemin sysfs réel de /dev/videoN (« /sys/devices/…/3-3:1.0 »), ou None."""
    lien = f"/sys/class/video4linux/{os.path.basename(chemin)}/device"
    return os.path.realpath(lien) if os.path.exists(lien) else None


def _lire(chemin):
    try:
        with open(chemin, encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except OSError:
        return ""


def nom_carte(usb, nom_gst):
    """Nom lisible : fabricant et produit USB, le nom GStreamer à défaut de produit (« MACROSILICON 2109 »)."""
    nom_gst = re.sub(r"\s*\((V4L2|PipeWire)\)$", "", nom_gst or "").strip()
    fabricant = _lire(f"/sys{usb}/manufacturer") if usb else ""
    produit = (_lire(f"/sys{usb}/product") if usb else "") or nom_gst
    if fabricant and produit.lower().startswith(fabricant.lower()):
        fabricant = ""
    return " ".join(p for p in (fabricant, produit) if p) or "Carte de capture"


def _proprietes(device):
    props = device.get_properties()
    if props is None:
        return {}
    resultat = {}
    for i in range(props.n_fields()):
        nom = props.nth_field_name(i)
        try:
            resultat[nom] = props.get_value(nom)
        except TypeError:            # valeur que PyGObject ne sait pas convertir : sans intérêt ici
            pass
    return resultat


def carte_depuis_device(device):
    """Carte décrite par un Gst.Device de classe Video/Source, ou None s'il n'a pas de chemin /dev/video."""
    props = _proprietes(device)
    chemin = props.get("api.v4l2.path") or props.get("device.path")
    if not chemin or not str(chemin).startswith("/dev/video"):
        return None
    usb = appareil_usb(_sysfs_video(chemin))
    caps = device.get_caps()
    modes = tuple(parser_caps(caps.to_string())) if caps else ()
    if not modes:
        return None
    return Carte(nom_carte(usb, device.get_display_name()), chemin, usb, modes)


def lister_cartes(moniteur):
    """Cartes vues par un Gst.DeviceMonitor démarré (filtre « Video/Source »), une par /dev/video."""
    cartes = {}
    for device in moniteur.get_devices():
        carte = carte_depuis_device(device)
        if carte and carte.chemin not in cartes:
            cartes[carte.chemin] = carte
    return sorted(cartes.values(), key=lambda c: c.chemin)


def _est_bluetooth(entree):
    props = entree.get("properties", {})
    return (entree.get("name", "").startswith("bluez_") or props.get("device.bus") == "bluetooth"
            or props.get("device.api") == "bluez5")


def parser_pactl(texte, sorties):
    """Sources (sorties=False, sans les « monitor ») ou sorties audio lues dans ``pactl -f json list …``."""
    resultat = []
    for entree in json.loads(texte or "[]"):
        nom = entree.get("name", "")
        props = entree.get("properties", {})
        if not sorties and (nom.endswith(".monitor") or props.get("device.class") == "monitor"):
            continue
        description = entree.get("description") or props.get("device.description") or nom
        resultat.append(Audio(nom, description, appareil_usb(props.get("sysfs.path")), _est_bluetooth(entree)))
    return resultat


def _pactl(*args):
    try:
        sortie = subprocess.run(["pactl", *args], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return sortie.stdout if sortie.returncode == 0 else ""


def lister_sources():
    return parser_pactl(_pactl("-f", "json", "list", "sources"), sorties=False)


def lister_sorties():
    return parser_pactl(_pactl("-f", "json", "list", "sinks"), sorties=True)


def sortie_par_defaut():
    return _pactl("get-default-sink").strip() or None


def associer_son(carte, sources):
    """Source audio branchée sur le même appareil USB que la carte, ou None."""
    if carte is None or not carte.usb:
        return None
    return next((s for s in sources if s.usb == carte.usb), None)
