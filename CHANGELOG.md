# Journal des modifications

Toutes les modifications notables de Lucarne sont consignées ici.
Format : [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/), versions : [SemVer](https://semver.org/lang/fr/).

## [0.3.0] - 2026-11-25

### Ajouté
- Réglage **Manière d'enregistrer** : « Brut, puis compressé » (comportement 0.2.0, par défaut) ou « Compressé en
  direct ». En direct, mpv écrit le MJPEG dans une file nommée, Lucarne la vide dans deux fils sans jamais faire
  attendre mpv (réserve en mémoire jusqu'à 512 Mo ; au-delà l'enregistrement s'arrête mais l'image continue) et la
  passe à ffmpeg, qui compresse en H.264 en direct (VA-API, sinon x264 `ultrafast`), hors file Gagarine car en temps
  réel. Le son reste en FLAC ; à l'arrêt, image copiée telle quelle et son AAC réunis en MP4 en quelques secondes
  (par la file Gagarine). Essai réel : 8 s de 1080p60 → 1,5 Mo, image et son de même durée. Environ 2 à 4 Go/h au
  lieu de 24 à 70 Go/h.
- Choix des dossiers : **Dossier des captures** et **Dossier des vidéos**, bouton **Changer…** (sélecteur de
  dossier) et bouton de retour au dossier par défaut.
- Réglages `enregistrement_direct`, `dossier_images`, `dossier_videos` (vide = `<Images>/Lucarne`,
  `<Vidéos>/Lucarne`).

## [0.2.0] - 2026-11-25

### Ajouté
- Capture d'image : bouton **Capturer** ou touche `S` dans la fenêtre de mpv, PNG dans `~/Images/Lucarne`
  (`Lucarne AAAA-MM-JJ HH-MM-SS.png`), par la prise de commande de mpv (`--input-ipc-server`).
- Enregistrement : bouton ou touche `R`. mpv copie le flux MJPEG brut (rien de plus sur l'image) et GStreamer
  enregistre le son de la carte en FLAC, dans `~/Vidéos/Lucarne/brut/` (environ 24 Go/h en 720×480, 70 Go/h en 1080p) ;
  arrêt automatique sous 2 Go libres, refus de démarrer sous 4 Go.
- Compression à l'arrêt : `systemd-run --user` lance `lucarne --compresser <description.json>`, qui passe ffmpeg par la
  file Gagarine (priorité de fond) : H.264 VA-API (sinon x264) et AAC vers `~/Vidéos/Lucarne/<nom>.mp4`, suppression
  du brut, notification du bureau. Son calé sur l'image (décalage mesuré).
- Bruts restés en attente relancés au démarrage ; en cas d'échec, brut gardé, erreur notée dans le `.json`, relance
  manuelle par `lucarne --compresser`.
- Retard réel : rangée **Retard réel** (section Image). Une mire (carré noir/blanc sur fond gris, toutes les 0,4 s,
  sans danger pour l'épilepsie) s'affiche une dizaine de secondes en plein écran sur la sortie HDMI branchée sur la
  carte ; résultat = retard de la carte (médiane) + décodage + un rafraîchissement d'écran = retard total. Gardé dans
  les réglages (`retards`, `ecran_mire`). `Échap` arrête la mire.
- Dépendances : `ffmpeg`, `gstreamer1.0-pulseaudio`.

## [0.1.0] - 2026-11-25

### Ajouté
- Fenêtre GTK 4 / libadwaita : carte, mode, plein écran, son de la carte, sortie, tampon du son, bouton
  Regarder / Arrêter.
- Image par mpv réglé pour la latence minimale (`--untimed`, profil `low-latency`, pas de cache, une image d'avance
  côté carte graphique, décodage logiciel sur un fil).
- Son par `pw-loopback`, directement de la carte vers la sortie choisie ; changement de sortie ou de tampon pendant
  la lecture.
- Test de vitesse : cadence réelle, attente et décodage mesurés pour chaque mode ; mode Automatique sur le plus
  rapide (à 1 ms près, la plus grande résolution) ; résultats gardés par carte.
- Son de la carte trouvé par l'appareil USB commun à l'image et au son.
- Suivi en direct des cartes (moniteur GStreamer) et des sources et sorties audio (`pactl subscribe`).
- Alerte quand la sortie est en Bluetooth (environ 200 ms de retard sur le son).
- Réglages gardés dans `~/.config/lucarne/reglages.json`.
- Paquet `.deb` (lanceur de bureau, icônes, metainfo).

[0.3.0]: https://github.com/mawena/lucarne/releases/tag/v0.3.0
[0.2.0]: https://github.com/mawena/lucarne/releases/tag/v0.2.0
[0.1.0]: https://github.com/mawena/lucarne/releases/tag/v0.1.0
