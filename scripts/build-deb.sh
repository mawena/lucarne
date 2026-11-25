#!/usr/bin/env bash
# Construit dist/lucarne_<version>_all.deb : tests, paquet, sommes SHA-256, lintian.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Une seule version partout : debian/changelog et lucarne --version
deb_version="$(dpkg-parsechangelog -S Version)"
app_version="$(python3 bin/lucarne --version | awk '{print $NF}')"
if [[ "$deb_version" != "$app_version" ]]; then
  echo "Versions différentes : debian/changelog=$deb_version, lucarne=$app_version" >&2
  exit 1
fi

# Lanceur et metainfo valides (sans réseau) avant de construire
desktop-file-validate data/applications/*.desktop
appstreamcli validate --no-net data/metainfo/*.metainfo.xml

make clean >/dev/null
make test
dpkg-buildpackage -us -uc -b
make clean >/dev/null

mkdir -p dist
mv -f "../lucarne_${deb_version}_all.deb" dist/
rm -f "../lucarne_${deb_version}_"*.buildinfo "../lucarne_${deb_version}_"*.changes
(cd dist && sha256sum ./*.deb | sed 's| \./| |' > SHA256SUMS)

# Lintian sans erreur ni avertissement
lintian -I --fail-on error,warning "dist/lucarne_${deb_version}_all.deb"
echo "Paquet : dist/lucarne_${deb_version}_all.deb"
