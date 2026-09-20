#!/usr/bin/env python3
"""Votação por município dos eleitos em 2022 (deputados federais e senadores) → data/generated/votos-2022.yaml.

Fonte: TSE, "Votação nominal por município e zona" 2022 (votacao_candidato_munzona_2022.zip, baixado manualmente em
build/cache-tse/ porque o CDN do TSE bloqueia acesso automatizado). Lê os 27 CSVs direto do zip, sem extrair.
Para cada eleito: total de votos, votos por município (código e nome TSE), os 15 municípios com mais votos e a parcela deles.
Casamento com o grafo: nome de urna normalizado + UF (deputados) e nome completo (senadores).
Uso: .venv/bin/python etl/votos.py
"""
import csv, io, re, sys, zipfile, pathlib, datetime, unicodedata, collections, json
import yaml
ROOT = pathlib.Path(__file__).resolve().parent.parent
ZIP = ROOT / "build" / "cache-tse" / "votacao_candidato_munzona_2022.zip"
def norm(s): return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())).strip()
def main():
    if not ZIP.exists(): print(f"votos: {ZIP} ausente (download manual do TSE); mantendo o arquivo gerado anterior", file=sys.stderr); return
    g = json.load(open(ROOT / "build" / "graph.br.json", encoding="utf-8")); P = g["people"]; N = g["nodes"]
    by_urna = {}; by_full = {}
    for pid, p in P.items():
        pos = {q["id"] for q in p.get("positions") or []}
        if "br-deputado-federal" in pos: by_urna[(norm(p["name"]), p.get("uf"))] = pid
        if "br-senador" in pos: by_urna[(norm(p["name"]), p.get("uf"))] = pid
    for n in (N.get("br-senador") or {}).get("people") or []:
        if n.get("full_name"): by_full[norm(n["full_name"])] = n["id"]
    z = zipfile.ZipFile(ZIP)
    cand = {}  # sq -> {nome, urna, uf, partido, cargo, total, muns:{cod:(nome, votos)}}
    for name in sorted(z.namelist()):
        if not name.endswith(".csv") or name.endswith("_BR.csv"): continue
        print(name, file=sys.stderr, flush=True)
        with z.open(name) as f:
            r = csv.reader(io.TextIOWrapper(f, encoding="latin1"), delimiter=";"); head = next(r); ix = {h: i for i, h in enumerate(head)}
            i_cargo, i_sit, i_sq, i_nome, i_urna, i_uf, i_part, i_mun, i_nmun, i_v, i_turno = (ix[k] for k in ("CD_CARGO", "DS_SIT_TOT_TURNO", "SQ_CANDIDATO", "NM_CANDIDATO", "NM_URNA_CANDIDATO", "SG_UF", "SG_PARTIDO", "CD_MUNICIPIO", "NM_MUNICIPIO", "QT_VOTOS_NOMINAIS_VALIDOS", "NR_TURNO"))
            for row in r:
                if row[i_cargo] not in ("5", "6") or row[i_turno] != "1": continue
                if not row[i_sit].startswith("ELEITO"): continue
                c = cand.setdefault(row[i_sq], {"nome": row[i_nome], "urna": row[i_urna], "uf": row[i_uf], "partido": row[i_part], "cargo": "senador" if row[i_cargo] == "5" else "deputado", "total": 0, "muns": {}})
                v = int(row[i_v] or 0); c["total"] += v
                m = c["muns"].setdefault(row[i_mun], [row[i_nmun].title(), 0]); m[1] += v
    out = {}; matched = 0
    for sq, c in cand.items():
        pid = by_urna.get((norm(c["urna"]), c["uf"])) or by_full.get(norm(c["nome"]))
        if not pid: continue
        matched += 1
        top = sorted(c["muns"].items(), key=lambda kv: -kv[1][1])[:15]
        top_share = sum(v for _, (_, v) in top) / c["total"] if c["total"] else 0
        out[pid] = {"nome": c["nome"], "urna": c["urna"], "uf": c["uf"], "partido": c["partido"], "cargo": c["cargo"], "votos": c["total"], "municipios": len(c["muns"]),
                    "top": [{"tse": cod, "nome": nm, "uf": c["uf"], "votos": v, "pct": round(100 * v / c["total"], 1)} for cod, (nm, v) in top], "top15_pct": round(100 * top_share, 1)}
    (ROOT / "data" / "generated" / "votos-2022.yaml").write_text("# GERADO por etl/votos.py a partir do TSE (votacao_candidato_munzona_2022). Não edite à mão.\n" + yaml.dump({"generated_at": datetime.date.today().isoformat(), "eleicao": 2022, "people": out}, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    print(f"eleitos em 2022: {len(cand)}; casados com o grafo: {matched}")
if __name__ == "__main__": main()
