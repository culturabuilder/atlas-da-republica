#!/usr/bin/env bash
# Atualização diária: conectores → build do grafo → site estático.
# Uso: scripts/update.sh [--fast]   (--fast pula SIORG completo e Wikidata, que são lentos)
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
[ -f .env ] && set -a && . ./.env && set +a
FAST=${1:-}
echo "== SIORG";           $PY etl/siorg.py ${FAST:+--no-full} --cache build
echo "== Câmara/Senado";   $PY etl/parlamentares.py --cache build
echo "== Sabatinas";       $PY etl/sabatinas.py
echo "== Build (1/2)";     $PY scripts/build_graph.py > /dev/null
[ -z "$FAST" ] && { echo "== Wikidata"; $PY etl/wikidata.py; }
echo "== Notícias";        $PY etl/noticias.py
echo "== DOU";             $PY etl/dou.py || echo "DOU falhou (segue)"
echo "== Orçamento";        $PY etl/orcamento.py || echo "Orçamento falhou (sem chave?)"
echo "== Build (2/2)";     $PY scripts/build_graph.py
echo "== Site";            $PY scripts/build_site.py --base "${SITE_BASE:-https://atlasdarepublica.org}"
