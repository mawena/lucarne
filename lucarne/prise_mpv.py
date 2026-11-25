"""Prise de commande de mpv (option --input-ipc-server) : envoyer des commandes et recevoir ses messages.

mpv écoute sur une prise Unix et échange des lignes JSON. Lucarne s'en sert pour la capture d'image
(``screenshot-to-file``), l'enregistrement (propriété ``stream-record``), les textes affichés dans l'image
(``show-text``) et pour savoir quand une touche de Lucarne est pressée dans la fenêtre de mpv : ces touches envoient
``script-message lucarne <action>``, qui arrive ici comme événement ``client-message``.

Tout se passe dans la boucle GLib : la prise est lue par GLib.io_add_watch, jamais par un fil à part.
"""
import json
import socket

from gi.repository import GLib

ESSAIS_CONNEXION = 50       # mpv crée la prise une fraction de seconde après son lancement
INTERVALLE_ESSAI_MS = 100


def message_commande(arguments, numero, asynchrone=False):
    """Ligne JSON d'une commande mpv, terminée par un saut de ligne."""
    message = {"command": list(arguments), "request_id": numero}
    if asynchrone:
        message["async"] = True
    return (json.dumps(message, ensure_ascii=False) + "\n").encode()


def lire_message(ligne):
    """Analyse une ligne reçue de mpv.

    Renvoie ("reponse", numero, erreur, donnee) pour la réponse à une commande (erreur vide si elle a réussi),
    ("message", [arguments]) pour un script-message, ou None pour le reste (autres événements, ligne illisible).
    """
    try:
        donnees = json.loads(ligne)
    except ValueError:
        return None
    if not isinstance(donnees, dict):
        return None
    if "request_id" in donnees and "error" in donnees:
        erreur = "" if donnees["error"] == "success" else str(donnees["error"])
        return ("reponse", donnees["request_id"], erreur, donnees.get("data"))
    if donnees.get("event") == "client-message":
        return ("message", [str(a) for a in donnees.get("args") or []])
    return None


class PriseMpv:
    """Connexion à la prise de commande d'un mpv qui vient d'être lancé.

    sur_message(arguments) est appelé pour chaque ``script-message`` envoyé par une touche de mpv. Les commandes
    envoyées avant la connexion attendent qu'elle soit faite.
    """

    def __init__(self, chemin, sur_message):
        self.chemin = chemin
        self._sur_message = sur_message
        self._prise = None
        self._veille = None
        self._tampon = b""
        self._en_attente = []           # commandes envoyées avant la connexion
        self._rappels = {}              # numéro de commande -> rappel(erreur, donnee)
        self._numero = 0
        self._essais = 0
        self._fermee = False
        GLib.timeout_add(INTERVALLE_ESSAI_MS, self._connecter)

    @property
    def connectee(self):
        return self._prise is not None

    def commande(self, *arguments, rappel=None, asynchrone=False):
        """Envoie une commande ; rappel(erreur, donnee) reçoit la réponse (erreur vide si elle a réussi)."""
        if self._fermee:
            if rappel:
                rappel("mpv est fermé", None)
            return
        if self._prise is None:
            self._en_attente.append((arguments, rappel, asynchrone))
            return
        self._envoyer(arguments, rappel, asynchrone)

    def fermer(self, raison="mpv est fermé"):
        if self._fermee:
            return
        self._fermee = True
        if self._veille is not None:
            GLib.source_remove(self._veille)
            self._veille = None
        if self._prise is not None:
            self._prise.close()
            self._prise = None
        rappels = list(self._rappels.values()) + [r for _a, r, _s in self._en_attente if r]
        self._rappels.clear()
        self._en_attente.clear()
        for rappel in rappels:
            rappel(raison, None)

    def _connecter(self):
        if self._fermee:
            return GLib.SOURCE_REMOVE
        prise = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            prise.connect(self.chemin)
        except OSError:
            prise.close()
            self._essais += 1
            if self._essais >= ESSAIS_CONNEXION:
                self.fermer("la prise de commande de mpv ne répond pas")
                return GLib.SOURCE_REMOVE
            return GLib.SOURCE_CONTINUE
        prise.setblocking(False)
        self._prise = prise
        self._veille = GLib.io_add_watch(prise.fileno(), GLib.PRIORITY_DEFAULT,
                                         GLib.IOCondition.IN | GLib.IOCondition.HUP | GLib.IOCondition.ERR,
                                         self._lire)
        en_attente, self._en_attente = self._en_attente, []
        for arguments, rappel, asynchrone in en_attente:
            self._envoyer(arguments, rappel, asynchrone)
        return GLib.SOURCE_REMOVE

    def _envoyer(self, arguments, rappel, asynchrone):
        self._numero += 1
        if rappel:
            self._rappels[self._numero] = rappel
        try:
            self._prise.sendall(message_commande(arguments, self._numero, asynchrone))
        except OSError as e:
            self._rappels.pop(self._numero, None)
            if rappel:
                rappel(e.strerror or str(e), None)

    def _lire(self, _fd, _condition):
        try:
            morceau = self._prise.recv(65536)
        except BlockingIOError:
            return GLib.SOURCE_CONTINUE
        except OSError:
            morceau = b""
        if not morceau:
            self._veille = None             # la source s'arrête d'elle-même avec SOURCE_REMOVE
            self.fermer()
            return GLib.SOURCE_REMOVE
        self._tampon += morceau
        *lignes, self._tampon = self._tampon.split(b"\n")
        for ligne in lignes:
            message = lire_message(ligne)
            if message is None:
                continue
            if message[0] == "reponse":
                rappel = self._rappels.pop(message[1], None)
                if rappel:
                    rappel(message[2], message[3])
            elif message[1]:
                self._sur_message(message[1])
        return GLib.SOURCE_CONTINUE
