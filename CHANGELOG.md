# Journal des modifications

Toutes les modifications notables de Lucarne sont consignées ici.
Format : [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/), versions : [SemVer](https://semver.org/lang/fr/).

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

[0.1.0]: https://github.com/mawena/lucarne/releases/tag/v0.1.0
