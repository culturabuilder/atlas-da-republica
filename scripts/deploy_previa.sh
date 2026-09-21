#!/bin/sh
# Publica uma PRÉVIA de testes em https://culturabuilder.github.io/atlas-previa/ (repositório separado,
# noindex, faixa de aviso). Não toca no site oficial nem na main. Uso: scripts/deploy_previa.sh
# Leve: leva home, app, JSON de nós/pessoas, imagens e páginas auxiliares; não leva as 2.300 páginas
# estáticas nem as imagens OG (a navegação por #id cobre tudo na prévia).
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
PY="$ROOT/.venv/bin/python"
REPO="https://github.com/culturabuilder/atlas-previa.git"
BASE="https://culturabuilder.github.io"; PREFIX="/atlas-previa"
cd "$ROOT"
[ -f build/graph.core.js ] || $PY scripts/build_graph.py
$PY scripts/build_site.py --base "$BASE" --prefix "$PREFIX" --previa
OUT=$(mktemp -d "${TMPDIR:-/tmp}/atlas-previa.XXXXXX")
for f in index.html 404.html atlas.js atlas.css atlas-camera.js graph.br.js robots.txt .nojekyll; do [ -e "site/$f" ] && cp "site/$f" "$OUT/"; done
for d in nodes people img como-funciona comparar metodologia dados feeds; do [ -d "site/$d" ] && cp -R "site/$d" "$OUT/$d"; done
cd "$OUT"
git init -q -b gh-pages && git add -A && git -c user.name="atlas-previa" -c user.email="noreply@atlasdarepublica.org" commit -q -m "prévia $(date -u +%Y-%m-%dT%H:%MZ) ($(git -C "$ROOT" rev-parse --short HEAD))"
git push -q --force "$REPO" gh-pages
cd "$ROOT" && rm -rf "$OUT"
echo "prévia enviada: $BASE$PREFIX/ (o GitHub Pages leva 1-2 min para atualizar)"
