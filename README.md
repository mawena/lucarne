# Lucarne

**L'image d'une carte de capture, sans retard, avec son son.**

Lucarne est une application Ubuntu (GTK 4) qui affiche l'image d'une carte de capture HDMI-USB (MS2109 et
semblables) avec le moins de retard possible, et envoie son son vers la sortie audio de ton choix : casque Bluetooth,
haut-parleurs du PC, dock. Elle s'installe par le dépôt APT signé de mawena, [apt.mawena.cloud](https://apt.mawena.cloud/).

```bash
curl -fsSL https://apt.mawena.cloud/installer.sh | sudo sh -s -- lucarne
```

## À quoi ça sert

Une carte de capture HDMI-USB donne deux flux séparés : l'image (`/dev/videoN`) et le son (une source audio à part).
Les lire avec un lecteur vidéo ordinaire pose trois problèmes :

- **le son ne sort pas** : mpv, à qui l'on donne l'image et le son comme deux entrées, garde le son en pause
  (le flux reste « bouchonné ») parce que les deux horloges ne s'accordent pas ;
- **l'image a du retard** : un lecteur garde quelques images en tampon pour un affichage régulier, ce qui se voit
  tout de suite quand on joue sur une console branchée à la carte ;
- **il faut connaître les bons réglages** : le format MJPEG (sans lui, la carte envoie du brut et le 1080p saccade),
  la résolution, la cadence, le nom de la source audio.

Lucarne règle tout ça en un bouton : **Regarder**.

## Fonctionnement

