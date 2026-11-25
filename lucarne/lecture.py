"""Lecture en cours : le processus mpv (image) et le processus pw-loopback (son), suivis par GLib.

Fermer la fenêtre de mpv (ou « q ») termine la lecture : le son est alors coupé aussi. Si pw-loopback s'arrête seul
(sortie Bluetooth déconnectée, par exemple), l'image continue et l'interface est prévenue.
"""
import signal

from gi.repository import Gio, GLib

from .commandes import commande_mpv, commande_son

DELAI_ARRET_S = 2       # après SIGTERM, temps laissé au processus avant SIGKILL


def _lancer(argv):
    drapeaux = Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_PIPE
    return Gio.Subprocess.new(argv, drapeaux)


def _arreter(processus):
    """SIGTERM, puis SIGKILL après DELAI_ARRET_S. Sans risque sur un processus déjà terminé : GIO ne signale alors
    plus rien (on ne peut pas lui demander s'il tourne encore : get_if_exited n'est valable qu'après sa fin)."""
    if processus is None:
        return
    processus.send_signal(signal.SIGTERM)

    def forcer():
        processus.force_exit()
        return GLib.SOURCE_REMOVE
    GLib.timeout_add_seconds(DELAI_ARRET_S, forcer)


def _derniere_ligne(texte):
    lignes = [l.strip() for l in (texte or "").splitlines() if l.strip()]
    return lignes[-1] if lignes else ""


class Lecture:
    """Une lecture : démarrer(), changer_son(), arreter(). Rappels appelés dans le fil principal GLib :

    sur_fin(erreur)      : mpv s'est terminé (erreur vide si l'utilisateur l'a fermé normalement) ;
    sur_son_perdu(texte) : pw-loopback s'est arrêté tout seul.
    """

    def __init__(self, sur_fin, sur_son_perdu):
        self._sur_fin = sur_fin
        self._sur_son_perdu = sur_son_perdu
        self._mpv = None
        self._son = None
        self._arret_demande = False

    @property
    def en_cours(self):
        return self._mpv is not None

    def demarrer(self, carte, mode, source=None, sortie=None, tampon_ms=None, plein_ecran=False):
        """Lance l'image et, s'il y a une source audio, le son. Lève GLib.Error si mpv ne peut pas démarrer."""
        self._arret_demande = False
        self._mpv = _lancer(commande_mpv(carte, mode, plein_ecran))
        self._mpv.communicate_utf8_async(None, None, self._mpv_termine, self._mpv)
        self.changer_son(source, sortie, tampon_ms)

    def changer_son(self, source, sortie=None, tampon_ms=None):
        """(Re)lance le renvoi du son vers une autre sortie ; source None coupe le son."""
        ancien, self._son = self._son, None
        _arreter(ancien)
        if source is None or self._mpv is None:
            return
        argv = commande_son(source, sortie, *(() if tampon_ms is None else (tampon_ms,)))
        try:
            self._son = _lancer(argv)
        except GLib.Error as e:
            self._sur_son_perdu(e.message)
            return
        self._son.communicate_utf8_async(None, None, self._son_termine, self._son)

    def arreter(self):
        self._arret_demande = True
        mpv, son = self._mpv, self._son
        self._mpv = self._son = None
        _arreter(son)
        _arreter(mpv)

    def _mpv_termine(self, processus, resultat, attendu):
        try:
            _ok, _sortie, erreurs = processus.communicate_utf8_finish(resultat)
        except GLib.Error as e:
            erreurs = e.message
        if attendu is not self._mpv and self._mpv is not None:
            return                                  # ancienne lecture, déjà remplacée
        demande = self._arret_demande
        son, self._son, self._mpv = self._son, None, None
        _arreter(son)
        code = processus.get_exit_status() if processus.get_if_exited() else 0
        # mpv sort avec 0 quand on le ferme (q, croix) ; 4 quand il est interrompu par un signal (notre arrêt)
        erreur = "" if demande or code in (0, 4) else (_derniere_ligne(erreurs) or f"mpv s'est arrêté (code {code})")
        self._sur_fin(erreur)

    def _son_termine(self, processus, resultat, attendu):
        try:
            _ok, _sortie, erreurs = processus.communicate_utf8_finish(resultat)
        except GLib.Error as e:
            erreurs = e.message
        if attendu is not self._son:
            return                                  # arrêt voulu (changement de sortie, fin de lecture)
        self._son = None
        self._sur_son_perdu(_derniere_ligne(erreurs) or "le renvoi du son s'est arrêté")
