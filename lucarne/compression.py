"""``lucarne --compresser <description.json>`` : compresse un enregistrement brut, puis supprime le brut.

Lancé par systemd-run à la fin d'un enregistrement (voir enregistrement). ffmpeg passe par la file Gagarine en
priorité « fond » : d'abord en H.264 par VA-API (la puce graphique, presque sans processeur), sinon par x264.
Une notification du bureau dit quand la vidéo est prête, ou pourquoi elle ne l'est pas (le brut est alors gardé).
"""
import os
import subprocess

from . import APP_ID
from .enregistrement import Brut, commandes_compression, dans_la_file, trouver_rendu


def _derniere_ligne(texte):
    lignes = [l.strip() for l in (texte or "").splitlines() if l.strip()]
    return lignes[-1] if lignes else ""


def _supprimer(chemin):
    try:
        os.unlink(chemin)
    except OSError:
        pass


def compresser(brut, rendu=None, executer=subprocess.run):
    """Compresse brut vers brut.sortie ; renvoie un texte d'erreur, vide si tout a marché (brut supprimé)."""
    os.makedirs(brut.dossier, exist_ok=True)
    partiel = brut.sortie + ".part"
    erreur = "aucune commande"
    for argv in commandes_compression(brut, rendu):
        r = executer(dans_la_file(argv, brut.nom), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        if r.returncode == 0 and os.path.exists(partiel) and os.path.getsize(partiel) > 0:
            os.replace(partiel, brut.sortie)
            for chemin in (brut.video, brut.son, brut.description):
                if chemin:
                    _supprimer(chemin)
            return ""
        erreur = _derniere_ligne(r.stderr) or f"ffmpeg a échoué (code {r.returncode})"
        _supprimer(partiel)
    return erreur


def notifier(titre, texte):
    """Notification du bureau par D-Bus ; sans bureau (session sans affichage), rien."""
    try:
        from gi.repository import Gio, GLib
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        bus.call_sync("org.freedesktop.Notifications", "/org/freedesktop/Notifications",
                      "org.freedesktop.Notifications", "Notify",
                      GLib.Variant("(susssasa{sv}i)", ("Lucarne", 0, APP_ID, titre, texte, [], {}, -1)),
                      None, Gio.DBusCallFlags.NONE, 5000, None)
    except Exception:           # pas de bus de session, pas de service de notification : on n'insiste pas
        pass


def main(arguments):
    if len(arguments) != 1:
        print("usage : lucarne --compresser <description.json>")
        return 2
    brut = Brut.charger(arguments[0])
    if brut is None:
        print(f"lucarne : description illisible : {arguments[0]}")
        return 1
    erreur = compresser(brut, trouver_rendu())
    if erreur:
        brut.erreur = erreur
        try:
            brut.enregistrer()
        except OSError:
            pass
        print(f"lucarne : compression ratée pour {brut.nom} : {erreur}")
        notifier("Compression ratée", f"{brut.nom} : {erreur}. Le brut est gardé dans {os.path.dirname(brut.video)}.")
        return 1
    print(f"lucarne : vidéo prête : {brut.sortie}")
    notifier("Vidéo prête", brut.sortie)
    return 0
