import unittest

from lucarne.retard import Front, ResultatRetard, apparier, fronts, luminance_centre, resumer


class Fronts(unittest.TestCase):
    def test_noir_blanc(self):
        serie = [(0.0, 10), (0.1, 10), (0.2, 240), (0.3, 240), (0.4, 10)]
        self.assertEqual(fronts(serie), [Front(0.2, True), Front(0.4, False)])

    def test_contraste_insuffisant(self):
        self.assertEqual(fronts([(0.0, 100), (0.1, 120), (0.2, 100), (0.3, 130)]), [])

    def test_trop_court(self):
        self.assertEqual(fronts([]), [])
        self.assertEqual(fronts([(0.0, 10)]), [])


class Apparier(unittest.TestCase):
    def test_retards_attendus(self):
        bascules = [Front(1.0, True), Front(1.4, False)]
        vus = [Front(1.08, True), Front(1.51, False)]
        retards = apparier(bascules, vus)
        self.assertEqual(len(retards), 2)
        self.assertAlmostEqual(retards[0], 0.08)
        self.assertAlmostEqual(retards[1], 0.11)

    def test_front_de_mauvais_sens_ignore(self):
        self.assertEqual(apparier([Front(1.0, True)], [Front(1.05, False)]), [])

    def test_front_trop_tardif_ignore(self):
        self.assertEqual(apparier([Front(1.0, True)], [Front(1.5, True)]), [])

    def test_front_avant_la_bascule_ignore(self):
        retards = apparier([Front(1.0, True)], [Front(0.9, True), Front(1.1, True)])
        self.assertAlmostEqual(retards[0], 0.1)


class Resumer(unittest.TestCase):
    def test_trop_peu(self):
        self.assertIsNone(resumer([0.1] * 4, [2.0], 16.7, "m", True))

    def test_statistiques(self):
        r = resumer([0.08, 0.10, 0.09, 0.12, 0.07], [2.0, 4.0, 3.0], 16.7, "mjpeg-720", True)
        self.assertEqual((r.carte_ms, r.min_ms, r.max_ms), (90.0, 70.0, 120.0))
        self.assertEqual((r.decodage_ms, r.affichage_ms, r.mesures), (3.0, 16.7, 5))
        self.assertAlmostEqual(r.total_ms, 90.0 + 3.0 + 16.7)

    def test_sans_decodage(self):
        self.assertEqual(resumer([0.1] * 5, [], 16.7, "m", False).decodage_ms, 0.0)


class Dictionnaire(unittest.TestCase):
    def test_aller_retour(self):
        r = ResultatRetard("m", 90.0, 70.0, 120.0, 3.0, 16.7, 5, True)
        self.assertEqual(ResultatRetard.depuis_dict(r.vers_dict()), r)

    def test_incomplet(self):
        d = ResultatRetard("m", 90.0, 70.0, 120.0, 3.0, 16.7, 5, True).vers_dict()
        del d["mesures"]
        self.assertIsNone(ResultatRetard.depuis_dict(d))


class LuminanceCentre(unittest.TestCase):
    def test_carre_central(self):
        l, h = 64, 36
        octets = bytearray(l * h)
        for y in range(10, 26):
            for x in range(24, 40):
                octets[y * l + x] = 255
        self.assertEqual(luminance_centre(bytes(octets), l, h), 255)
        self.assertEqual(luminance_centre(bytes(l * h), l, h), 0)

    def test_pas_de_ligne(self):
        # lignes de 70 octets pour une image de 64 : le remplissage ne doit pas décaler le centre
        l, h, pas = 64, 36, 70
        octets = bytearray(pas * h)
        for y in range(h):
            for x in range(l):
                octets[y * pas + x] = 255 if 24 <= x < 40 and 10 <= y < 26 else 0
        self.assertEqual(luminance_centre(bytes(octets), l, h, pas), 255)
