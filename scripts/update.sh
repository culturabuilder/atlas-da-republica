#!/usr/bin/env bash
# Atualização diária: conectores → build do grafo → site estático.
# Uso: scripts/update.sh [--fast]   (--fast pula SIORG completo e Wikidata, que são lentos)
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
mkdir -p build build/cache-comissoes
[ -f .env ] && set -a && . ./.env && set +a
FAST=${1:-}
echo "== SIORG";           $PY etl/siorg.py ${FAST:+--no-full} --cache build || echo "SIORG falhou (segue com os dados do último dia)"
echo "== Câmara/Senado";   $PY etl/parlamentares.py --cache build || echo "Câmara/Senado falhou (segue com os dados do último dia)"
echo "== Comissões";       $PY etl/comissoes.py --cache build/cache-comissoes || echo "comissões falhou (segue)"
echo "== Build (1/2)";     $PY scripts/build_graph.py > /dev/null
echo "== Sabatinas";       $PY etl/sabatinas.py || echo "Sabatinas falhou (segue com os dados do último dia)"
[ -z "$FAST" ] && { echo "== Wikidata"; $PY etl/wikidata.py || echo "Wikidata falhou (segue)"; }
echo "== Notícias";        $PY etl/noticias.py || echo "Notícias falhou (segue com os dados do último dia)"
echo "== DOU";             $PY etl/dou.py || echo "DOU falhou (segue)"
echo "== DOU assinaturas"; $PY etl/dou_assinaturas.py || echo "assinaturas falhou (segue)"
echo "== Wikipédia";        $PY etl/wikipedia.py || echo "wikipedia falhou (segue)"
echo "== Nascimentos";      $PY etl/nascimentos.py || echo "nascimentos falhou (segue)"
echo "== Omissão";         $PY etl/omissao.py || echo "omissão falhou (segue)"
echo "== Temas";           $PY etl/temas.py || echo "temas falhou (segue)"
echo "== Arrecadação";     $PY etl/arrecadacao.py || echo "arrecadação falhou (segue)"
echo "== Atividade";       $PY etl/atividade.py || echo "atividade falhou (segue)"
echo "== Votos 2022";      $PY etl/votos.py || echo "votos falhou (segue)"
echo "== Patrimônio";      $PY etl/patrimonio.py || echo "patrimônio falhou (segue)"
echo "== Candidaturas";    $PY etl/candidaturas.py || echo "candidaturas falhou (segue)"
echo "== Gabinetes";       $PY etl/gabinetes.py || echo "gabinetes falhou (segue)"
echo "== Gabinetes SF";    $PY etl/gabinetes_senado.py || echo "gabinetes do Senado falhou (segue)"
echo "== Emendas";         $PY etl/emendas.py || echo "emendas falhou (segue)"
echo "== Renúncias";       $PY etl/renuncias.py || echo "renúncias falhou (segue)"
echo "== Teto";            $PY etl/teto.py || echo "teto falhou (segue)"
echo "== Orçamento";        $PY etl/orcamento.py || echo "Orçamento falhou (sem chave?)"
echo "== Build (2/2)";     $PY scripts/build_graph.py
echo "== Site";            $PY scripts/build_site.py --base "${SITE_BASE:-https://atlasdarepublica.org}" --prefix "${SITE_PREFIX:-}" --cname "${SITE_CNAME:-}"
