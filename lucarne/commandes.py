"""Commandes lancées pour regarder la carte : mpv pour l'image, pw-loopback pour le son.

L'image et le son passent par deux chemins séparés : mpv lit la vidéo seule (sans tampon ni synchronisation, chaque
image est affichée dès qu'elle est décodée) et PipeWire renvoie directement le son de la carte vers la sortie
choisie. Les relier dans mpv fait attendre le son (le flux reste « bouchonné ») et ajoute du retard à l'image.
"""

TAMPON_SON_MS = 30          # tampon par défaut de pw-loopback : assez court pour ne pas s'entendre, sans craquements
TAMPON_SON_MIN, TAMPON_SON_MAX = 10, 300


def texte_ips(ips):
    """Cadence pour FFmpeg : « 60 » ou « 30000/1001 »."""
    return str(ips.numerator) if ips.denominator == 1 else f"{ips.numerator}/{ips.denominator}"


def commande_mpv(carte, mode, plein_ecran=False):
    """mpv réglé pour le moins de retard possible sur une source vidéo en direct."""
    options_v4l2 = ",".join((
        f"video_size={mode.largeur}x{mode.hauteur}",
        f"input_format={mode.format}",
        f"framerate={texte_ips(mode.ips)}",
        "fflags=+nobuffer",                 # pas de tampon à l'ouverture (repris du profil low-latency)
    ))
    commande = [
        "mpv", f"av://v4l2:{carte.chemin}",
        "--profile=low-latency",            # pas de cache, analyse minimale du flux, un seul fil de décodage
        f"--demuxer-lavf-o={options_v4l2}",  # après le profil : cette liste remplace la sienne, fflags compris
        "--untimed",                        # chaque image s'affiche dès qu'elle est décodée, sans attendre son heure
        "--no-audio",                       # le son passe par pw-loopback
        "--cache=no",
        "--hwdec=no",                       # le décodage MJPEG logiciel prend quelques ms et ne met rien en file
        "--swapchain-depth=1",              # une seule image d'avance côté carte graphique (3 par défaut)
        "--osc=no",
        "--cursor-autohide=1000",
        f"--title=Lucarne — {carte.nom}",
        "--force-window=immediate",
        "--msg-level=all=error",
    ]
    if plein_ecran:
        commande.append("--fs")
    return commande


def commande_son(source, sortie=None, tampon_ms=TAMPON_SON_MS):
    """pw-loopback de la source audio de la carte vers la sortie (la sortie par défaut si sortie est None)."""
    tampon_ms = max(TAMPON_SON_MIN, min(TAMPON_SON_MAX, int(tampon_ms)))
    commande = ["pw-loopback", "-n", "lucarne", "-C", source, "-l", str(tampon_ms)]
    if sortie:
        commande += ["-P", sortie]
    return commande
