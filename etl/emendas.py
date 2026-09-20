#!/usr/bin/env python3
"""Emendas parlamentares → data/generated/emendas.yaml.

Fonte: Portal da Transparência, download "Emendas parlamentares" (CSV único, todos os anos desde 2014), atualizado diariamente.
Cruzamentos: autor × ano (empenhado, pago), autor × município (concentração), salto em ano eleitoral (2022 vs 2021, 2026 vs 2025 no
mesmo período), municípios por habitante (IBGE, população estimada por município, SIDRA 6579).
O autor é casado com deputados e senadores do grafo por nome parlamentar normalizado (nomes das APIs da Câmara e do Senado).
Uso: .venv/bin/python etl/emendas.py
"""
import csv, io, json, re, sys, zipfile, pathlib, datetime, unicodedata, urllib.request, collections
import yaml
ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / "build" / "cache-emendas"; CACHE.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (Macintosh) atlas-da-republica/0.1"}
TODAY = datetime.date.today(); Y = TODAY.year
def norm(s): return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())).strip()
def money(s): return float((s or "0").replace(".", "").replace(",", ".") or 0)
def fetch(url, name, max_age_h=20):
    p = CACHE / name
    if p.exists() and (datetime.datetime.now() - datetime.datetime.fromtimestamp(p.stat().st_mtime)).total_seconds() < max_age_h * 3600: return p.read_bytes()
    print("GET", url, file=sys.stderr); data = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=900).read(); p.write_bytes(data); return data
def populacao():
    try:
        d = json.load(urllib.request.urlopen(urllib.request.Request("https://apisidra.ibge.gov.br/values/t/6579/n6/all/v/9324/p/last%201?formato=json", headers=UA), timeout=300))
        return {r["D1C"]: int(float(r["V"])) for r in d[1:] if r.get("V") not in (None, "...", "-")}
    except Exception as e: print("população falhou", e, file=sys.stderr); return {}
