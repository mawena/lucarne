import os
import tempfile
import unittest
from types import SimpleNamespace

from lucarne.compression import compresser
from lucarne.enregistrement import Brut

RENDU = "/dev/dri/renderD128"


def preparer(d):
    brut = Brut("Lucarne test", d, os.path.join(d, "brut", "a.mkv"), os.path.join(d, "brut", "a.flac"))
    os.makedirs(os.path.join(d, "brut"))
    for chemin in (brut.video, brut.son):
        with open(chemin, "w") as f:
            f.write("x")
    brut.enregistrer()
    return brut


class Compresser(unittest.TestCase):
    def test_succes(self):
        with tempfile.TemporaryDirectory() as d:
            brut = preparer(d)
            appels = []

            def executer(argv, **_):
                appels.append(argv)
                with open(argv[-1], "wb") as f:     # la dernière valeur est « <sortie>.part »
                    f.write(b"video")
                return SimpleNamespace(returncode=0, stderr="")
            self.assertEqual(compresser(brut, RENDU, executer), "")
            self.assertEqual(len(appels), 1)         # la première commande (VA-API) a suffi
            self.assertTrue(os.path.exists(brut.sortie))
            self.assertFalse(os.path.exists(brut.sortie + ".part"))
            for chemin in (brut.video, brut.son, brut.description):
                self.assertFalse(os.path.exists(chemin))

    def test_repli_sur_x264(self):
        with tempfile.TemporaryDirectory() as d:
            brut = preparer(d)

            def executer(argv, **_):
                if "h264_vaapi" in argv:
                    return SimpleNamespace(returncode=1, stderr="pas de VA-API\n")
                with open(argv[-1], "wb") as f:
                    f.write(b"video")
                return SimpleNamespace(returncode=0, stderr="")
            self.assertEqual(compresser(brut, RENDU, executer), "")
            self.assertTrue(os.path.exists(brut.sortie))

    def test_echec_partout(self):
        with tempfile.TemporaryDirectory() as d:
            brut = preparer(d)
            appels = []

            def executer(argv, **_):
                appels.append(argv)
                with open(argv[-1], "wb") as f:     # un .part laissé par ffmpeg doit être nettoyé
                    f.write(b"debris")
                return SimpleNamespace(returncode=1, stderr="avertissement\nerreur x\n")
            self.assertEqual(compresser(brut, RENDU, executer), "erreur x")
            self.assertEqual(len(appels), 2)
            for chemin in (brut.video, brut.son, brut.description):
                self.assertTrue(os.path.exists(chemin))
            self.assertFalse(os.path.exists(brut.sortie))
            self.assertFalse(os.path.exists(brut.sortie + ".part"))

    def test_echec_sans_message(self):
        with tempfile.TemporaryDirectory() as d:
            brut = preparer(d)
            executer = lambda argv, **_: SimpleNamespace(returncode=3, stderr="")
            self.assertEqual(compresser(brut, None, executer), "ffmpeg a échoué (code 3)")

    def test_code_zero_sans_fichier(self):
        with tempfile.TemporaryDirectory() as d:
            brut = preparer(d)
            executer = lambda argv, **_: SimpleNamespace(returncode=0, stderr="")
            self.assertNotEqual(compresser(brut, None, executer), "")
            self.assertTrue(os.path.exists(brut.video))
