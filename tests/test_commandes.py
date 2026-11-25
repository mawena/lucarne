import os
import unittest
from fractions import Fraction

from lucarne.appareils import Carte
from lucarne.commandes import commande_mpv, commande_son
from lucarne.modes import Mode

CARTE = Carte("MACROSILICON 2109", "/dev/video0")


class CommandeMpv(unittest.TestCase):
    def test_options_de_faible_latence(self):
        argv = commande_mpv(CARTE, Mode("mjpeg", 1280, 720, Fraction(60)))
        self.assertEqual(argv[:2], ["mpv", "av://v4l2:/dev/video0"])
        self.assertIn("--demuxer-lavf-o=video_size=1280x720,input_format=mjpeg,framerate=60,fflags=+nobuffer", argv)
        for option in ("--untimed", "--no-audio", "--profile=low-latency", "--swapchain-depth=1", "--hwdec=no"):
            self.assertIn(option, argv)
        self.assertNotIn("--fs", argv)

    def test_options_v4l2_apres_le_profil(self):
        # Le profil low-latency ajoute fflags=+nobuffer : notre liste doit venir après et le reprendre
        argv = commande_mpv(CARTE, Mode("mjpeg", 1280, 720, Fraction(60)))
        profil = argv.index("--profile=low-latency")
        options = next(i for i, a in enumerate(argv) if a.startswith("--demuxer-lavf-o="))
        self.assertLess(profil, options)

    def test_brut_fractionnaire_et_plein_ecran(self):
        argv = commande_mpv(CARTE, Mode("yuyv422", 640, 480, Fraction(30000, 1001)), plein_ecran=True)
        self.assertIn("--demuxer-lavf-o=video_size=640x480,input_format=yuyv422,framerate=30000/1001,"
                      "fflags=+nobuffer", argv)
        self.assertIn("--fs", argv)


class CommandeSon(unittest.TestCase):
    def test_vers_une_sortie(self):
        self.assertEqual(commande_son("src", "bluez_output.X", 40),
                         ["pw-loopback", "-n", "lucarne", "-C", "src", "-l", "40", "-P", "bluez_output.X"])

    def test_sortie_du_systeme_et_bornes(self):
        self.assertNotIn("-P", commande_son("src"))
        self.assertIn("10", commande_son("src", None, 1))
        self.assertIn("300", commande_son("src", None, 5000))


if __name__ == "__main__":
    unittest.main()


class CommandeMpvPrise(unittest.TestCase):
    def test_avec_prise(self):
        argv = commande_mpv(CARTE, Mode("mjpeg", 1280, 720, Fraction(60)), prise="/tmp/x.sock")
        self.assertIn("--input-ipc-server=/tmp/x.sock", argv)
        conf = next(a for a in argv if a.startswith("--input-conf="))
        chemin = conf.split("=", 1)[1]
        self.assertEqual(os.path.basename(chemin), "input.conf")
        self.assertTrue(os.path.isfile(chemin))

    def test_sans_prise(self):
        argv = commande_mpv(CARTE, Mode("mjpeg", 1280, 720, Fraction(60)))
        self.assertFalse(any(a.startswith(("--input-ipc-server", "--input-conf")) for a in argv))
