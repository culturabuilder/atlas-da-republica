#!/usr/bin/env bash
# Atualização diária: conectores → build do grafo → site estático.
# Uso: scripts/update.sh [--fast]   (--fast pula SIORG completo e Wikidata, que são lentos)
# Cada conector tem limite de tempo (ATLAS_LIMITE, 900s) e o conjunto tem orçamento (ATLAS_ORCAMENTO, 3h30).
# Estourado o orçamento, os conectores restantes são pulados e o job vai direto para o build e a publicação:
# é melhor publicar com um dado de ontem do que não publicar nada.
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
INICIO=$(date +%s)
# Dois limites, para o job nunca terminar sem publicar: um por conector e um para o conjunto.
# Um conector que estoura o tempo é cortado e o site segue com o dado do último dia que deu certo.
LIMITE=${ATLAS_LIMITE:-900}          # segundos por conector; LIM=1800 run ... aumenta para um só
ORCAMENTO=${ATLAS_ORCAMENTO:-12600}  # 3h30 para todos os conectores; depois disso vai direto para o build
# Quatro conectores varrem centenas de páginas oficiais uma a uma e passam de 15 minutos: posses, ocupantes
# pelo DOU, segundo escalão e agendas. O que eles medem muda devagar, então rodam uma vez por semana, com
# prazo folgado, em vez de serem cortados todo dia. ATLAS_SEMANAL=1 força; ATLAS_SEMANAL=0 pula.
DIA_SEMANAL=${ATLAS_DIA_SEMANAL:-7}   # 7 = domingo
if [ -n "${ATLAS_SEMANAL:-}" ]; then SEMANAL=$ATLAS_SEMANAL
elif [ "$(date +%u)" = "$DIA_SEMANAL" ]; then SEMANAL=1
else SEMANAL=0; fi
semanal() {  # semanal <segundos> "Nome" comando...
  local lim="$1"; shift
  if [ "$SEMANAL" = 1 ]; then LIM=$lim run "$@"
  else echo "== $1 fora do dia semanal (roda no dia $DIA_SEMANAL da semana)"
       printf '%s\t%s\t%s\n' "$1" "fora do dia semanal" "0" >> "$EXEC_LOG"; fi
}
_tempo() {  # timeout portátil: GNU timeout no Linux, perl no macOS
  local s="$1"; shift
  if command -v timeout >/dev/null 2>&1; then timeout -k 20 "$s" "$@"
  else perl -e 'my $s=shift; my $p=fork; if(!$p){exec @ARGV; exit 127} $SIG{ALRM}=sub{kill 9,$p; exit 124}; alarm $s; waitpid($p,0); my $c=$?>>8; alarm 0; exit $c' "$s" "$@"; fi
}
run() {  # run "Nome visível" comando...   (LIM=1800 run ... para um limite maior)
  local nome="$1"; shift
  local lim=${LIM:-$LIMITE}; unset LIM
  local gasto=$(( $(date +%s) - INICIO ))
  if [ "$gasto" -gt "$ORCAMENTO" ]; then
    echo "== $nome pulado: o orçamento de tempo dos conectores acabou aos ${gasto}s"
    printf '%s\t%s\t%s\n' "$nome" "pulado por tempo" "0" >> "$EXEC_LOG"; return 0
  fi
  local t0=$(date +%s)
  local marca=build/.run_marca; : > "$marca"
  echo "== $nome"
  local st=ok rc=0
  _tempo "$lim" "$@" || rc=$?
  if [ "$rc" -eq 124 ] || [ "$rc" -eq 137 ]; then st="tempo esgotado"; echo "$nome passou de ${lim}s e foi cortado"
  # Código 2 é a convenção dos conectores que dependem de arquivo baixado à mão (os zips do TSE):
  # num runner limpo eles nunca terão o insumo, e marcar isso como "falhou" todo dia vira ruído que
  # esconde a falha de verdade. O dado anterior continua publicado.
  elif [ "$rc" -eq 2 ]; then st="falta arquivo local"; echo "$nome não tem o arquivo que precisa ser baixado à mão; segue com o dado anterior"
  elif [ "$rc" -ne 0 ]; then st=falhou; echo "$nome falhou"; fi
  # Duas devoluções, para o site nunca publicar menos do que já tinha.
  # (1) Cortado ou quebrado, o conector pode ter deixado meio arquivo: vários escrevem em partes.
  # (2) Mesmo "com sucesso", um conector pode gravar quase nada quando a fonte está fora do ar ou
  #     quando falta um arquivo baixado à mão (os zips do TSE não existem num runner limpo). Isso já
  #     apagou dirigentes e patrimônio em produção. Encolher para menos de 40% do que estava
  #     commitado é tratado como falha, não como atualização.
  if [ -d .git ]; then
    local sujos=$(find data/generated -type f -newer "$marca" 2>/dev/null)
    local encolheu=""
    if [ "$st" = ok ] && [ -n "$sujos" ]; then
      while read -r f; do
        [ -n "$f" ] || continue
        local antes=$(git show "HEAD:$f" 2>/dev/null | wc -c | tr -d ' ')
        local agora=$(wc -c < "$f" 2>/dev/null | tr -d ' ')
        [ "${antes:-0}" -gt 2000 ] && [ "${agora:-0}" -lt $(( antes * 2 / 5 )) ] && encolheu="$encolheu $f"
      done <<< "$sujos"
    fi
    if [ -n "$encolheu" ]; then
      st="encolheu, devolvido"
      echo "$nome gravou bem menos do que já existia; devolvido:$encolheu"
    fi
    if { [ "$st" != ok ] || [ -n "$encolheu" ]; } && [ -n "$sujos" ]; then
      echo "$sujos" | while read -r f; do [ -n "$f" ] && git checkout -- "$f" 2>/dev/null && echo "   devolvido ao estado anterior: $f"; done
    fi
  fi
  rm -f "$marca"
  printf '%s\t%s\t%s\n' "$nome" "$st" "$(( $(date +%s) - t0 ))" >> "$EXEC_LOG"
}
# antes de três horas de trabalho, meio segundo conferindo que os pacotes estão todos lá
$PY scripts/checar_dependencias.py || { echo "faltam dependências; veja requirements.txt"; exit 1; }
LIM=1800 run "SIORG" $PY etl/siorg.py ${FAST:+--no-full} --cache build
run "Câmara/Senado" $PY etl/parlamentares.py --cache build
run "Comissões" $PY etl/comissoes.py --cache build/cache-comissoes
INICIO_ORC=$INICIO; INICIO=$(date +%s); LIM=1800 run "Build (1/2)" $PY scripts/build_graph.py > /dev/null; INICIO=$INICIO_ORC
run "Colegiados" $PY etl/colegiados.py   # lê build/graph.br.json: só roda depois do primeiro build
run "Sabatinas" $PY etl/sabatinas.py
[ -z "$FAST" ] && { run "Wikidata" $PY etl/wikidata.py || echo "Wikidata falhou (segue)"; }
run "Notícias" $PY etl/noticias.py
LIM=1200 run "DOU" $PY etl/dou.py
LIM=1200 run "DOU assinaturas" $PY etl/dou_assinaturas.py
semanal 2700 "Posses" $PY etl/posses.py
semanal 2700 "Ocupantes pelo DOU" $PY etl/ocupantes_dou.py
semanal 2700 "Segundo escalão" $PY etl/segundo_escalao.py
semanal 2700 "Dirigentes" $PY etl/dirigentes.py
run "Wikipédia" $PY etl/wikipedia.py
run "Nascimentos" $PY etl/nascimentos.py
run "Histórico" $PY etl/historico.py
run "Omissão" $PY etl/omissao.py
run "Temas" $PY etl/temas.py
LIM=1800 run "Resumos" $PY etl/resumos.py --limit 120
run "Arrecadação" $PY etl/arrecadacao.py
run "Atividade" $PY etl/atividade.py
run "Votos 2022" $PY etl/votos.py
run "Patrimônio" $PY etl/patrimonio.py
run "Doadores" $PY etl/doadores.py
run "Candidaturas" $PY etl/candidaturas.py
run "Proposições" $PY etl/proposicoes.py
run "Gabinetes" $PY etl/gabinetes.py
run "Gabinetes SF" $PY etl/gabinetes_senado.py
semanal 2700 "Agendas" $PY etl/agendas.py
LIM=1800 run "Agenda Planalto" $PY etl/agenda_planalto.py
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
INICIO=$(date +%s)  # build e site ficam fora do orçamento: sem eles o job não publica nada
LIM=1800 run "Build (2/2)" $PY scripts/build_graph.py
LIM=1800 run "Site" $PY scripts/build_site.py --base "${SITE_BASE:-https://atlasdarepublica.org}" --prefix "${SITE_PREFIX:-}" --cname "${SITE_CNAME:-}"
awk -F'\t' '{printf "   %-22s %-16s %ss\n", $1, $2, $3}' "$EXEC_LOG" | sort -t' ' -k3 -rn | head -8
echo "registro de execução em data/generated/_execucao.yaml"
