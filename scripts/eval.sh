#!/usr/bin/env bash
# Eval completo do Atlas: constrói, compara com o estado anterior, olha o site no ar e roda as
# verificações de interface. Não conserta nada; só diz o que está errado e sai com código 1.
#
# Uso: scripts/eval.sh            (completo)
#      scripts/eval.sh --rapido   (pula as verificações de navegador)
set -uo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
PW=/private/tmp/claude-501/-Users-culto-govnew/cbdbacff-6e4d-44b6-b805-449b42969f6f/scratchpad/pw
PORTA=8767
BASE=https://atlasdarepublica.org
RAPIDO=${1:-}
problemas=0
sec(){ printf '\n=== %s\n' "$1"; }
ok(){ printf '   ok   %s\n' "$1"; }
mal(){ printf '   ERRO %s\n' "$1"; problemas=$((problemas+1)); }
aviso(){ printf '   !    %s\n' "$1"; }

sec "dependências"
if $PY scripts/checar_dependencias.py >/dev/null 2>&1; then ok "todos os pacotes declarados e instalados"; else mal "faltam dependências (veja requirements.txt)"; fi

sec "repositório"
git fetch -q origin 2>/dev/null
atras=$(git rev-list --count HEAD..origin/main 2>/dev/null || echo 0)
sujos=$(git status --porcelain | wc -l | tr -d ' ')
[ "$atras" -gt 0 ] && aviso "$atras commit(s) atrás de origin/main" || ok "em dia com origin/main"
[ "$sujos" -gt 0 ] && aviso "$sujos arquivo(s) modificados sem commit" || ok "árvore limpa"

sec "arquivos gerados que encolheram"
enc=0
while read -r f; do
  [ -n "$f" ] || continue
  a=$(git show "HEAD:$f" 2>/dev/null | wc -c | tr -d ' '); b=$(wc -c < "$f" 2>/dev/null | tr -d ' ')
  if [ "${a:-0}" -gt 2000 ] && [ "${b:-0}" -lt $(( a * 2 / 5 )) ]; then mal "$f: $a -> $b bytes"; enc=$((enc+1)); fi
done < <(find data/generated -type f)
[ "$enc" -eq 0 ] && ok "nenhum arquivo encolheu"

sec "build do grafo"
saida=$($PY scripts/build_graph.py 2>&1); codigo=$?
if [ $codigo -ne 0 ]; then mal "build_graph falhou"; echo "$saida" | tail -4
else
  echo "$saida" | grep -E "^OK" | sed 's/^/   /'
  $PY - <<'PY'
import json, pathlib, sys
G=json.load(open("build/graph.br.json")); s=G["stats"]
base=pathlib.Path("build/_eval_base.json")
atual={"nos":s["nodes"],"arestas":s["edges"],"cadeiras":s["seats_total"],
       "pessoas":len(G.get("people") or {}),"custo":s.get("cargos_com_custo"),
       "power":len(G.get("power") or []),"fios":len(G.get("power_links") or [])}
if base.exists():
    ant=json.loads(base.read_text()); ruim=0
    for k,v in atual.items():
        a=ant.get(k)
        if isinstance(a,int) and isinstance(v,int) and a>0 and v < a*0.95:
            print(f"   ERRO {k}: {a} -> {v} (queda de {100-100*v/a:.0f}%)"); ruim+=1
        elif a!=v: print(f"   !    {k}: {a} -> {v}")
    if not ruim: print("   ok   nenhuma queda acima de 5% contra a execução anterior")
    sys.exit(1 if ruim else 0)
else:
    print("   !    primeira execução: gravando linha de base")
base.write_text(json.dumps(atual))
PY
  [ $? -ne 0 ] && problemas=$((problemas+1))
  $PY - <<'PY'
import json
s=json.load(open("build/graph.br.json"))["stats"]
ex=s.get("execucao") or {}
v=ex.get("blocos_velhos") or []
print(f"   {'!   ' if v else 'ok  '} blocos com mais de 7 dias: {len(v)}{': '+', '.join(map(str,v[:5])) if v else ''}")
f=ex.get("falhas") or []
print(f"   {'!   ' if f else 'ok  '} conectores com falha no último update: {len(f)}{': '+', '.join(f[:6]) if f else ''}")
PY
fi

