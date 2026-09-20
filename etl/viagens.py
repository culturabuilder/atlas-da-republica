#!/usr/bin/env python3
"""Viagens a serviço → data/generated/viagens.yaml (por ocupante de cargo do Executivo e por órgão superior).

Fonte: Portal da Transparência, download anual "Viagens a serviço" (arquivo Viagem.csv: nome, cargo, órgão, período, destinos,
motivo, diárias, passagens). O nome do arquivo muda com a data de geração; a URL é resolvida pelo redirecionamento do portal.
Casamento por nome completo do viajante com os ocupantes de cargos do setor executivo. CPF é mascarado na fonte e não é usado.
Uso: .venv/bin/python etl/viagens.py
"""
import csv, io, re, sys, json, zipfile, pathlib, datetime, unicodedata, collections, urllib.request
import yaml
ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / "build" / "cache-viagens"; CACHE.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (Macintosh) atlas-da-republica/0.1"}
TODAY = datetime.date.today(); Y = TODAY.year
def norm(s): return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())).strip()
def money(s): return float(str(s or "0").replace(".", "").replace(",", ".") or 0)
def fetch():
    p = CACHE / f"{Y}_Viagens.zip"
    if p.exists() and (datetime.datetime.now() - datetime.datetime.fromtimestamp(p.stat().st_mtime)).total_seconds() < 6 * 86400: return p
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k): return None
    op = urllib.request.build_opener(NoRedirect)
    try: op.open(urllib.request.Request(f"https://portaldatransparencia.gov.br/download-de-dados/viagens/{Y}", headers=UA), timeout=60); url = None
    except urllib.error.HTTPError as e: url = e.headers.get("Location")
    if not url: print("viagens: não achou a URL do arquivo", file=sys.stderr); return p if p.exists() else None
    print("GET", url, file=sys.stderr); p.write_bytes(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=1800).read()); return p
def main():
    p = fetch()
    if not p: return
    g = json.load(open(ROOT / "build" / "graph.br.json", encoding="utf-8")); N = g["nodes"]
    want = {}
    for n in N.values():
        if n["type"] != "dept_head" or n.get("sector") != "executivo": continue
        for h in n.get("people") or []:
            if h.get("id") and h.get("name"): want.setdefault(norm(h.get("full_name") or h["name"]), []).append(h["id"])
    z = zipfile.ZipFile(p); name = [x for x in z.namelist() if x.endswith("_Viagem.csv")][0]
    per = collections.defaultdict(lambda: {"n": 0, "diarias": 0.0, "passagens": 0.0, "dest": collections.Counter(), "ultimas": [], "exterior": 0})
    org = collections.defaultdict(lambda: {"n": 0, "diarias": 0.0, "passagens": 0.0, "viajantes": set()})
    with z.open(name) as f:
        r = csv.DictReader(io.TextIOWrapper(f, encoding="latin1"), delimiter=";")
        for row in r:
            if (row.get("Situação") or "").strip().lower() not in ("realizada", "não realizada", ""): pass
            if (row.get("Situação") or "").strip().lower() != "realizada": continue
            d = money(row["Valor diárias"]); ps = money(row["Valor passagens"]); o = row["Nome do órgão superior"]
            og = org[o]; og["n"] += 1; og["diarias"] += d; og["passagens"] += ps; og["viajantes"].add(row["Nome"])
            k = norm(row["Nome"])
            if k not in want: continue
            dest = (row.get("Destinos") or "").strip(); ext = bool(re.search(r"/[A-Z]{2}\b", dest) is None and dest)  # destinos no Brasil terminam em /UF
            for pid in want[k]:
                v = per[pid]; v["n"] += 1; v["diarias"] += d; v["passagens"] += ps; v["dest"][dest[:60]] += 1; v["exterior"] += 1 if ext else 0
                v["ultimas"].append({"inicio": row["Período - Data de início"], "fim": row["Período - Data de fim"], "destino": dest[:80], "motivo": re.sub(r"^Motivo da viagem[^:]*:\s*", "", row.get("Motivo") or "")[:160], "diarias": round(d, 2), "passagens": round(ps, 2)})
    def dkey(s): 
        try: return datetime.datetime.strptime(s, "%d/%m/%Y")
        except Exception: return datetime.datetime.min
    people = {pid: {"viagens": v["n"], "diarias": round(v["diarias"], 2), "passagens": round(v["passagens"], 2), "total": round(v["diarias"] + v["passagens"], 2), "exterior": v["exterior"],
                    "destinos": [{"destino": k, "n": c} for k, c in v["dest"].most_common(4)], "ultimas": sorted(v["ultimas"], key=lambda x: dkey(x["inicio"]), reverse=True)[:4]} for pid, v in per.items()}
    orgs = sorted(({"orgao": o, "viagens": d["n"], "diarias": round(d["diarias"], 2), "passagens": round(d["passagens"], 2), "total": round(d["diarias"] + d["passagens"], 2), "viajantes": len(d["viajantes"])} for o, d in org.items()), key=lambda x: -x["total"])
    out = {"generated_at": TODAY.isoformat(), "ano": Y, "fonte": "Portal da Transparência, viagens a serviço (SCDP)", "people": people, "orgaos": orgs[:25], "total": round(sum(x["total"] for x in orgs), 2), "viagens_total": sum(x["viagens"] for x in orgs),
           "nota": "Viagens realizadas no ano, com diárias e passagens pagas pelo órgão; não inclui viagens do Legislativo e do Judiciário, que têm sistemas próprios."}
    (ROOT / "data" / "generated" / "viagens.yaml").write_text("# GERADO por etl/viagens.py. Não edite à mão.\n" + yaml.dump(out, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    print(f"viagens {Y}: {out['viagens_total']} viagens, R$ {out['total']/1e6:.1f} mi; {len(people)} ocupantes de cargos com viagens")
    for pid, v in sorted(people.items(), key=lambda kv: -kv[1]["total"])[:4]: print("  ", pid, v["viagens"], "viagens, R$", v["total"], "| exterior", v["exterior"], "|", v["ultimas"][0]["destino"] if v["ultimas"] else "")
if __name__ == "__main__": main()
