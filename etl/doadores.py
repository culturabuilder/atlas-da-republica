#!/usr/bin/env python3
"""Receitas de campanha de 2022 dos parlamentares e ocupantes → data/generated/doadores-2022.yaml.

Fonte: TSE, prestação de contas eleitorais 2022 (receitas_candidatos_2022_BRASIL.csv dentro do zip em build/cache-tse/),
mais consulta_cand_2022 para casar SQ_CANDIDATO com as pessoas do grafo (nome completo idêntico ou nome de urna único + UF).
Por pessoa: receita total, por origem (fundo eleitoral, fundo partidário, pessoas físicas, recursos próprios, outros candidatos/partidos)
e maiores doadores. Nomes de doadores só aparecem quando são partidos, fundos, candidatos ou pessoas físicas com R$ 50 mil ou mais;
CPF nunca é lido para a saída.
Uso: .venv/bin/python etl/doadores.py
"""
import csv, io, re, sys, json, zipfile, pathlib, datetime, unicodedata, collections
import yaml
ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / "build" / "cache-tse"; LIMIAR_PF = 50000.0
def norm(s): return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())).strip()
def money(s): return float(str(s or "0").replace(".", "").replace(",", ".") or 0)
def main():
    zp = CACHE / "prestacao_de_contas_eleitorais_candidatos_2022.zip"; cp = CACHE / "consulta_cand_2022.zip"
    if not zp.exists() or not cp.exists(): print("doadores: zips do TSE ausentes; mantendo o gerado anterior", file=sys.stderr); return
    g = json.load(open(ROOT / "build" / "graph.br.json", encoding="utf-8")); P = g["people"]; N = g["nodes"]
    full = {}
    for nd in N.values():
        for p in nd.get("people") or []:
            if p.get("id"): full.setdefault(p["id"], p.get("full_name") or p.get("name"))
    for pid, p in P.items(): full.setdefault(pid, p.get("name"))
    by_full = collections.defaultdict(list); by_short = collections.defaultdict(list)
    for pid, nm in full.items(): by_full[norm(nm)].append(pid)
    for pid, p in P.items(): by_short[(norm(p.get("name")), p.get("uf"))].append(pid)
    z = zipfile.ZipFile(cp); C = {}
    for name in z.namelist():
        if not name.endswith(".csv") or re.search(r"_(BR|BRASIL)\.csv$", name): continue
        with z.open(name) as f:
            for row in csv.DictReader(io.TextIOWrapper(f, encoding="latin1"), delimiter=";"):
                if row.get("NR_TURNO") == "1": C[row["SQ_CANDIDATO"]] = (norm(row["NM_CANDIDATO"]), norm(row["NM_URNA_CANDIDATO"]), row["SG_UF"])
    uc = collections.Counter((u, uf) for _, u, uf in C.values())
    sq2pid = {}
    for sq, (nm, u, uf) in C.items():
        pids = by_full.get(nm) or ([] if uc[(u, uf)] != 1 else by_short.get((u, uf), []))
        if pids: sq2pid[sq] = pids
    tot = collections.defaultdict(float); orig = collections.defaultdict(lambda: collections.defaultdict(float)); don = collections.defaultdict(lambda: collections.defaultdict(float)); dtype = {}
    zr = zipfile.ZipFile(zp); name = [n for n in zr.namelist() if n.endswith("receitas_candidatos_2022_BRASIL.csv")][0]
    with zr.open(name) as f:
        r = csv.reader(io.TextIOWrapper(f, encoding="latin1"), delimiter=";"); head = next(r); ix = {h: i for i, h in enumerate(head)}
        i_sq, i_or, i_nm, i_rfb, i_v, i_nat = ix["SQ_CANDIDATO"], ix["DS_ORIGEM_RECEITA"], ix["NM_DOADOR"], ix["NM_DOADOR_RFB"], ix["VR_RECEITA"], ix["DS_NATUREZA_RECEITA"]
        for row in r:
            sq = row[i_sq]
            if sq not in sq2pid: continue
            v = money(row[i_v]); o = row[i_or]; nm = (row[i_rfb] if row[i_rfb] not in ("#NULO", "#NULO#", "") else row[i_nm]).title()
            for pid in sq2pid[sq]:
                tot[pid] += v; orig[pid][o] += v
                key = (nm, o); don[pid][key] += v
    out = {}
    for pid, t in tot.items():
        top = []
        for (nm, o), v in sorted(don[pid].items(), key=lambda kv: -kv[1]):
            pf = "física" in o.lower()
            if pf and v < LIMIAR_PF: continue
            top.append({"doador": nm, "origem": o.title(), "valor": round(v, 2), "pct": round(100 * v / t, 1) if t else None})
            if len(top) >= 8: break
        out[pid] = {"total": round(t, 2), "origens": {k.title(): round(v, 2) for k, v in sorted(orig[pid].items(), key=lambda kv: -kv[1])}, "maiores": top, "doadores_pf_pequenos_omitidos": True}
    data = {"generated_at": datetime.date.today().isoformat(), "eleicao": 2022, "fonte": "TSE, prestação de contas eleitorais 2022 (receitas dos candidatos)", "limiar_pf": LIMIAR_PF, "people": out}
    (ROOT / "data" / "generated" / "doadores-2022.yaml").write_text("# GERADO por etl/doadores.py. Não edite à mão. Doadores pessoa física abaixo de R$ 50 mil não são nomeados.\n" + yaml.dump(data, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    print(f"doadores 2022: {len(out)} pessoas do grafo com receitas")
    for pid, v in sorted(out.items(), key=lambda kv: -kv[1]["total"])[:3]: print("  ", full.get(pid), round(v["total"]/1e6, 2), "mi |", list(v["origens"].items())[:2], "|", v["maiores"][:1])
if __name__ == "__main__": main()
