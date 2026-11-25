import json
import os
import tempfile
import unittest

from lucarne.config import Reglages


class ReglagesFichier(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.TemporaryDirectory()
        self.chemin = os.path.join(self.dossier.name, "lucarne", "reglages.json")

    def tearDown(self):
        self.dossier.cleanup()

    def test_absent_donne_les_valeurs_par_defaut(self):
        r = Reglages.charger(self.chemin)
        self.assertEqual((r.mode, r.sortie, r.tampon_son_ms, r.plein_ecran), ("", "", 30, False))

    def test_aller_retour(self):
        r = Reglages(carte="MACROSILICON 2109", mode="mjpeg-1280x720-60", sortie="bluez_output.X",
                     tampon_son_ms=40, plein_ecran=True, tests={"MACROSILICON 2109": [{"cle": "a"}]})
        r.enregistrer(self.chemin)
        self.assertEqual(Reglages.charger(self.chemin), r)

    def test_fichier_abime_ou_champ_inconnu(self):
        os.makedirs(os.path.dirname(self.chemin))
        with open(self.chemin, "w") as f:
            f.write("{pas du json")
        self.assertEqual(Reglages.charger(self.chemin), Reglages())
        with open(self.chemin, "w") as f:
            json.dump({"mode": "x", "inconnu": 1}, f)
        self.assertEqual(Reglages.charger(self.chemin).mode, "x")


if __name__ == "__main__":
    unittest.main()
