import unittest
from fractions import Fraction

from lucarne.mesure import Resultat, choisir, modes_a_tester
from lucarne.modes import Mode

M1080 = Mode("mjpeg", 1920, 1080, Fraction(60))
M720 = Mode("mjpeg", 1280, 720, Fraction(60))
M480 = Mode("yuyv422", 640, 480, Fraction(60))
LENT = Mode("yuyv422", 1920, 1080, Fraction(5))


def res(mode, ips, attente=2.0, decodage=0.0, erreur=""):
    return Resultat(mode.cle, ips, attente, decodage, 100_000, erreur)


class Latence(unittest.TestCase):
    def test_intervalle_plus_attente_plus_decodage(self):
        self.assertAlmostEqual(res(M720, 60, 2.0, 3.0).latence_ms, 1000 / 60 + 5.0)

    def test_mode_sans_image(self):
        self.assertEqual(res(M720, 0).latence_ms, float("inf"))
        self.assertFalse(res(M720, 60, erreur="busy").valide)

    def test_aller_retour_dict(self):
        r = res(M720, 59.9, 1.5, 2.5)
        self.assertEqual(Resultat.depuis_dict(r.vers_dict()), r)


class Choisir(unittest.TestCase):
    def test_le_plus_rapide(self):
        # La carte annonce 60 i/s en 1080p mais n'en livre que 30 : le 720p à 60 i/s gagne
        resultats = [res(M1080, 30, 2, 4), res(M720, 60, 2, 2)]
        self.assertEqual(choisir([M1080, M720], resultats), M720)

    def test_a_egalite_la_plus_grande_resolution(self):
        resultats = [res(M1080, 60, 2, 2.6), res(M720, 60, 2, 2.0)]
        self.assertEqual(choisir([M1080, M720], resultats), M1080)

    def test_ecart_au_dela_de_la_tolerance(self):
        resultats = [res(M1080, 60, 2, 5.0), res(M720, 60, 2, 2.0), res(M480, 60, 2, 0.0)]
        self.assertEqual(choisir([M1080, M720, M480], resultats), M480)

    def test_aucun_resultat_valide(self):
        self.assertIsNone(choisir([M720], [res(M720, 0)]))
        self.assertIsNone(choisir([M720], []))


class ModesATester(unittest.TestCase):
    def test_seulement_les_plus_hautes_cadences(self):
        self.assertEqual(modes_a_tester([M1080, M720, LENT, M480]), [M1080, M720, M480])
        self.assertEqual(modes_a_tester([]), [])


if __name__ == "__main__":
    unittest.main()
