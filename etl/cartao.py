#!/usr/bin/env python3
"""Cartão de pagamento do governo federal (CPGF) → data/generated/cartao.yaml.

Fonte: Portal da Transparência, arquivos mensais "{AAAAMM}_CPGF.zip" (portador, órgão, favorecido, transação, valor).
Saída: por ocupante de cargo do Executivo (casamento por nome completo do portador), gastos no ano, número de transações,
maiores favorecidos e saques; e por órgão, total do ano. CPF do portador é mascarado na fonte e não é usado.
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
    want = {}
    for n in N.values():
        if n["type"] != "dept_head" or n.get("sector") != "executivo": continue
        for h in n.get("people") or []:
            if h.get("id") and h.get("name"): want.setdefault(norm(h.get("full_name") or h["name"]), []).append(h["id"])
    per = collections.defaultdict(lambda: {"total": 0.0, "n": 0, "saques": 0.0, "fav": collections.defaultdict(float), "meses": collections.defaultdict(float), "orgao": None})
    org = collections.defaultdict(lambda: {"total": 0.0, "n": 0, "portadores": set(), "saques": 0.0}); months = []
    for m in range(1, TODAY.month + 1):
        ym = f"{TODAY.year}{m:02d}"; data = fetch(ym)
        if not data: continue
        months.append(ym); z = zipfile.ZipFile(io.BytesIO(data)); name = [x for x in z.namelist() if x.endswith(".csv")][0]
        with z.open(name) as f:
            for r in csv.DictReader(io.TextIOWrapper(f, encoding="latin1"), delimiter=";"):
                v = money(r["VALOR TRANSAÇÃO"]); o = r["NOME ÓRGÃO SUPERIOR"]; saque = "SAQUE" in (r["TRANSAÇÃO"] or "").upper()
                og = org[o]; og["total"] += v; og["n"] += 1; og["portadores"].add(r["NOME PORTADOR"]); og["saques"] += v if saque else 0
                k = norm(r["NOME PORTADOR"])
                if k in want:
                    for pid in want[k]:
                        d = per[pid]; d["total"] += v; d["n"] += 1; d["saques"] += v if saque else 0; d["fav"][(r["NOME FAVORECIDO"] or "").title() or ("Saque" if saque else "—")] += v; d["meses"][ym] += v; d["orgao"] = o
    people = {pid: {"total": round(d["total"], 2), "transacoes": d["n"], "saques": round(d["saques"], 2), "orgao": d["orgao"], "meses": {k: round(v, 2) for k, v in sorted(d["meses"].items())},
                    "favorecidos": [{"nome": k, "valor": round(v, 2)} for k, v in sorted(d["fav"].items(), key=lambda kv: -kv[1])[:5]]} for pid, d in per.items()}
    orgs = sorted(({"orgao": o, "total": round(d["total"], 2), "transacoes": d["n"], "portadores": len(d["portadores"]), "saques": round(d["saques"], 2)} for o, d in org.items()), key=lambda x: -x["total"])
    out = {"generated_at": TODAY.isoformat(), "ano": TODAY.year, "meses": months, "fonte": "Portal da Transparência, cartão de pagamento do governo federal (CPGF), extratos mensais", "people": people, "orgaos": orgs[:25],
           "total": round(sum(d["total"] for d in org.values()), 2), "nota": "Gastos com cartão corporativo lançados nos extratos de cada mês; saques são identificados pela descrição da transação. Portadores casados com ocupantes de cargos por nome completo."}
    (ROOT / "data" / "generated" / "cartao.yaml").write_text("# GERADO por etl/cartao.py. Não edite à mão.\n" + yaml.dump(out, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    print(f"cartão {TODAY.year} ({len(months)} meses): R$ {out['total']/1e6:.1f} mi no total; {len(people)} ocupantes de cargos com gastos")
    for pid, v in sorted(people.items(), key=lambda kv: -kv[1]["total"])[:4]: print("  ", pid, v["total"], v["transacoes"], "transações |", v["orgao"], "| saques", v["saques"])
    for o in orgs[:3]: print("  órgão:", o["orgao"][:40], o["total"], o["portadores"], "portadores")
if __name__ == "__main__": main()
