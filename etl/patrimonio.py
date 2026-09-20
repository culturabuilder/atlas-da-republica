#!/usr/bin/env python3
"""Patrimônio declarado ao TSE (2018 e 2022) dos parlamentares e ocupantes → data/generated/patrimonio.yaml.

Fontes (zips baixados à mão em build/cache-tse/): bem_candidato_{ano}.zip (bens por SQ_CANDIDATO) e consulta_cand_{ano}.zip
(SQ_CANDIDATO → nome, urna, UF, cargo). Casamento com o grafo: nome completo idêntico (normalizado) ou nome de urna único no ano
+ mesma UF. Variação 2018→2022 nominal e em valor real (IPCA, IBGE/SIDRA 1737). Declaração é do próprio candidato ao TSE.
Uso: .venv/bin/python etl/patrimonio.py
"""
import csv, io, re, sys, json, zipfile, pathlib, datetime, unicodedata, collections, urllib.request
import yaml
ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / "build" / "cache-tse"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh) atlas-da-republica/0.1"}
def norm(s): return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())).strip()
def money(s): return float(str(s or "0").replace(".", "").replace(",", ".") or 0)
def ipca_factor(from_ym, to_ym):
    try:
        d = json.load(urllib.request.urlopen(urllib.request.Request("https://apisidra.ibge.gov.br/values/t/1737/n1/all/v/2266/p/all?formato=json", headers=UA), timeout=120))
        idx = {f"{r['D3C'][:4]}-{r['D3C'][4:6]}": float(r["V"]) for r in d[1:]}
        return idx[to_ym] / idx[from_ym], to_ym
    except Exception as e: print("IPCA falhou", e, file=sys.stderr); return None, None
def cands(ano):
    z = zipfile.ZipFile(CACHE / f"consulta_cand_{ano}.zip"); out = {}
    for name in z.namelist():
        if not name.endswith(".csv") or re.search(r"_(BR|BRASIL)\.csv$", name): continue
        with z.open(name) as f:
            r = csv.DictReader(io.TextIOWrapper(f, encoding="latin1"), delimiter=";")
            for row in r:
                if row.get("NR_TURNO") != "1": continue
                out[row["SQ_CANDIDATO"]] = {"nome": row["NM_CANDIDATO"], "urna": row["NM_URNA_CANDIDATO"], "uf": row["SG_UF"], "cargo": row["DS_CARGO"].title()}
    return out
def bens(ano):
    z = zipfile.ZipFile(CACHE / f"bem_candidato_{ano}.zip"); tot = collections.defaultdict(float); tipos = collections.defaultdict(lambda: collections.defaultdict(float)); n = collections.Counter()
    for name in z.namelist():
        if not name.endswith(".csv") or re.search(r"_(BR|BRASIL)\.csv$", name): continue
        with z.open(name) as f:
            for row in csv.DictReader(io.TextIOWrapper(f, encoding="latin1"), delimiter=";"):
                sq = row["SQ_CANDIDATO"]; v = money(row["VR_BEM_CANDIDATO"]); tot[sq] += v; tipos[sq][row["DS_TIPO_BEM_CANDIDATO"].title()] += v; n[sq] += 1
    return tot, tipos, n
def main():
    g = json.load(open(ROOT / "build" / "graph.br.json", encoding="utf-8")); P = g["people"]; N = g["nodes"]
    full = {}
    for nid, nd in N.items():
        for p in nd.get("people") or []:
            if p.get("id"): full.setdefault(p["id"], p.get("full_name") or p.get("name"))
    for pid, p in P.items(): full.setdefault(pid, p.get("name"))
    by_full = collections.defaultdict(list); by_short = collections.defaultdict(list)
    for pid, nm in full.items(): by_full[norm(nm)].append(pid)
    for pid, p in P.items(): by_short[(norm(p.get("name")), p.get("uf"))].append(pid)
    result = collections.defaultdict(dict)
    for ano in (2018, 2022):
        if not (CACHE / f"consulta_cand_{ano}.zip").exists() or not (CACHE / f"bem_candidato_{ano}.zip").exists(): print(f"{ano}: arquivos ausentes", file=sys.stderr); continue
        C = cands(ano); tot, tipos, n = bens(ano)
        urna_count = collections.Counter((norm(c["urna"]), c["uf"]) for c in C.values())
        for sq, c in C.items():
            pids = by_full.get(norm(c["nome"])) or ([] if urna_count[(norm(c["urna"]), c["uf"])] != 1 else by_short.get((norm(c["urna"]), c["uf"]), []))
            for pid in pids:
                if ano in result[pid]: continue
                top = sorted(tipos[sq].items(), key=lambda kv: -kv[1])[:4]
                result[pid][ano] = {"total": round(tot.get(sq, 0), 2), "itens": n.get(sq, 0), "cargo": c["cargo"], "uf": c["uf"], "top": [{"tipo": t, "valor": round(v, 2)} for t, v in top], "casado_por": "nome completo" if by_full.get(norm(c["nome"])) else "nome de urna único + UF"}
        print(f"{ano}: {sum(1 for r in result.values() if ano in r)} pessoas do grafo com declaração", file=sys.stderr)
    factor, ref = ipca_factor("2018-08", "2022-08")
    out = {}
    for pid, yrs in result.items():
        rec = {str(a): v for a, v in yrs.items()}
        if 2018 in yrs and 2022 in yrs and yrs[2018]["total"] > 0:
            rec["variacao_nominal_pct"] = round(100 * (yrs[2022]["total"] / yrs[2018]["total"] - 1), 1)
            if factor: rec["variacao_real_pct"] = round(100 * (yrs[2022]["total"] / (yrs[2018]["total"] * factor) - 1), 1)
        out[pid] = rec
    data = {"generated_at": datetime.date.today().isoformat(), "fonte": "TSE, bens declarados pelos candidatos (2018 e 2022)", "ipca_fator_2018_2022": round(factor, 4) if factor else None, "people": out}
    (ROOT / "data" / "generated" / "patrimonio.yaml").write_text("# GERADO por etl/patrimonio.py. Não edite à mão. Declaração feita pelo próprio candidato ao TSE.\n" + yaml.dump(data, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    both = [r for r in out.values() if "variacao_nominal_pct" in r]
    print(f"patrimônio: {len(out)} pessoas; {len(both)} com 2018 e 2022; IPCA 2018→2022 ×{factor:.3f}" if factor else f"patrimônio: {len(out)} pessoas")
    for pid, r in sorted(out.items(), key=lambda kv: -(kv[1].get("2022") or {}).get("total", 0))[:5]: print("  ", full.get(pid), r.get("2022", {}).get("total"), "| 2018:", r.get("2018", {}).get("total"), "| var real", r.get("variacao_real_pct"))
if __name__ == "__main__": main()
