#!/usr/bin/env python3
"""Renúncias fiscais (gastos tributários) → data/generated/renuncias.yaml.

Fonte: Receita Federal, Demonstrativo dos Gastos Tributários, planilha "DGT Previsão PLOA {ano} - Quadros.xlsx"
(Quadro IV: por função orçamentária e por gasto tributário, regionalizado; a soma das regiões é o total nacional).
Cruzamento: renúncia por função × despesa empenhada dos ministérios da mesma área (orçamento já no grafo).
Uso: .venv/bin/python etl/renuncias.py [--ano 2026]
"""
import io, sys, json, re, pathlib, datetime, argparse, urllib.request
import yaml, openpyxl
ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / "build" / "cache-renuncias"; CACHE.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (Macintosh) atlas-da-republica/0.1"}
# função orçamentária da renúncia → ministério que executa a mesma área (para comparar ordens de grandeza)
FUNC_MIN = {"Saúde": "br-ministerio-da-saude", "Educação": "br-ministerio-da-educacao", "Agricultura": "br-ministerio-da-agricultura-e-pecuaria", "Assistência Social": "br-ministerio-do-desenvolvimento-social",
            "Ciência e Tecnologia": "br-ministerio-da-ciencia-tecnologia-e-inovacao", "Cultura": "br-ministerio-da-cultura", "Desporto e Lazer": "br-ministerio-do-esporte", "Trabalho": "br-ministerio-do-trabalho-e-emprego",
            "Transporte": "br-ministerio-dos-transportes", "Habitação": "br-ministerio-das-cidades", "Energia": "br-ministerio-de-minas-e-energia", "Comércio e Serviço": "br-ministerio-do-desenvolvimento-industria-comercio-e-servicos", "Comércio e Serviços": "br-ministerio-do-desenvolvimento-industria-comercio-e-servicos",
            "Indústria": "br-ministerio-do-desenvolvimento-industria-comercio-e-servicos", "Direitos da Cidadania": "br-ministerio-dos-direitos-humanos-e-da-cidadania", "Previdência Social": "br-ministerio-da-previdencia-social", "Defesa Nacional": "br-ministerio-da-defesa"}
def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--ano", type=int, default=datetime.date.today().year); a = ap.parse_args()
    p = CACHE / f"dgt-{a.ano}.xlsx"
    if not p.exists():
        url = f"https://www.gov.br/receitafederal/pt-br/centrais-de-conteudo/publicacoes/relatorios/renuncia/gastos-tributarios-ploa/dgt-previsao-ploa-{a.ano}-quadros.xlsx/@@download/file"
        print("GET", url, file=sys.stderr); p.write_bytes(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=300).read())
    import warnings; warnings.filterwarnings("ignore")
    wb = openpyxl.load_workbook(p, read_only=True, data_only=True); ws = wb["Q IV"]
    rows = [r for r in ws.iter_rows(values_only=True)]
    head_i = next(i for i, r in enumerate(rows) if r and isinstance(r[0], str) and r[0].upper().startswith("FUNÇÃO"))
    ncols = [i for i, c in enumerate(rows[head_i]) if c and isinstance(c, str) and c.strip().upper() in ("NORTE", "NORDESTE", "CENTRO-OESTE", "SUDESTE", "SUL")]
    funcs = []; cur = None; gastos = []
    def tot(r): return sum(float(r[i] or 0) for i in ncols if isinstance(r[i], (int, float)))
    for r in rows[head_i + 1:]:
        if not r or r[0] is None or not isinstance(r[0], str): continue
        label = r[0].strip(); v = tot(r)
        if not label or label.upper().startswith("TOTAL"): 
            if label.upper().startswith("TOTAL"): total = v
            continue
        # linha de função: o valor é a soma dos gastos que a seguem; detectamos pela mudança de "bloco": função quando o próximo rótulo repete o total
        funcs.append((label, v))
    # separa funções de gastos: uma função é seguida por gastos cuja soma == seu valor
    out_funcs = []; out_gastos = []; i = 0
    while i < len(funcs):
        label, v = funcs[i]; j = i + 1; s = 0.0; items = []
        while j < len(funcs) and s + funcs[j][1] <= v * 1.0001 + 1:
            s += funcs[j][1]; items.append(funcs[j]); j += 1
            if abs(s - v) <= max(1.0, v * 1e-6): break
        if items and abs(s - v) <= max(1.0, v * 1e-6):
            out_funcs.append({"funcao": label, "valor": round(v, 2), "itens": len(items)}); out_gastos += [{"gasto": g, "funcao": label, "valor": round(x, 2)} for g, x in items]; i = j
        else:
            out_gastos.append({"gasto": label, "funcao": None, "valor": round(v, 2)}); i += 1
    total = total if "total" in dir() else sum(f["valor"] for f in out_funcs)
    g = json.load(open(ROOT / "build" / "graph.br.json", encoding="utf-8")); N = g["nodes"]
    compare = []
    for f in sorted(out_funcs, key=lambda x: -x["valor"]):
        nid = FUNC_MIN.get(f["funcao"]); b = ((N.get(nid) or {}).get("budget") or {})
        by = b.get(str(a.ano)) or b.get(str(a.ano - 1)) or {}
        compare.append({"funcao": f["funcao"], "renuncia": f["valor"], "ministerio": nid, "ministerio_nome": (N.get(nid) or {}).get("name"), "empenhado": by.get("empenhado"), "empenhado_ano": str(a.ano) if b.get(str(a.ano)) else (str(a.ano - 1) if b.get(str(a.ano - 1)) else None)})
    out = {"generated_at": datetime.date.today().isoformat(), "ano": a.ano, "fonte": f"Receita Federal, DGT Previsão PLOA {a.ano}, Quadro IV", "fonte_url": f"https://www.gov.br/receitafederal/pt-br/centrais-de-conteudo/publicacoes/relatorios/renuncia/gastos-tributarios-ploa",
           "total": round(total, 2), "por_funcao": sorted(out_funcs, key=lambda x: -x["valor"]), "gastos_top": sorted(out_gastos, key=lambda x: -x["valor"])[:20], "compare": compare[:12],
           "nota": "Estimativa oficial de quanto a União deixa de arrecadar por benefícios tributários. Não inclui benefícios fora do demonstrativo (ex.: isenção de lucros e dividendos), que estudos independentes estimam em centenas de bilhões a mais."}
    (ROOT / "data" / "generated" / "renuncias.yaml").write_text("# GERADO por etl/renuncias.py. Não edite à mão.\n" + yaml.dump(out, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    print(f"renúncias {a.ano}: total R$ {total/1e9:.1f} bi; {len(out_funcs)} funções; {len(out_gastos)} gastos")
    for f in out["por_funcao"][:6]: print("  ", f["funcao"], round(f["valor"]/1e9, 1), "bi")
    for x in out["gastos_top"][:6]: print("  ", x["gasto"][:50], round(x["valor"]/1e9, 1), "bi", "|", x["funcao"])
if __name__ == "__main__": main()
