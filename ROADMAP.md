# Feuille de route de Lucarne

Lucarne affiche l'image d'une carte de capture HDMI-USB (MS2109 et semblables) avec le moins de retard possible, et
envoie son son vers la sortie audio choisie (casque Bluetooth, haut-parleurs, dock…).

## Phase 1 — 0.1.0 : regarder et entendre en un clic

- [x] Dépôt, git flow, licence, README, CHANGELOG
- [x] Modes de la carte : lecture des formats annoncés (MJPEG, YUYV, résolutions, images par seconde)
- [x] Appareils : cartes de capture (GStreamer), sources et sorties audio (`pactl`), association image/son par le port USB
- [x] Lecture : image par mpv réglé pour la latence minimale, son par `pw-loopback` vers la sortie choisie
- [x] Test de la carte : débit réel, attente et décodage mesurés pour chaque mode, choix automatique du plus rapide
- [x] Réglages gardés entre deux lancements (carte, mode, sortie, tampon du son, plein écran)
- [x] Fenêtre GTK 4 / libadwaita : carte, mode, son, sortie, bouton Regarder/Arrêter, alerte Bluetooth
- [x] Branchement et débranchement suivis en direct (cartes et sorties audio)
- [x] Paquet `.deb` (lanceur, icône, metainfo), lintian propre, installé sur le poste
- [ ] Release 0.1.0 : tag, release GitHub, dépôt APT apt.mawena.cloud

## Plus tard

- [ ] Enregistrer ce qui passe à l'écran (fichier vidéo + son)
- [ ] Capture d'image (touche) vers ~/Images
- [ ] Mesure du retard réel de bout en bout (avec la caméra du PC ou une mire)
