import os
import tempfile
import unittest

from gi.repository import GLib

from lucarne.config import Reglages
from lucarne.enregistrement import Brut, Relais, commande_direct, commandes_compression, dossier_videos, dossier_images


class CommandeDirect(unittest.TestCase):
    def test_vaapi(self):
        argv = commande_direct("/v/x.mkv", "/dev/dri/renderD128")
        self.assertEqual(argv[argv.index("-i") + 1], "pipe:0")
        self.assertIn("h264_vaapi", argv)
        self.assertLess(argv.index("-vaapi_device"), argv.index("-i"))
        self.assertEqual(argv[-3:], ["-f", "matroska", "/v/x.mkv"])
        self.assertNotIn("-nostdin", argv)          # l'image arrive justement par l'entrée standard

    def test_sans_puce_graphique(self):
        argv = commande_direct("/v/x.mkv")
        self.assertIn("libx264", argv)
        self.assertIn("ultrafast", argv)
        self.assertNotIn("-vaapi_device", argv)


class CompressionDejaFaite(unittest.TestCase):
    def test_image_copiee(self):
        brut = Brut("Lucarne x", "/v", "/v/brut/x.mkv", "/v/brut/x.flac", 0.02, video_compressee=True)
        commandes = commandes_compression(brut, "/dev/dri/renderD128")
        self.assertEqual(len(commandes), 1)
        argv = commandes[0]
        self.assertEqual(argv[argv.index("-c:v") + 1], "copy")
        self.assertNotIn("h264_vaapi", argv)
        self.assertIn("-c:a", argv)

    def test_aller_retour(self):
        with tempfile.TemporaryDirectory() as d:
            brut = Brut("Lucarne x", d, os.path.join(d, "brut", "x.mkv"), video_compressee=True)
            brut.enregistrer()
            self.assertTrue(Brut.charger(brut.description).video_compressee)


class Dossiers(unittest.TestCase):
    def test_choisi_ou_par_defaut(self):
        self.assertEqual(dossier_videos("~/films"), os.path.expanduser("~/films"))
        self.assertEqual(dossier_images("/tmp/captures"), "/tmp/captures")
        self.assertEqual(os.path.basename(dossier_videos()), "Lucarne")
        self.assertEqual(os.path.basename(dossier_images("")), "Lucarne")

    def test_reglages(self):
        r = Reglages()
        self.assertEqual((r.enregistrement_direct, r.dossier_images, r.dossier_videos), (False, "", ""))


class RelaisFile(unittest.TestCase):
    def test_tout_passe_a_ffmpeg(self):
        with tempfile.TemporaryDirectory() as d:
            fifo, sortie = os.path.join(d, "f.mkv"), os.path.join(d, "sortie")
            os.mkfifo(fifo)
            boucle = GLib.MainLoop()
            fin, problemes = [], []
            relais = Relais(fifo, ["sh", "-c", f"cat > '{sortie}'"], problemes.append,
                            lambda e: (fin.append(e), boucle.quit()))
            donnees = os.urandom(3 * 1024 * 1024)
            with open(fifo, "wb") as f:                 # comme mpv
                f.write(donnees)
            GLib.timeout_add_seconds(10, boucle.quit)
            boucle.run()
            self.assertEqual(fin, [""])
            self.assertEqual(problemes, [])
            self.assertTrue(relais.fini)
            self.assertFalse(os.path.exists(fifo))      # file nommée supprimée à la fin
            with open(sortie, "rb") as f:
                self.assertEqual(f.read(), donnees)

    def test_ffmpeg_qui_echoue(self):
        with tempfile.TemporaryDirectory() as d:
            fifo = os.path.join(d, "f.mkv")
            os.mkfifo(fifo)
            boucle = GLib.MainLoop()
            fin = []
            Relais(fifo, ["sh", "-c", "echo 'pas de puce' >&2; exit 3"], lambda t: None,
                            lambda e: (fin.append(e), boucle.quit()))
            with open(fifo, "wb"):                     # mpv ouvre la file et la referme sans rien écrire
                pass
            GLib.timeout_add_seconds(10, boucle.quit)
            boucle.run()
            self.assertEqual(fin, ["pas de puce"])


if __name__ == "__main__":
    unittest.main()
