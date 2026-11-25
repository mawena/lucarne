import os
import tempfile
import unittest
from datetime import datetime

from lucarne.enregistrement import (Brut, commande_lancement, commandes_compression, dans_la_file, en_attente,
                                    filtre_son, nom_libre, texte_duree, texte_taille, trouver_rendu)

INSTANT = datetime(2026, 11, 25, 8, 19, 0)
NOM = "Lucarne 2026-11-25 08-19-00"


def toucher(chemin, contenu=""):
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    with open(chemin, "w") as f:
        f.write(contenu)


class NomLibre(unittest.TestCase):
    def test_nom_de_base(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(nom_libre(d, INSTANT, [".mp4"]), NOM)

    def test_suffixe_si_le_fichier_existe(self):
        with tempfile.TemporaryDirectory() as d:
            toucher(os.path.join(d, NOM + ".mp4"))
            self.assertEqual(nom_libre(d, INSTANT, [".mp4"]), NOM + " (2)")
            toucher(os.path.join(d, NOM + " (2).mp4"))
            self.assertEqual(nom_libre(d, INSTANT, [".mp4"]), NOM + " (3)")

    def test_autres_dossiers(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as brut:
            toucher(os.path.join(brut, NOM + ".mkv"))
            self.assertEqual(nom_libre(d, INSTANT, [".mp4"], [(brut, ".mkv")]), NOM + " (2)")


class Textes(unittest.TestCase):
    def test_taille(self):
        self.assertEqual(texte_taille(512 * 1024 ** 2), "512 Mo")
        self.assertEqual(texte_taille(int(1.5 * 1024 ** 3)), "1,5 Go")

    def test_duree(self):
        self.assertEqual(texte_duree(65), "01:05")
        self.assertEqual(texte_duree(3725.9), "1:02:05")
        self.assertEqual(texte_duree(0), "00:00")


class BrutDisque(unittest.TestCase):
    def test_sortie_et_description(self):
        b = Brut(NOM, "/v/Lucarne", "/v/Lucarne/brut/x.mkv")
        self.assertEqual(b.sortie, f"/v/Lucarne/{NOM}.mp4")
        self.assertEqual(b.description, f"/v/Lucarne/brut/{NOM}.json")

    def test_aller_retour(self):
        with tempfile.TemporaryDirectory() as d:
            b = Brut(NOM, d, os.path.join(d, "brut", NOM + ".mkv"), os.path.join(d, "brut", NOM + ".flac"), 0.12)
            b.enregistrer()
            self.assertEqual(Brut.charger(b.description), b)
            self.assertFalse(os.path.exists(b.description + ".tmp"))

    def test_charger_illisible(self):
        with tempfile.TemporaryDirectory() as d:
            chemin = os.path.join(d, "x.json")
            toucher(chemin, "{pas du json")
            self.assertIsNone(Brut.charger(chemin))
            self.assertIsNone(Brut.charger(os.path.join(d, "absent.json")))

    def test_charger_ignore_les_champs_inconnus(self):
        with tempfile.TemporaryDirectory() as d:
            chemin = os.path.join(d, "x.json")
            toucher(chemin, '{"nom": "a", "dossier": "b", "video": "c", "futur": 1}')
            self.assertEqual(Brut.charger(chemin), Brut("a", "b", "c"))


class EnAttente(unittest.TestCase):
    def test_ignore_erreur_et_sans_video(self):
        with tempfile.TemporaryDirectory() as d:
            def brut(nom, avec_video=True, erreur=""):
                video = os.path.join(d, "brut", nom + ".mkv")
                if avec_video:
                    toucher(video, "x")
                b = Brut(nom, d, video, erreur=erreur)
                b.enregistrer()
            brut("a")
            brut("b", erreur="ffmpeg a échoué")
            brut("c", avec_video=False)
            brut("d")
            toucher(os.path.join(d, "brut", "e.json"), "illisible")
            self.assertEqual([b.nom for b in en_attente(d)], ["a", "d"])

    def test_sans_dossier(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(en_attente(d), [])


class TrouverRendu(unittest.TestCase):
    def faux_drm(self, d, pilote):
        cible = os.path.join(d, "pilotes", pilote)
        os.makedirs(cible)
        device = os.path.join(d, "drm", "renderD128", "device")
        os.makedirs(device)
        os.symlink(cible, os.path.join(device, "driver"))
        return os.path.join(d, "drm")

    def test_pilote_vaapi(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(trouver_rendu(self.faux_drm(d, "i915")), "/dev/dri/renderD128")

    def test_autre_pilote(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(trouver_rendu(self.faux_drm(d, "nouveau")))

    def test_aucun_rendu(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(trouver_rendu(d))


class FiltreSon(unittest.TestCase):
    def test_positif_coupe_le_debut(self):
        self.assertEqual(filtre_son(0.25), "atrim=start=0.250,asetpts=PTS-STARTPTS")

    def test_negatif_retarde(self):
        self.assertEqual(filtre_son(-0.1204), "adelay=120:all=1")

    def test_nul(self):
        self.assertIsNone(filtre_son(0))
        self.assertIsNone(filtre_son(0.0001))
        self.assertIsNone(filtre_son(-0.0001))


def brut_exemple(son=True, decalage=0.2):
    return Brut(NOM, "/v/Lucarne", "/v/Lucarne/brut/a.mkv", "/v/Lucarne/brut/a.flac" if son else "", decalage)


class CommandesCompression(unittest.TestCase):
    def test_avec_rendu(self):
        b = brut_exemple()
        vaapi, x264 = commandes_compression(b, "/dev/dri/renderD128")
        self.assertIn("h264_vaapi", vaapi)
        self.assertEqual(vaapi[vaapi.index("-vaapi_device") + 1], "/dev/dri/renderD128")
        self.assertIn("libx264", x264)
        self.assertNotIn("-vaapi_device", x264)
        for argv in (vaapi, x264):
            self.assertEqual(argv[-1], b.sortie + ".part")
            self.assertIn("-shortest", argv)

    def test_sans_rendu(self):
        commandes = commandes_compression(brut_exemple())
        self.assertEqual(len(commandes), 1)
        self.assertIn("libx264", commandes[0])

    def test_sans_son(self):
        for argv in commandes_compression(brut_exemple(son=False), "/dev/dri/renderD128"):
            self.assertNotIn("1:a:0", argv)
            self.assertNotIn("-shortest", argv)
            self.assertNotIn("-af", argv)

    def test_filtre_son_applique(self):
        argv = commandes_compression(brut_exemple(decalage=0.2))[0]
        self.assertEqual(argv[argv.index("-af") + 1], "atrim=start=0.200,asetpts=PTS-STARTPTS")
        self.assertNotIn("-af", commandes_compression(brut_exemple(decalage=0))[0])


class DansLaFile(unittest.TestCase):
    def test_avec_gagarine(self):
        argv = dans_la_file(["ffmpeg", "-i", "x"], "nom", gagarine="/usr/bin/gagarine")
        self.assertEqual(argv[:2], ["/usr/bin/gagarine", "file"])
        self.assertEqual(argv[argv.index("--priorite") + 1], "fond")
        i = argv.index("--")
        self.assertEqual(argv[i + 1:], ["ffmpeg", "-i", "x"])

    def test_sans_gagarine(self):
        self.assertEqual(dans_la_file(["ffmpeg"], "nom", gagarine=""), ["nice", "-n", "19", "ffmpeg"])


class CommandeLancement(unittest.TestCase):
    def test_unite_et_arguments(self):
        b = brut_exemple()
        argv = commande_lancement(b, ["lucarne"])
        self.assertEqual(argv[0], "systemd-run")
        unite = next(a for a in argv if a.startswith("--unit="))
        self.assertEqual(unite, "--unit=lucarne-compression-2026-11-25-08-19-00")
        self.assertNotIn(" ", unite)
        self.assertEqual(argv[-2:], ["--compresser", b.description])
        self.assertLess(argv.index("lucarne"), argv.index("--compresser"))
