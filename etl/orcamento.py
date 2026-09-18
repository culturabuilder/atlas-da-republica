#!/usr/bin/env python3
"""Portal da Transparência: despesas por órgão → data/generated/orcamento.yaml

Requer PORTAL_TRANSPARENCIA_KEY (em .env). Para cada órgão superior do SIAFI, baixa empenhado/liquidado/pago
do ano corrente e do anterior; casa cada órgão com um nó do grafo pelo nome e agrega por órgão superior.
Uso: .venv/bin/python etl/orcamento.py
"""
import json, os, re, sys, pathlib, datetime, urllib.request, urllib.parse, unicodedata, time
import yaml
ROOT = pathlib.Path(__file__).resolve().parent.parent
API = "https://api.portaldatransparencia.gov.br/api-de-dados"

def key():
    k = os.environ.get("PORTAL_TRANSPARENCIA_KEY")
    if not k and (ROOT / ".env").exists():
        for line in open(ROOT / ".env"):
            if line.startswith("PORTAL_TRANSPARENCIA_KEY="): k = line.split("=", 1)[1].strip()
    if not k: sys.exit("PORTAL_TRANSPARENCIA_KEY ausente")
    return k

def get(path, params, k):
    url = API + path + "?" + urllib.parse.urlencode(params)
    for i in range(4):
        try:
            r = urllib.request.Request(url, headers={"chave-api-dados": k, "Accept": "application/json"})
            with urllib.request.urlopen(r, timeout=90) as resp: return json.load(resp)
        except Exception as e:
            time.sleep(1.5 * (i + 1))
    return []

def norm(s): return re.sub(r"[^a-z0-9 ]", " ", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()).strip()
def money(s): return round(float(str(s).replace(".", "").replace(",", ".")), 2) if s else 0.0

def main():
    k = key()
    graph = json.load(open(ROOT / "build" / "graph.br.json", encoding="utf-8")); N = graph["nodes"]
    by_name = {}
    for n in N.values():
        if n["type"] == "dept_head": continue
        for a in [n["name"]] + list(n.get("aliases") or []):
            if a and len(norm(a)) > 3: by_name.setdefault(norm(a), n["id"])
    # órgãos superiores SIAFI (códigos terminados em 000, mais os que aparecem como orgaoSuperior)
    siafi = []
    for p in range(1, 60):
        page = get("/orgaos-siafi", {"pagina": p}, k)
        if not page: break
        siafi += page
    sup = sorted({o["codigo"] for o in siafi if str(o["codigo"]).endswith("000")})
    year = datetime.date.today().year
    rows = []
    for code in sup:
        for ano in (year, year - 1):
            for p in range(1, 20):
                page = get("/despesas/por-orgao", {"ano": ano, "orgaoSuperior": code, "pagina": p}, k)
                if not page: break
                rows += page
                if len(page) < 15: break
            time.sleep(0.4)
    out = {}
    for r in rows:
        nid = by_name.get(norm(r["orgao"])) or by_name.get(norm(re.sub(r" - Unidades com v[íi]nculo direto", "", r["orgao"])))
        entry = {"ano": r["ano"], "orgao": r["orgao"], "codigoOrgao": r["codigoOrgao"], "orgaoSuperior": r["orgaoSuperior"], "codigoOrgaoSuperior": r["codigoOrgaoSuperior"],
                 "empenhado": money(r["empenhado"]), "liquidado": money(r["liquidado"]), "pago": money(r["pago"]), "node": nid}
        out.setdefault(str(r["codigoOrgaoSuperior"]), []).append(entry)
    # agrega por órgão superior e por nó
    nodes_budget = {}
    for code, entries in out.items():
        sup_name = entries[0]["orgaoSuperior"]; sup_id = by_name.get(norm(sup_name))
        for ano in (year, year - 1):
            tot = {"empenhado": sum(e["empenhado"] for e in entries if e["ano"] == ano), "liquidado": sum(e["liquidado"] for e in entries if e["ano"] == ano), "pago": sum(e["pago"] for e in entries if e["ano"] == ano)}
            if sup_id and tot["empenhado"]: nodes_budget.setdefault(sup_id, {})[str(ano)] = dict(tot, escopo="órgão superior (inclui vinculadas)", codigo=code)
        for e in entries:
            if e["node"] and e["node"] != sup_id:
                nodes_budget.setdefault(e["node"], {})[str(e["ano"])] = {"empenhado": e["empenhado"], "liquidado": e["liquidado"], "pago": e["pago"], "escopo": "órgão", "codigo": e["codigoOrgao"]}
    class D(yaml.SafeDumper):
        def increase_indent(self, flow=False, indentless=False): return super().increase_indent(flow, False)
    (ROOT / "data" / "generated" / "orcamento.yaml").write_text("# GERADO por etl/orcamento.py (Portal da Transparência, despesas por órgão). Valores em R$.\n" + yaml.dump({"generated_at": datetime.date.today().isoformat(), "source": "https://portaldatransparencia.gov.br/api-de-dados/despesas/por-orgao", "nodes": nodes_budget}, Dumper=D, allow_unicode=True, sort_keys=True, width=110), encoding="utf-8")
    print(f"órgãos superiores={len(sup)} linhas={len(rows)} nós com orçamento={len(nodes_budget)} sem casar={sum(1 for es in out.values() for e in es if not e['node'])}")
    top = sorted(((v.get(str(year), {}).get("empenhado", 0), N[k]["name"]) for k, v in nodes_budget.items()), reverse=True)[:8]
    for v, n in top: print(f"  {n[:50]:50} R$ {v/1e9:,.1f} bi empenhado em {year}")

if __name__ == "__main__": main()
