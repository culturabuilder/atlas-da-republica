#!/usr/bin/env python3
"""Remuneração mensal dos ocupantes de cargos do Executivo federal → data/generated/remuneracao.yaml.

Fonte: Portal da Transparência, download mensal "Servidores civis (SIAPE)" (mesmo arquivo usado por etl/teto.py):
Cadastro (nome, cargo, função, órgão) e Remuneração (bruta, abate-teto, indenizatórias, líquida). Casamento com o grafo por
nome completo idêntico (normalizado) dos ocupantes de cargos do setor executivo; homônimos com mais de um registro são descartados.
Uso: .venv/bin/python etl/remuneracao.py [--mes AAAAMM]
"""
import csv, io, sys, zipfile, pathlib, datetime, argparse, re, unicodedata, json, collections
import yaml
ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / "build" / "cache-teto"
def money(s): return float((s or "0").replace(".", "").replace(",", ".") or 0)
def norm(s): return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())).strip()
def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--mes"); a = ap.parse_args()
    t = datetime.date.today(); m = a.mes or (t.replace(day=1) - datetime.timedelta(days=45)).strftime("%Y%m")
    p = CACHE / f"{m}_Servidores_SIAPE.zip"
    if not p.exists(): print(f"remuneração: {p.name} ausente (etl/teto.py baixa); pulando", file=sys.stderr); return
    g = json.load(open(ROOT / "build" / "graph.br.json", encoding="utf-8")); N = g["nodes"]
    want = {}
    for n in N.values():
        if n["type"] != "dept_head" or n.get("sector") != "executivo": continue
        for h in n.get("people") or []:
            if h.get("id") and h.get("name"): want.setdefault(norm(h.get("full_name") or h["name"]), []).append((h["id"], n["id"], n["name"]))
    z = zipfile.ZipFile(p); cad = [x for x in z.namelist() if x.endswith("Cadastro.csv")][0]; rem = [x for x in z.namelist() if x.endswith("Remuneracao.csv")][0]
    ids = collections.defaultdict(list)
    with z.open(cad) as f:
        r = csv.reader(io.TextIOWrapper(f, encoding="latin1"), delimiter=";"); head = next(r); ix = {h: i for i, h in enumerate(head)}
        for row in r:
            try: k = norm(row[ix["NOME"]])
            except IndexError: continue
            if k in want: ids[k].append({"id": row[ix["Id_SERVIDOR_PORTAL"]], "cargo": row[ix.get("DESCRICAO_CARGO", 0)], "funcao": row[ix.get("FUNCAO", 0)] if "FUNCAO" in ix else "", "orgao": row[ix.get("ORG_EXERCICIO", 0)] if "ORG_EXERCICIO" in ix else "", "vinculo": row[ix.get("TIPO_VINCULO", 0)] if "TIPO_VINCULO" in ix else ""})
    by_id = {}
    for k, lst in ids.items():
        if len({x["id"] for x in lst}) == 1: by_id[lst[0]["id"]] = (k, lst[0])
    out = {}
    with z.open(rem) as f:
        r = csv.reader(io.TextIOWrapper(f, encoding="latin1"), delimiter=";"); head = next(r); ix = {h: i for i, h in enumerate(head)}
        i_ind = next((i for h, i in ix.items() if h.startswith("VERBAS INDENIZATÓRIAS REGISTRADAS EM SISTEMAS DE PESSOAL - CIVIL (R$)")), None)
        for row in r:
            sid = row[ix["Id_SERVIDOR_PORTAL"]]
            if sid not in by_id: continue
            k, cad_ = by_id[sid]
            rec = {"mes": m, "bruta": money(row[ix["REMUNERAÇÃO BÁSICA BRUTA (R$)"]]), "abate_teto": money(row[ix["ABATE-TETO (R$)"]]), "gratificacao_natalina": money(row[ix["GRATIFICAÇÃO NATALINA (R$)"]]), "ferias": money(row[ix["FÉRIAS (R$)"]]), "eventuais": money(row[ix["OUTRAS REMUNERAÇÕES EVENTUAIS (R$)"]]),
                   "liquida": money(row[ix["REMUNERAÇÃO APÓS DEDUÇÕES OBRIGATÓRIAS (R$)"]]), "indenizatorias": money(row[i_ind]) if i_ind is not None else 0.0, "cargo": cad_["cargo"], "funcao": cad_["funcao"], "orgao": cad_["orgao"], "vinculo": cad_["vinculo"]}
            for pid, nid, nname in want[k]:
                cur = out.get(pid)
                if cur: cur["bruta"] += rec["bruta"]; cur["liquida"] += rec["liquida"]; cur["indenizatorias"] += rec["indenizatorias"]; cur["eventuais"] += rec["eventuais"]
                else: out[pid] = dict(rec, position=nid, position_name=nname)
    for v in out.values():
        for k in ("bruta", "abate_teto", "gratificacao_natalina", "ferias", "eventuais", "liquida", "indenizatorias"): v[k] = round(v[k], 2)
    data = {"generated_at": t.isoformat(), "mes": m, "fonte": "Portal da Transparência, remuneração de servidores civis (SIAPE)", "people": out,
            "nota": "Remuneração do mês publicada pelo Portal da Transparência; a folha sai com cerca de dois meses de atraso. Ministros de Estado recebem subsídio; verbas indenizatórias ficam fora do teto por lei."}
    (ROOT / "data" / "generated" / "remuneracao.yaml").write_text("# GERADO por etl/remuneracao.py. Não edite à mão.\n" + yaml.dump(data, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    print(f"remuneração {m}: {len(out)} ocupantes encontrados na folha de {len(want)} nomes")
    for pid, v in list(out.items())[:5]: print("  ", pid, v["position_name"][:40], "bruta", v["bruta"], "líquida", v["liquida"], "|", v["cargo"][:30])
if __name__ == "__main__": main()
