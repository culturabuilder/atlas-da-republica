#!/usr/bin/env python3
"""Remuneração acima do teto no Executivo federal → data/generated/teto.yaml.

Fonte: Portal da Transparência, download mensal "Servidores civis (SIAPE)": Cadastro (órgão de exercício, cargo) e Remuneração
(remuneração básica bruta, abate-teto, verbas indenizatórias, remuneração após deduções). Teto: subsídio de ministro do STF,
R$ 46.366,19 (Lei 14.520/2023, 4ª parcela a partir de fev/2025). Agregado por órgão: quantos servidores tiveram abate-teto (bruto acima do
teto), quanto foi abatido, e quanto foi pago fora do teto em verbas indenizatórias. Só agregados por órgão; nada individual.
Uso: .venv/bin/python etl/teto.py [--mes AAAAMM]   (padrão: dois meses atrás, o último publicado)
"""
import csv, io, sys, zipfile, pathlib, datetime, argparse, urllib.request, collections, re, unicodedata, json
import yaml
ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / "build" / "cache-teto"; CACHE.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (Macintosh) atlas-da-republica/0.1"}
TETO = 46366.19
def money(s): return float((s or "0").replace(".", "").replace(",", ".") or 0)
def norm(s): return re.sub(r"[^a-z0-9]+", " ", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()).strip()
def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--mes"); a = ap.parse_args()
    t = datetime.date.today(); m = a.mes or f"{(t.replace(day=1) - datetime.timedelta(days=45)).strftime('%Y%m')}"
    p = CACHE / f"{m}_Servidores_SIAPE.zip"
    if not p.exists():
        url = f"https://dadosabertos-download.cgu.gov.br/PortalDaTransparencia/saida/servidores/{m}_Servidores_SIAPE.zip"; print("GET", url, file=sys.stderr)
        p.write_bytes(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=1800).read())
    z = zipfile.ZipFile(p)
    cad = [n for n in z.namelist() if n.endswith("Cadastro.csv")][0]; rem = [n for n in z.namelist() if n.endswith("Remuneracao.csv")][0]
    org_of = {}; cargo_of = {}
    with z.open(cad) as f:
        r = csv.reader(io.TextIOWrapper(f, encoding="latin1"), delimiter=";"); head = next(r)
        ix = {h: i for i, h in enumerate(head)}
        i_id, i_org, i_cargo = ix["Id_SERVIDOR_PORTAL"], ix.get("ORG_EXERCICIO", ix.get("ORGSUP_EXERCICIO")), ix.get("DESCRICAO_CARGO")
        i_sup = ix.get("ORGSUP_EXERCICIO")
        for row in r:
            try: org_of[row[i_id]] = (row[i_org], row[i_sup] if i_sup is not None else row[i_org]); cargo_of[row[i_id]] = row[i_cargo] if i_cargo is not None else ""
            except IndexError: continue
    agg = collections.defaultdict(lambda: {"servidores": 0, "abate": 0, "abatido": 0.0, "indenizatorias": 0.0, "acima_com_indenizatorias": 0, "cargos": collections.Counter()})
    sup_of = {}
    n = 0
    with z.open(rem) as f:
        r = csv.reader(io.TextIOWrapper(f, encoding="latin1"), delimiter=";"); head = next(r); ix = {h: i for i, h in enumerate(head)}
        i_id = ix["Id_SERVIDOR_PORTAL"]; i_bruta = ix["REMUNERAÇÃO BÁSICA BRUTA (R$)"]; i_abate = ix["ABATE-TETO (R$)"]; i_ind = next((i for h, i in ix.items() if h.startswith("VERBAS INDENIZATÓRIAS REGISTRADAS EM SISTEMAS DE PESSOAL - CIVIL (R$)")), None)
        i_apos = ix["REMUNERAÇÃO APÓS DEDUÇÕES OBRIGATÓRIAS (R$)"]
        for row in r:
            sid = row[i_id]; org, sup = org_of.get(sid, ("(sem cadastro)", "(sem cadastro)")); sup_of[org] = sup
            g = agg[org]; g["servidores"] += 1; n += 1
            abate = -money(row[i_abate]) if money(row[i_abate]) < 0 else money(row[i_abate]); bruta = money(row[i_bruta]); ind = money(row[i_ind]) if i_ind is not None else 0.0
            if abate > 0 or bruta > TETO: g["abate"] += 1; g["abatido"] += abate; g["cargos"][cargo_of.get(sid, "")] += 1
            g["indenizatorias"] += ind
            if money(row[i_apos]) + ind > TETO: g["acima_com_indenizatorias"] += 1
    graph = json.load(open(ROOT / "build" / "graph.br.json", encoding="utf-8")); N = graph["nodes"]
    by_key = {}
    for nd in N.values():
        if nd["type"] == "dept_head": continue
        for k in [nd["name"]] + list(nd.get("aliases") or []): by_key.setdefault(norm(k), nd["id"])
    orgs = []
    for org, g in agg.items():
        if g["servidores"] < 50: continue
        nid = by_key.get(norm(org)) or by_key.get(norm(re.sub(r"^(MINISTERIO|MINIST\.) ", "Ministério ", org)))
        orgs.append({"orgao": org, "orgao_superior": sup_of.get(org), "node": nid, "servidores": g["servidores"], "com_abate_teto": g["abate"], "pct_com_abate": round(100 * g["abate"] / g["servidores"], 2), "valor_abatido": round(g["abatido"], 2),
                     "indenizatorias": round(g["indenizatorias"], 2), "acima_do_teto_com_indenizatorias": g["acima_com_indenizatorias"], "cargos_mais_comuns": [{"cargo": c or "(não informado)", "n": v} for c, v in g["cargos"].most_common(3)]})
    orgs.sort(key=lambda o: -o["com_abate_teto"])
    tot_abate = sum(o["com_abate_teto"] for o in orgs); tot_abatido = sum(o["valor_abatido"] for o in orgs); tot_ind = sum(o["indenizatorias"] for o in orgs); tot_acima = sum(o["acima_do_teto_com_indenizatorias"] for o in orgs)
    out = {"generated_at": t.isoformat(), "mes": m, "teto": TETO, "teto_fonte": "Lei 14.520/2023 (subsídio de ministro do STF, 4ª parcela a partir de fev/2025)", "servidores": n, "com_abate_teto": tot_abate, "valor_abatido_mes": round(tot_abatido, 2),
           "indenizatorias_mes": round(tot_ind, 2), "acima_do_teto_com_indenizatorias": tot_acima, "orgaos": orgs[:40],
           "nota": "Abrange servidores civis do Poder Executivo federal no SIAPE (não inclui militares, Judiciário, Legislativo, MPU nem estatais). 'Abate-teto' é o corte aplicado para respeitar o teto; verbas indenizatórias ficam fora do teto por lei."}
    (ROOT / "data" / "generated" / "teto.yaml").write_text("# GERADO por etl/teto.py. Não edite à mão.\n" + yaml.dump(out, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    print(f"{m}: {n} servidores; {tot_abate} com abate-teto (R$ {tot_abatido/1e6:.1f} mi abatidos no mês); R$ {tot_ind/1e6:.1f} mi em indenizatórias; {tot_acima} acima do teto contando indenizatórias")
    for o in orgs[:8]: print("  ", o["orgao"][:50], o["com_abate_teto"], f"({o['pct_com_abate']}%)", "→", o["node"])
if __name__ == "__main__": main()
