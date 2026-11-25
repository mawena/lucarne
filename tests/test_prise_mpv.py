import json
import unittest

from lucarne.prise_mpv import lire_message, message_commande


class MessageCommande(unittest.TestCase):
    def test_ligne_json(self):
        octets = message_commande(["set_property", "pause", True], 7)
        self.assertTrue(octets.endswith(b"\n"))
        self.assertEqual(json.loads(octets), {"command": ["set_property", "pause", True], "request_id": 7})

    def test_asynchrone(self):
        self.assertTrue(json.loads(message_commande(["quit"], 1, asynchrone=True))["async"])
        self.assertNotIn("async", json.loads(message_commande(["quit"], 1)))

    def test_accents_gardes(self):
        self.assertIn("é".encode(), message_commande(["show-text", "é"], 1))


class LireMessage(unittest.TestCase):
    def test_reponse_reussie(self):
        ligne = '{"request_id": 3, "error": "success", "data": 42}'
        self.assertEqual(lire_message(ligne), ("reponse", 3, "", 42))

    def test_reponse_en_erreur(self):
        ligne = '{"request_id": 4, "error": "property unavailable"}'
        self.assertEqual(lire_message(ligne), ("reponse", 4, "property unavailable", None))

    def test_message_de_script(self):
        ligne = '{"event": "client-message", "args": ["lucarne", "capture"]}'
        self.assertEqual(lire_message(ligne), ("message", ["lucarne", "capture"]))

    def test_message_sans_arguments(self):
        self.assertEqual(lire_message('{"event": "client-message"}'), ("message", []))

    def test_ligne_illisible(self):
        self.assertIsNone(lire_message("pas du json"))
        self.assertIsNone(lire_message("[1, 2]"))

    def test_autre_evenement(self):
        self.assertIsNone(lire_message('{"event": "property-change", "name": "pause"}'))
