#!/usr/bin/env bash
# Atualização diária: conectores → build do grafo → site estático.
# Uso: scripts/update.sh [--fast]   (--fast pula SIORG completo e Wikidata, que são lentos)
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
mkdir -p build build/cache-comissoes
[ -f .env ] && set -a && . ./.env && set +a
FAST=${1:-}
# registro de execução: cada conector vira uma linha "nome<TAB>status<TAB>segundos" em build/_execucao.tsv,
# que scripts/build_graph.py transforma em data/generated/_execucao.yaml e o site mostra como "atualizado em".
EXEC_LOG=build/_execucao.tsv
: > "$EXEC_LOG"
run() {  # run "Nome visível" comando...
  local nome="$1"; shift
  local t0=$(date +%s)
  echo "== $nome"
  if "$@"; then local st=ok; else local st=falhou; echo "$nome falhou (segue com os dados do último dia)"; fi
  printf '%s\t%s\t%s\n' "$nome" "$st" "$(( $(date +%s) - t0 ))" >> "$EXEC_LOG"
}
run "SIORG" $PY etl/siorg.py ${FAST:+--no-full} --cache build
run "Câmara/Senado" $PY etl/parlamentares.py --cache build
run "Comissões" $PY etl/comissoes.py --cache build/cache-comissoes
run "Colegiados" $PY etl/colegiados.py
run "Build (1/2)" $PY scripts/build_graph.py > /dev/null
run "Sabatinas" $PY etl/sabatinas.py
[ -z "$FAST" ] && { run "Wikidata" $PY etl/wikidata.py || echo "Wikidata falhou (segue)"; }
run "Notícias" $PY etl/noticias.py
run "DOU" $PY etl/dou.py
run "DOU assinaturas" $PY etl/dou_assinaturas.py
run "Segundo escalão" $PY etl/segundo_escalao.py
run "Dirigentes" $PY etl/dirigentes.py
run "Wikipédia" $PY etl/wikipedia.py
run "Nascimentos" $PY etl/nascimentos.py
run "Histórico" $PY etl/historico.py
run "Omissão" $PY etl/omissao.py
run "Temas" $PY etl/temas.py
run "Resumos" $PY etl/resumos.py --limit 120
run "Arrecadação" $PY etl/arrecadacao.py
run "Atividade" $PY etl/atividade.py
run "Votos 2022" $PY etl/votos.py
run "Patrimônio" $PY etl/patrimonio.py
run "Doadores" $PY etl/doadores.py
run "Candidaturas" $PY etl/candidaturas.py
run "Proposições" $PY etl/proposicoes.py
run "Gabinetes" $PY etl/gabinetes.py
run "Gabinetes SF" $PY etl/gabinetes_senado.py
run "Agendas" $PY etl/agendas.py
run "Agenda Planalto" $PY etl/agenda_planalto.py
run "Emendas" $PY etl/emendas.py
run "Renúncias" $PY etl/renuncias.py
run "Teto" $PY etl/teto.py
run "Viagens" $PY etl/viagens.py
run "Cartão" $PY etl/cartao.py
run "Subsídios" $PY etl/subsidios.py
run "Remuneração" $PY etl/remuneracao.py
run "Orçamento" $PY etl/orcamento.py
run "Programas" $PY etl/programas.py
run "Transferências" $PY etl/transferencias.py
run "Build (2/2)" $PY scripts/build_graph.py
run "Site" $PY scripts/build_site.py --base "${SITE_BASE:-https://atlasdarepublica.org}" --prefix "${SITE_PREFIX:-}" --cname "${SITE_CNAME:-}"
printf '%s\t%s\t%s\n' "Site" "ok" "0" >> "$EXEC_LOG"
echo "registro de execução em data/generated/_execucao.yaml"
