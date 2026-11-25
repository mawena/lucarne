PYTHON ?= python3

.PHONY: test deb clean

# Tests unitaires (modes, appareils, commandes, choix du mode, réglages ; sans toucher à la carte)
test:
	$(PYTHON) -m unittest discover -s tests -t . -v

# Construit dist/lucarne_<version>_all.deb avec SHA256SUMS et lintian
deb:
	scripts/build-deb.sh

clean:
	rm -rf dist build debian/lucarne debian/.debhelper debian/files debian/*.substvars debian/*.debhelper debian/*.debhelper.log debian/debhelper-build-stamp
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
