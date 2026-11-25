import unittest
from fractions import Fraction

from lucarne.modes import Mode, mode_depuis_cle, mode_par_defaut, parser_caps

# Extrait réel des caps d'une MS2109 (MACROSILICON 345f:2109) vue par le moniteur GStreamer de PipeWire
CAPS_MS2109 = (
    "image/jpeg, width=(int)1920, height=(int)1080, framerate=(fraction){ 60/1, 50/1, 30/1, 20/1, 10/1 }; "
    "image/jpeg, width=(int)1280, height=(int)720, framerate=(fraction){ 60/1, 50/1, 30/1, 20/1, 10/1 }; "
    "video/x-raw, format=(string)YUY2, width=(int)1920, height=(int)1080, framerate=(fraction){ 5/1 }; "
    "video/x-raw, format=(string)YUY2, width=(int)640, height=(int)480, framerate=(fraction){ 60/1, 30/1 }; "
    "video/x-raw, format=(string)YUY2, width=(int)1280, height=(int)720, framerate=(fraction)10/1"
)


class ParserCaps(unittest.TestCase):
    def test_un_mode_par_format_et_resolution_a_la_cadence_la_plus_haute(self):
        modes = parser_caps(CAPS_MS2109)
        self.assertEqual(len(modes), 5)
        self.assertIn(Mode("mjpeg", 1920, 1080, Fraction(60)), modes)
        self.assertIn(Mode("yuyv422", 1920, 1080, Fraction(5)), modes)
        self.assertIn(Mode("yuyv422", 1280, 720, Fraction(10)), modes)

    def test_ordre_mjpeg_puis_cadence_puis_resolution(self):
        cles = [m.cle for m in parser_caps(CAPS_MS2109)]
        self.assertEqual(cles, ["mjpeg-1920x1080-60", "mjpeg-1280x720-60", "yuyv422-640x480-60",
                                "yuyv422-1280x720-10", "yuyv422-1920x1080-5"])

    def test_intervalle_et_cadence_fractionnaire(self):
        modes = parser_caps("image/jpeg, width=(int)800, height=(int)600, framerate=(fraction)[ 1/1, 30000/1001 ]")
        self.assertEqual(modes[0].ips, Fraction(30000, 1001))
        self.assertEqual(modes[0].cle, "mjpeg-800x600-29_97")
        self.assertIn("29,97 i/s", modes[0].libelle)

    def test_formats_inconnus_et_structures_incompletes_ignores(self):
        texte = ("video/x-h264, width=(int)1920, height=(int)1080, framerate=(fraction)30/1; "
                 "image/jpeg, width=(int)640; video/x-raw, format=(string)RGB, width=(int)2, height=(int)2, "
                 "framerate=(fraction)1/1; image/jpeg, width=(int)640, height=(int)480, framerate=(fraction)0/1")
        self.assertEqual(parser_caps(texte), [])

    def test_mode_depuis_cle_et_par_defaut(self):
        modes = parser_caps(CAPS_MS2109)
        self.assertEqual(mode_depuis_cle("mjpeg-1280x720-60", modes), Mode("mjpeg", 1280, 720, Fraction(60)))
        self.assertIsNone(mode_depuis_cle("absent", modes))
        self.assertEqual(mode_par_defaut(modes).cle, "mjpeg-1920x1080-60")
        self.assertIsNone(mode_par_defaut([]))


if __name__ == "__main__":
    unittest.main()
