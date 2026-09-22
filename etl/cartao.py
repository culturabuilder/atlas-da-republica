#!/usr/bin/env python3
"""Cartão de pagamento do governo federal (CPGF) → data/generated/cartao.yaml.

Fonte: Portal da Transparência, arquivos mensais "{AAAAMM}_CPGF.zip" (portador, órgão, favorecido, transação, valor).
Saída: por órgão (casado com o nó do grafo quando possível), total do ano, transações, saques, unidades gestoras que mais gastam
e maiores favorecidos. NÃO há bloco por pessoa: o portador do cartão é quase sempre servidor de execução, não o dirigente do órgão —
o casamento por nome com os ocupantes de cargo devolveu zero em todos os testes. CPF do portador é mascarado na fonte e não é usado.
Uso: .venv/bin/python etl/cartao.py
"""
import csv, io, re, sys, json, zipfile, pathlib, datetime, unicodedata, collections, urllib.request
import yaml
ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / "build" / "cache-cartao"; CACHE.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (Macintosh) atlas-da-republica/0.1"}
TODAY = datetime.date.today()
def norm(s): return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())).strip()
def money(s): return float(str(s or "0").replace(".", "").replace(",", ".") or 0)
def fetch(ym):
    p = CACHE / f"{ym}_CPGF.zip"
    if p.exists(): return p.read_bytes()
    url = f"https://dadosabertos-download.cgu.gov.br/PortalDaTransparencia/saida/cpgf/{ym}_CPGF.zip"
    try: data = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=300).read()
    except Exception as e: print("sem arquivo", ym, e, file=sys.stderr); return None
    p.write_bytes(data); return data
def main():
    g = json.load(open(ROOT / "build" / "graph.br.json", encoding="utf-8")); N = g["nodes"]
    # nós do grafo por nome normalizado, para ligar o órgão superior do extrato ao mapa
    node_by_name = {}
    for n in N.values():
        if n["type"] not in ("department", "elected"): continue
        for nm in [n.get("name")] + list(n.get("aliases") or []):
            if nm: node_by_name.setdefault(norm(nm), n["id"])
    org = collections.defaultdict(lambda: {"total": 0.0, "n": 0, "portadores": set(), "saques": 0.0,
                                           "ug": collections.defaultdict(float), "fav": collections.defaultdict(float),
                                           "meses": collections.defaultdict(float)}); months = []
    for m in range(1, TODAY.month + 1):
        ym = f"{TODAY.year}{m:02d}"; data = fetch(ym)
        if not data: continue
        months.append(ym); z = zipfile.ZipFile(io.BytesIO(data)); name = [x for x in z.namelist() if x.endswith(".csv")][0]
        with z.open(name) as f:
            for r in csv.DictReader(io.TextIOWrapper(f, encoding="latin1"), delimiter=";"):
                v = money(r["VALOR TRANSAÇÃO"]); o = r["NOME ÓRGÃO SUPERIOR"]; saque = "SAQUE" in (r["TRANSAÇÃO"] or "").upper()
                og = org[o]; og["total"] += v; og["n"] += 1; og["portadores"].add(r["NOME PORTADOR"]); og["saques"] += v if saque else 0
                og["meses"][ym] += v
                _ug = (r.get("NOME UNIDADE GESTORA") or r.get("NOME UNIDADE GESTORA ") or "").title()
                if _ug: og["ug"][_ug] += v
                _fav = (r.get("NOME FAVORECIDO") or "").title()
                og["fav"]["Saque em espécie" if saque else (_fav or "—")] += v
    orgs = sorted(({"orgao": o, "node_id": node_by_name.get(norm(o)), "total": round(d["total"], 2), "transacoes": d["n"],
                    "portadores": len(d["portadores"]), "saques": round(d["saques"], 2),
                    "por_mes": {k: round(v, 2) for k, v in sorted(d["meses"].items())},
                    "unidades_top": [{"nome": k, "valor": round(v, 2)} for k, v in sorted(d["ug"].items(), key=lambda kv: -kv[1])[:5]],
                    "favorecidos_top": [{"nome": k, "valor": round(v, 2)} for k, v in sorted(d["fav"].items(), key=lambda kv: -kv[1])[:5]]}
                   for o, d in org.items()), key=lambda x: -x["total"])
    out = {"generated_at": TODAY.isoformat(), "ano": TODAY.year, "meses": months, "fonte": "Portal da Transparência, cartão de pagamento do governo federal (CPGF), extratos mensais", "orgaos": orgs[:25],
           "total": round(sum(d["total"] for d in org.values()), 2), "orgaos_casados": sum(1 for o in orgs[:25] if o["node_id"]),
           "nota": ("Gastos com cartão corporativo lançados nos extratos de cada mês; saques são identificados pela descrição da transação. "
                    "O extrato traz o portador do cartão, em regra servidor de execução, não o dirigente do órgão: por isso o Atlas mostra o "
                    "gasto por órgão e por unidade gestora, e não por ocupante de cargo.")}
    (ROOT / "data" / "generated" / "cartao.yaml").write_text("# GERADO por etl/cartao.py. Não edite à mão.\n" + yaml.dump(out, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    print(f"cartão {TODAY.year} ({len(months)} meses): R$ {out['total']/1e6:.1f} mi no total; {out['orgaos_casados']} de {len(orgs[:25])} órgãos ligados ao grafo")
    for o in orgs[:3]: print("  órgão:", o["orgao"][:40], o["total"], o["portadores"], "portadores")
if __name__ == "__main__": main()