sec "build do site"
saida=$($PY scripts/build_site.py 2>&1); codigo=$?
if [ $codigo -ne 0 ]; then mal "build_site falhou"; echo "$saida" | tail -4
else echo "$saida" | tail -1 | sed 's/^/   ok   /'; fi

sec "fila de revisão do Eikos"
$PY - <<'PY'
import yaml, json
try:
    r=yaml.safe_load(open("data/generated/resumos.yaml"))["resumos"]
    al=[v for v in r.values() if v.get("alertas")]
    novos=[(v.get("conf",0), v.get("title")) for v in al if not v.get("revisto_em")]
    print(f"   {'!   ' if novos else 'ok  '} resumos com alerta: {len(al)} de {len(r)}, sendo {len(novos)} ainda sem revisão humana")
    for c,t in sorted(novos, reverse=True)[:5]: print(f"        {c:.2f} {t}")
except Exception as e: print("   !    resumos:", str(e)[:70])
try:
    A=json.load(open("data/generated/noticias.json"))["articles"].values()
    sem=[a for a in A if "gov" not in a]; baixo=[a for a in A if a.get("gov_conf",1) < 0.8]
    print(f"   ok   artigos: {len(list(A))} · sem veredito {len(sem)} · abaixo de 0,80 {len(baixo)}")
except Exception as e: print("   !    notícias:", str(e)[:70])
PY

sec "site no ar"
for u in "" "do-zero/" "metodologia/" "dados/" "comparar/" "como-funciona/"; do
  c=$(curl -s -o /dev/null -m 20 -w "%{http_code}" "$BASE/$u")
  [ "$c" = "200" ] && ok "/$u" || mal "/$u devolveu $c"
done
n=$(curl -s -m 25 "$BASE/sitemap.xml" | grep -c "<url>")
[ "${n:-0}" -gt 2000 ] && ok "sitemap com $n endereços" || mal "sitemap com só ${n:-0} endereços"

sec "workflows"
# olha as três últimas rodadas: uma falha recente não pode ficar escondida por outra que começou depois
for w in "Publicar site" "Atualização diária"; do
  linhas=$(gh run list --workflow="$w" --limit 3 --json conclusion,status,createdAt,databaseId \
           -q '.[] | "\(.status) \(.conclusion // "-") \(.createdAt) \(.databaseId)"' 2>/dev/null)
  [ -z "$linhas" ] && { aviso "$w: sem informação"; continue; }
  primeira=$(echo "$linhas" | head -1)
  falhas=$(echo "$linhas" | grep -c "failure" || true)
  case "$primeira" in
    *in_progress*|*queued*) aviso "$w: rodando agora ($primeira)" ;;
    *success*) ok "$w: $primeira" ;;
    *) mal "$w: $primeira" ;;
  esac
  [ "${falhas:-0}" -gt 0 ] && mal "$w: $falhas das 3 últimas rodadas falharam" && echo "$linhas" | grep "failure" | sed 's/^/        /'
done
true

if [ "$RAPIDO" != "--rapido" ] && [ -d "$PW" ]; then
  sec "interface"
  curl -s -o /dev/null -m 3 "http://localhost:$PORTA/" || { (cd site && nohup python3 -m http.server $PORTA >/dev/null 2>&1 &) ; sleep 3; }
  for t in overflow dzov quebra svgfit pmap; do
    [ -f "$PW/$t.js" ] || continue
    saida=$(cd "$PW" && node "$t.js" 2>&1 | tail -3)
    if echo "$saida" | grep -qiE "erro|falha|estoura|FALHAS|quebrada"; then
      if echo "$saida" | grep -qiE "nenhuma palavra quebrada|contenção ok|erros \[\]"; then ok "$t"; else mal "$t"; echo "$saida" | sed 's/^/        /'; fi
    else ok "$t"; fi
  done
fi

sec "resultado"
if [ "$problemas" -eq 0 ]; then echo "   nada a corrigir"; else echo "   $problemas item(ns) pedem correção"; fi
exit $(( problemas > 0 ? 1 : 0 ))
