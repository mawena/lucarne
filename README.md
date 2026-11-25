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
- **Alerte Bluetooth** : un casque Bluetooth ajoute environ 200 ms de retard au son ; Lucarne le rappelle quand la
  sortie en est un.

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
`pipewire-bin` (`pw-loopback`), `pulseaudio-utils` (`pactl`).

## Utilisation

1. Branche la carte de capture : elle apparaît dans **Carte**, avec son son dans **Son de la carte**.
2. Une fois, clique **Tester** (la source HDMI doit être allumée et aucun autre programme ne doit utiliser la carte) :
   le mode **Automatique** prend alors le plus rapide.
3. Choisis la **Sortie** du son (la sortie du système par défaut), puis **Regarder**.

Dans la fenêtre de l'image : `f` ou double-clic pour le plein écran, `q` pour fermer (le son s'arrête avec l'image).
La sortie du son et son tampon se changent pendant la lecture ; seul le son redémarre.

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
sortie du son (vide = sortie du système), tampon du son, plein écran au lancement, et les résultats du test de chaque
carte (par nom de carte). Supprimer ce fichier remet tout à zéro.

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
