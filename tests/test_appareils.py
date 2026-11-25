import json
import unittest

from lucarne.appareils import Audio, Carte, appareil_usb, associer_son, parser_pactl

USB = "/devices/pci0000:00/0000:00:14.0/usb3/3-3"


def _entree(nom, description, **props):
    return {"name": nom, "description": description, "properties": props}


class AppareilUsb(unittest.TestCase):
    def test_coupe_a_l_interface(self):
        self.assertEqual(appareil_usb(f"/sys{USB}/3-3:1.0"), USB)
        self.assertEqual(appareil_usb(f"{USB}/3-3:1.2/sound/card1"), USB)

    def test_concentrateur(self):
        self.assertEqual(appareil_usb("/devices/pci0000:00/0000:00:14.0/usb1/1-2/1-2.4/1-2.4:1.0"),
                         "/devices/pci0000:00/0000:00:14.0/usb1/1-2/1-2.4")

    def test_hors_usb(self):
        self.assertIsNone(appareil_usb("/devices/pci0000:00/0000:00:1f.3/sound/card0"))
        self.assertIsNone(appareil_usb(None))


class ParserPactl(unittest.TestCase):
    def test_sources_sans_monitor(self):
        texte = json.dumps([
            _entree("alsa_input.usb-MACROSILICON_2109-02.analog-stereo", "2109",
                    **{"sysfs.path": f"{USB}/3-3:1.2/sound/card1", "device.bus": "usb"}),
            _entree("alsa_output.pci.monitor", "Monitor of Speaker", **{"device.class": "monitor"}),
        ])
        sources = parser_pactl(texte, sorties=False)
        self.assertEqual(sources, [Audio("alsa_input.usb-MACROSILICON_2109-02.analog-stereo", "2109", USB, False)])

    def test_sorties_bluetooth_reperees(self):
        texte = json.dumps([
            _entree("bluez_output.BB_6F_27_89_F4_DB.1", "LN-1008BT", **{"device.api": "bluez5"}),
            _entree("alsa_output.pci-0000_00_1f.3.analog", "Speaker + Headphones"),
        ])
        sorties = parser_pactl(texte, sorties=True)
        self.assertEqual([s.bluetooth for s in sorties], [True, False])
        self.assertEqual(sorties[0].description, "LN-1008BT")

    def test_texte_vide(self):
        self.assertEqual(parser_pactl("", sorties=True), [])


class AssocierSon(unittest.TestCase):
    def test_meme_appareil_usb(self):
        carte = Carte("MACROSILICON 2109", "/dev/video0", USB)
        sources = [Audio("micro", "Micro", None), Audio("carte", "2109", USB), Audio("autre", "Autre", "/x/1-1")]
        self.assertEqual(associer_son(carte, sources).nom, "carte")

    def test_sans_usb_ou_sans_carte(self):
        self.assertIsNone(associer_son(Carte("Webcam", "/dev/video2"), [Audio("a", "A", None)]))
        self.assertIsNone(associer_son(None, []))


if __name__ == "__main__":
    unittest.main()
