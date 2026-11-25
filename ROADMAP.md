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
- [x] Release 0.1.0 : tag, release GitHub, dépôt APT apt.mawena.cloud

## Phase 2 — 0.2.0 : capturer, enregistrer, mesurer

- [x] Capture d'image : bouton et touche S, PNG dans ~/Images/Lucarne par la prise de commande de mpv
- [x] Prise de commande de mpv (`--input-ipc-server`) et fichier de touches `input.conf` (S, R)
- [x] Enregistrement brut : flux MJPEG copié par mpv, son de la carte en FLAC par GStreamer, ~/Vidéos/Lucarne/brut
- [x] Garde-fous de place : refus sous 4 Go libres, arrêt automatique sous 2 Go
- [x] Calage du son sur l'image (décalage mesuré au démarrage)
- [x] Compression à l'arrêt : `lucarne --compresser` par systemd-run, ffmpeg dans la file Gagarine, H.264 VA-API ou x264 + AAC
- [x] Bruts en attente relancés au démarrage, erreur gardée dans le json, relance manuelle
- [x] Retard réel : calcul (fronts, appariement, médiane + décodage + rafraîchissement d'écran)
- [x] Mire plein écran sans danger pour l'épilepsie, rangée « Retard réel » dans la fenêtre, résultats gardés
- [x] Tests unitaires, README, CHANGELOG, page de manuel, paquet (ffmpeg, gstreamer1.0-pulseaudio)
- [x] Essai réel de la mire : la carte voit la sortie HDMI-1, 19 changements sur 20 retrouvés (carte ≈ 9 ms, total ≈ 27 ms)
- [x] Release 0.2.0 : tag, release GitHub, dépôt APT

## Plus tard

- [ ] Enregistrement compressé en direct, sans passer par le brut
- [ ] Choix des dossiers de capture et d'enregistrement