- **Image** : mpv réglé pour une source en direct (`--untimed`, profil `low-latency`, pas de cache, une seule image
  d'avance côté carte graphique, décodage MJPEG logiciel sur un fil). Chaque image s'affiche dès qu'elle est décodée.
- **Son** : `pw-loopback` envoie directement le son de la carte vers la sortie choisie, par PipeWire, avec un tampon
  réglable (30 ms par défaut). L'image et le son ne s'attendent pas.
- **Son de la carte trouvé tout seul** : la source audio branchée sur le même appareil USB que l'image est choisie
  d'office.
- **Test de vitesse** : pour chaque mode de la carte (format, résolution, cadence la plus haute), Lucarne ouvre la
  carte une seconde et demie et mesure la cadence réellement reçue (une carte annonce parfois 60 i/s et en livre 30),
  l'attente entre l'horodatage de l'image par le noyau et sa remise au programme, et le temps de décodage. Le mode
  **Automatique** prend ensuite le plus rapide ; à 1 ms près, la plus grande résolution. Les résultats sont gardés.
- **Branchements suivis en direct** : brancher ou débrancher une carte, un casque Bluetooth ou un dock met les listes
  à jour sans relancer.
- **Capture d'image** : la touche `s` (ou le bouton **Capturer**) demande à mpv, par sa prise de commande
  (`--input-ipc-server`), d'enregistrer l'image affichée en PNG.
- **Enregistrement** : pendant qu'on enregistre, mpv copie le flux MJPEG de la carte tel quel (`stream-record` : rien
  de plus sur l'image) et GStreamer enregistre le son de la carte en FLAC, dans du Matroska qui garde l'heure de chaque morceau. À l'arrêt, un processus séparé
  (`systemd-run --user`, donc indépendant de la fenêtre) lance `lucarne --compresser`, qui passe ffmpeg par la file
  Gagarine en priorité de fond : H.264 (VA-API si la carte graphique le permet, sinon x264) et AAC, en un MP4. Le
  son est calé sur l'image d'après le décalage mesuré au démarrage. Le brut est supprimé une fois le MP4 fini.
- **Retard réel** : une mire (un carré noir ou blanc sur fond gris, qui change toutes les 0,4 s, sans danger pour
  l'épilepsie) s'affiche en plein écran sur une sortie HDMI du PC branchée sur la carte. Lucarne chronomètre l'arrivée
  de chaque changement dans les images de la carte. Résultat : retard de la carte (médiane) + décodage + un
  rafraîchissement d'écran = retard total.
- **Alerte Bluetooth** : un casque Bluetooth ajoute environ 200 ms de retard au son ; Lucarne le rappelle quand la
  sortie en est un.

- **Enregistrement compressé en direct** (réglage **Manière d'enregistrer**) : mpv écrit le MJPEG dans une file
  nommée au lieu d'un fichier. Lucarne la vide dans deux fils, sans jamais faire attendre mpv (réserve en mémoire
  jusqu'à 512 Mo ; au-delà, l'enregistrement s'arrête mais l'image continue), et la passe à ffmpeg qui compresse en
  H.264 au fil de l'eau (VA-API, sinon x264 `ultrafast`). Ffmpeg tourne hors de la file Gagarine : c'est du temps
  réel. Le son reste en FLAC (Matroska) ; à l'arrêt, l'image est copiée telle quelle et le son passe en AAC, réunis en MP4 en
  quelques secondes (par la file Gagarine). Essai réel : 8 s de 1080p60 donnent 1,5 Mo, image et son de même durée.

En mode brut, l'enregistrement est volumineux : environ 24 Go par heure en 720×480 et 70 Go par heure en 1080p. En
mode direct, compter 2 à 4 Go par heure. Dans les deux cas, il refuse de démarrer sous 4 Go libres et s'arrête tout
seul sous 2 Go libres.

La latence affichée par le test est une estimation pour comparer les modes entre eux (un intervalle d'image, plus
l'attente, plus le décodage). Le retard total de bout en bout ajoute l'encodage dans la carte et l'affichage
(compositeur, écran), à peu près les mêmes pour tous les modes.

## Installation

Lucarne est publiée dans le dépôt APT signé unique de mawena, [apt.mawena.cloud](https://apt.mawena.cloud/).

### En une ligne

```bash
curl -fsSL https://apt.mawena.cloud/installer.sh | sudo sh -s -- lucarne
```

Le script ([à lire](https://apt.mawena.cloud/installer.sh)) ajoute la clé et le dépôt, puis installe Lucarne :
exactement les trois étapes ci-dessous.

### Pas à pas

```bash
# 1. La clé qui signe le dépôt
sudo curl -fsSL -o /usr/share/keyrings/mawena-depot.gpg https://apt.mawena.cloud/mawena-depot.gpg
# 2. Le dépôt
sudo curl -fsSL -o /etc/apt/sources.list.d/mawena-depot.sources https://apt.mawena.cloud/mawena-depot.sources
# 3. Lucarne
sudo apt update && sudo apt install mawena-depot lucarne
```

Empreinte de la clé du dépôt : `60A2 0BB2 21C9 1DAD F39D D55B 456B 0129 30FA 901D` (« mawena APT »).

### Mettre à jour

```bash
sudo apt update && sudo apt upgrade
```

### En dernier recours : le `.deb`

Chaque [release GitHub](https://github.com/mawena/lucarne/releases) joint `lucarne_<version>_all.deb` et
`SHA256SUMS` :

```bash
sha256sum -c SHA256SUMS && sudo apt install ./lucarne_<version>_all.deb
```

Dépendances (installées par apt) : Python 3, PyGObject, GTK 4, libadwaita, GStreamer (plugins good), mpv,
`pipewire-bin` (`pw-loopback`), `pulseaudio-utils` (`pactl`), `gstreamer1.0-pulseaudio` (son de
l'enregistrement), `ffmpeg` (compression). La file Gagarine est utilisée si elle est installée.

## Utilisation

1. Branche la carte de capture : elle apparaît dans **Carte**, avec son son dans **Son de la carte**.
2. Une fois, clique **Tester** (la source HDMI doit être allumée et aucun autre programme ne doit utiliser la carte) :
   le mode **Automatique** prend alors le plus rapide.
3. Choisis la **Sortie** du son (la sortie du système par défaut), puis **Regarder**.

Dans la fenêtre de l'image : `f` ou double-clic pour le plein écran, `s` pour capturer l'image, `r` pour démarrer ou
arrêter l'enregistrement, `q` pour fermer (le son s'arrête avec l'image). La sortie du son et son tampon se changent
pendant la lecture ; seul le son redémarre.

### Capturer une image

Bouton **Capturer** ou touche `S` dans la fenêtre de l'image : un PNG est écrit dans `~/Images/Lucarne`
(`Lucarne AAAA-MM-JJ HH-MM-SS.png`).

### Enregistrer

Dans la section **Capture et enregistrement**, la rangée **Manière d'enregistrer** propose :

- **Brut, puis compressé** (par défaut, comportement de la 0.2.0) : le plus léger pour le processeur pendant le jeu,
  mais 24 à 70 Go par heure en attendant la compression ;
- **Compressé en direct** : l'image est compressée en H.264 pendant l'enregistrement, 2 à 4 Go par heure, et la
  vidéo est prête quelques secondes après l'arrêt.

Les rangées **Dossier des captures** et **Dossier des vidéos** montrent où les fichiers vont ; **Changer…** ouvre un
sélecteur de dossier et le bouton de retour remet le dossier par défaut.

Bouton **Enregistrer** ou touche `R` (même touche pour arrêter). En mode brut, le brut va dans
`~/Vidéos/Lucarne/brut/`. À l'arrêt, la compression se lance toute seule en arrière-plan (priorité de fond, elle ne gêne pas le jeu) et produit
`~/Vidéos/Lucarne/<nom>.mp4` ; une notification du bureau annonce la fin. Les bruts restés en attente (PC éteint en
route, par exemple) sont relancés au démarrage de Lucarne. Si la compression échoue, le brut est gardé, l'erreur est
notée dans son `.json` et on la relance à la main :

```bash
lucarne --compresser ~/Vidéos/Lucarne/brut/<nom>.json
```

### Mesurer le retard réel

Dans la section Image, rangée **Retard réel** : branche une sortie HDMI du PC sur l'entrée de la carte, choisis cet
écran, clique **Mesurer**. La mire occupe cet écran en plein écran pendant une dizaine de secondes ; `Échap` l'arrête.
Le résultat (retard de la carte, décodage, rafraîchissement d'écran, total) est gardé pour la carte.

Sans l'interface, la même chose à la main :

```bash
pw-loopback -n lucarne -C <source de la carte> -P <sortie> -l 30 &
mpv av://v4l2:/dev/video0 --profile=low-latency \
  --demuxer-lavf-o=video_size=1280x720,input_format=mjpeg,framerate=60,fflags=+nobuffer \
  --untimed --no-audio --cache=no --hwdec=no --swapchain-depth=1
kill %1
```

## Configuration

Les réglages sont gardés dans `~/.config/lucarne/reglages.json` : dernière carte, mode choisi (vide = automatique),
sortie du son (vide = sortie du système), tampon du son, plein écran au lancement, les résultats du test de chaque
carte (par nom de carte, `tests`), les mesures du retard réel (`retards`) et l'écran de la mire (`ecran_mire`).
Supprimer ce fichier remet tout à zéro.

Réglages d'enregistrement (0.3.0) :

| Réglage | Rôle | Défaut |
| --- | --- | --- |
| `enregistrement_direct` | `true` : compressé en direct ; `false` : brut puis compressé | `false` |
| `dossier_images` | dossier des captures PNG | vide = `<Images>/Lucarne` |
| `dossier_videos` | dossier des vidéos finies (le brut va dans `brut/` à l'intérieur) | vide = `<Vidéos>/Lucarne` |

Par défaut : captures dans `~/Images/Lucarne`, vidéos finies dans `~/Vidéos/Lucarne`, bruts en attente dans
`~/Vidéos/Lucarne/brut` (suivent les dossiers Images et Vidéos de l'utilisateur).

## Structure

```
bin/lucarne                 lanceur (modules dans /usr/share/lucarne une fois installé)
lucarne/application.py      application GTK, menu, À propos
lucarne/fenetre.py          fenêtre : listes, bouton Regarder/Arrêter, test, suivi des branchements
lucarne/appareils.py        cartes (moniteur GStreamer), sources et sorties audio (pactl), association par l'USB
lucarne/modes.py            modes de la carte lus dans les caps GStreamer
lucarne/mesure.py           test de vitesse d'un mode et choix du plus rapide
lucarne/commandes.py        commandes mpv et pw-loopback
lucarne/lecture.py          processus de lecture suivis par GLib
lucarne/prise_mpv.py        prise de commande de mpv (--input-ipc-server) : capture, copie du flux, messages
lucarne/input.conf          touches S et R dans la fenêtre de mpv
lucarne/enregistrement.py   enregistrement brut ou direct (mpv + son FLAC, relais vers ffmpeg), calage du son, bruts en attente, lancement de la compression
lucarne/compression.py      lucarne --compresser : ffmpeg par la file Gagarine, MP4, notification
lucarne/retard.py           calcul du retard réel : fronts de la mire, appariement, médiane
lucarne/mire.py             mire plein écran et chronométrage des changements
lucarne/config.py           réglages
data/                       lanceur de bureau, icônes, metainfo
debian/, scripts/           paquet .deb (make deb)
tests/                      tests unitaires (make test)
```

## Développement

```bash
bin/lucarne        # lance l'application depuis le dépôt
make test          # tests unitaires
make deb           # dist/lucarne_<version>_all.deb, SHA256SUMS, lintian
```

Projet géré en git flow (`main`, `develop`, `feature/*`, `release/*`, tags `v<version>`).

## Licence

MIT, © 2026 mawena. Voir [LICENSE](LICENSE).