def main():
    g = json.load(open(ROOT / "build" / "graph.br.json", encoding="utf-8")); P = g["people"]
    parl = {}
    for pid, p in P.items():
        if any(q["id"] in ("br-deputado-federal", "br-senador") for q in p.get("positions") or []): parl.setdefault(norm(p["name"]), pid)
    z = zipfile.ZipFile(io.BytesIO(fetch("https://dadosabertos-download.cgu.gov.br/PortalDaTransparencia/saida/emendas-parlamentares/EmendasParlamentares.zip", "emendas.zip")))
    name = [n for n in z.namelist() if n.endswith("EmendasParlamentares.csv")][0]
    by_author_year = collections.defaultdict(lambda: collections.defaultdict(lambda: [0.0, 0.0]))  # empenhado, pago
    by_author_mun = collections.defaultdict(lambda: collections.defaultdict(float)); by_mun_year = collections.defaultdict(lambda: collections.defaultdict(float))
    # votos por município (TSE 2022) para cruzar com as emendas por município: casamento por nome normalizado + UF
    vt_p = ROOT / "data" / "generated" / "votos-2022.yaml"
    votos = (yaml.safe_load(open(vt_p, encoding="utf-8")) or {}).get("people") or {} if vt_p.exists() else {}
    UFS = {"ACRE":"AC","ALAGOAS":"AL","AMAZONAS":"AM","AMAPÁ":"AP","BAHIA":"BA","CEARÁ":"CE","DISTRITO FEDERAL":"DF","ESPÍRITO SANTO":"ES","GOIÁS":"GO","MARANHÃO":"MA","MINAS GERAIS":"MG","MATO GROSSO DO SUL":"MS","MATO GROSSO":"MT","PARÁ":"PA","PARAÍBA":"PB","PERNAMBUCO":"PE","PIAUÍ":"PI","PARANÁ":"PR","RIO DE JANEIRO":"RJ","RIO GRANDE DO NORTE":"RN","RONDÔNIA":"RO","RORAIMA":"RR","RIO GRANDE DO SUL":"RS","SANTA CATARINA":"SC","SERGIPE":"SE","SÃO PAULO":"SP","TOCANTINS":"TO"}
    mun_uf = {}  # código IBGE -> (nome normalizado, UF)
    by_year = collections.defaultdict(lambda: [0.0, 0.0]); by_type_year = collections.defaultdict(lambda: collections.defaultdict(float)); names = {}; mun_names = {}
    with z.open(name) as f:
        for r in csv.DictReader(io.TextIOWrapper(f, encoding="latin1"), delimiter=";"):
            ano = int(r["Ano da Emenda"]); emp = money(r["Valor Empenhado"]); pago = money(r["Valor Pago"]); a = r["Nome do Autor da Emenda"]; t = r["Tipo de Emenda"]
            by_year[ano][0] += emp; by_year[ano][1] += pago; by_type_year[ano][t] += emp
            if a and a != "Sem informação":
                k = norm(a); names[k] = a; by_author_year[k][ano][0] += emp; by_author_year[k][ano][1] += pago
                cod = r["Código Município IBGE"]
                if cod and cod not in ("S/I", "") and r["Município"]:
                    mun_names[cod] = f"{r['Município'].title()} ({r['UF'][:2] if len(r['UF'])==2 else r['UF'].title()})" if r["UF"] else r["Município"].title()
                    mun_uf[cod] = (norm(r["Município"]), r["UF"] if len(r["UF"]) == 2 else UFS.get(r["UF"].upper(), r["UF"]))
                    if ano >= Y - 3: by_author_mun[k][cod] += emp
                    by_mun_year[cod][ano] += emp
    # pagamentos por ano/mês (arquivo por favorecido): permite comparar o mesmo período de anos diferentes
    fav = [n for n in z.namelist() if n.endswith("PorFavorecido.csv")]
    by_ym = collections.defaultdict(float); fav_mun = collections.defaultdict(lambda: collections.defaultdict(float)); fav_names = {}; fav_pj = collections.defaultdict(lambda: collections.defaultdict(float))
    if fav:
        with z.open(fav[0]) as f:
            for r in csv.DictReader(io.TextIOWrapper(f, encoding="latin1"), delimiter=";"):
                ym = r.get("Ano/Mês") or ""; v = money(r.get("Valor Recebido"))
                if len(ym) == 6: by_ym[ym] += v
                a = r.get("Nome do Autor da Emenda") or ""; mun = (r.get("Município Favorecido") or "").strip(); uf = (r.get("UF Favorecido") or "").strip()
                if len(ym) == 6 and int(ym[:4]) >= Y - 3 and a and mun and uf and len(uf) == 2 and v > 0:
                    key = (norm(mun), uf); fav_mun[norm(a)][key] += v; fav_names[key] = f"{mun.title()} ({uf})"
                if len(ym) == 6 and int(ym[:4]) >= Y - 3 and a and v > 0 and (r.get("Tipo Favorecido") or "") == "Pessoa Jurídica":
                    fav_pj[norm(a)][(r.get("Favorecido") or "").title()] += v
    last_ym = max(by_ym) if by_ym else None; last_m = int(last_ym[4:6]) if last_ym else 12
    def ytd(y): return sum(v for k, v in by_ym.items() if k.startswith(str(y)) and int(k[4:6]) <= last_m)
    pagos_ytd = {str(y): round(ytd(y), 2) for y in range(2018, Y + 1)}
    pop = populacao()
    people = {}; unmatched = 0
    for k, yrs in by_author_year.items():
        pid = parl.get(k)
        if not pid: unmatched += 1; continue
        muns = dict(fav_mun.get(k, {}))
        # pagamentos a favorecidos sediados em Brasília (órgãos federais, fundos) não são "destino local" para quem não é do DF
        if (P.get(pid) or {}).get("uf") not in (None, "DF"): muns.pop(("brasilia", "DF"), None)
        tot = sum(muns.values()) or 1
        top = sorted(muns.items(), key=lambda kv: -kv[1])[:5]
        people[pid] = {"autor": names[k], "anos": {str(y): {"empenhado": round(v[0], 2), "pago": round(v[1], 2)} for y, v in sorted(yrs.items()) if y >= 2019},
                       "top_municipios": [{"nome": fav_names.get(c, c[0]), "valor": round(v, 2), "pct": round(100 * v / tot, 1)} for c, v in top],
                       "concentracao_top5_pct": round(100 * sum(v for _, v in top) / tot, 1), "municipios": len(muns), "desde": Y - 3, "base": "pagamentos a favorecidos por município"}
        pj = sorted(fav_pj.get(k, {}).items(), key=lambda kv: -kv[1])[:40]
        people[pid]["favorecidos_pj"] = [{"nome": n_, "valor": round(v_, 2)} for n_, v_ in pj]
        vt = votos.get(pid)
        if vt and muns:
            vkeys = {(norm(m["nome"]), m["uf"]) for m in vt["top"]}
            em_top = sum(v for c, v in muns.items() if c in vkeys); em_com_mun = sum(muns.values())
            people[pid]["votos_2022"] = {"votos": vt["votos"], "top15_votos_pct": vt["top15_pct"], "emendas_com_municipio": round(em_com_mun, 2), "emendas_nos_top15_pct": round(100 * em_top / em_com_mun, 1) if em_com_mun else None,
                                        "top15": [m["nome"] + " (" + str(m["pct"]) + "%)" for m in vt["top"][:5]]}
    # ano eleitoral: 2022 vs 2021 (ano cheio) e ano corrente vs anterior
    def ratio(a, b): return round(a / b, 2) if b else None
    eleitoral = {"empenhado_2022_vs_2021": ratio(by_year[2022][0], by_year[2021][0]), "empenhado_2018_vs_2017": ratio(by_year[2018][0], by_year[2017][0]),
                 f"pago_ate_mes_{last_m}_{Y}_vs_{Y-1}": ratio(ytd(Y), ytd(Y - 1)), f"pago_ate_mes_{last_m}_2022_vs_2021": ratio(ytd(2022), ytd(2021)), "pagos_ate_mesmo_mes": pagos_ytd, "ultimo_mes": last_ym}
    top_now = sorted(((k, v[Y][0]) for k, v in by_author_year.items() if Y in v and parl.get(k)), key=lambda kv: -kv[1])[:15]
    top_coletivos = sorted(((k, v[Y][0]) for k, v in by_author_year.items() if Y in v and not parl.get(k)), key=lambda kv: -kv[1])[:10]
    top_mun = sorted(((c, v.get(Y, 0)) for c, v in by_mun_year.items() if pop.get(c)), key=lambda kv: -(kv[1] / max(pop.get(kv[0], 1), 1)))[:15]
    cross = [p["votos_2022"] for p in people.values() if p.get("votos_2022") and p["votos_2022"].get("emendas_nos_top15_pct") is not None and p["votos_2022"]["emendas_com_municipio"] >= 1e6]
    import statistics
    voto_emenda = {"parlamentares": len(cross), "mediana_emendas_nos_top15_pct": round(statistics.median(x["emendas_nos_top15_pct"] for x in cross), 1) if cross else None,
                   "mediana_votos_top15_pct": round(statistics.median(x["top15_votos_pct"] for x in cross), 1) if cross else None, "acima_de_50_pct": sum(1 for x in cross if x["emendas_nos_top15_pct"] >= 50)}
    out = {"generated_at": TODAY.isoformat(), "year": Y, "voto_emenda": voto_emenda, "por_ano": {str(y): {"empenhado": round(v[0], 2), "pago": round(v[1], 2)} for y, v in sorted(by_year.items())},
           "por_tipo_ano": {str(y): {t: round(v, 2) for t, v in sorted(d.items(), key=lambda kv: -kv[1])} for y, d in sorted(by_type_year.items()) if y >= Y - 2},
           "ano_eleitoral": eleitoral, "autores_top": [{"autor": names[k], "person_id": parl.get(k), "empenhado": round(v, 2)} for k, v in top_now], "coletivos_top": [{"autor": names[k], "empenhado": round(v, 2)} for k, v in top_coletivos],
           "municipios_por_habitante_top": [{"codigo": c, "nome": mun_names.get(c, c), "empenhado": round(v, 2), "populacao": pop.get(c), "por_habitante": round(v / pop[c], 2)} for c, v in top_mun],
           "people": people, "autores_sem_pessoa": unmatched}
    (ROOT / "data" / "generated" / "emendas.yaml").write_text("# GERADO por etl/emendas.py. Não edite à mão.\n" + yaml.dump(out, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    print(f"emendas: {len(people)} parlamentares casados, {unmatched} autores sem pessoa no grafo; {Y}: R$ {by_year[Y][0]/1e9:.1f} bi empenhados; eleitoral {eleitoral}")
    for a in out["autores_top"][:5]: print("  ", a["autor"], round(a["empenhado"]/1e6, 1), "mi", a["person_id"])
    for m in out["municipios_por_habitante_top"][:5]: print("  ", m["nome"], m["populacao"], "hab · R$", m["por_habitante"], "/hab")
if __name__ == "__main__": main()
