#!/usr/bin/env python3
"""Gabinetes dos deputados → data/generated/gabinetes.yaml (equipe, folha estimada, custo do mandato, comparação com a mediana).

Fonte: Câmara, arquivo diário de funcionários (https://dadosabertos.camara.leg.br/arquivos/funcionarios/csv/funcionarios.csv):
nome, cargo (nível SPnn + S/C = sem/com gratificação de gabinete), lotação (gabinete) e datas. O salário de cada nível vem da
tabela oficial em data/tabela-sp-2026.yaml; a folha do gabinete é uma ESTIMATIVA (vencimento bruto × pessoas), sem encargos.
Custo do mandato no ano = subsídio × meses + cota parlamentar paga (atividade.yaml) + folha estimada × meses.
Uso: .venv/bin/python etl/gabinetes.py
"""
import csv, io, re, sys, json, pathlib, datetime, unicodedata, collections, statistics, urllib.request
import yaml
ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / "build" / "cache-gabinetes"; CACHE.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (Macintosh) atlas-da-republica/0.1"}
TODAY = datetime.date.today(); SUBSIDIO = 46366.19  # subsídio mensal de deputado federal (Decreto Legislativo 2/2023; igual ao de ministro do STF desde fev/2025)
def norm(s): return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())).strip()
def fetch(url, name, max_age_h=20):
    p = CACHE / name
    if p.exists() and (datetime.datetime.now() - datetime.datetime.fromtimestamp(p.stat().st_mtime)).total_seconds() < max_age_h * 3600: return p.read_bytes()
    print("GET", url, file=sys.stderr); data = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=600).read(); p.write_bytes(data); return data
def main():
    tab = yaml.safe_load(open(ROOT / "data" / "tabela-sp-2026.yaml", encoding="utf-8")); niveis = tab["niveis"]
    g = json.load(open(ROOT / "build" / "graph.br.json", encoding="utf-8")); P = g["people"]
    at_p = ROOT / "data" / "generated" / "atividade.yaml"; at = ((yaml.safe_load(open(at_p, encoding="utf-8")) or {}).get("people") or {}) if at_p.exists() else {}
    rows = csv.DictReader(io.StringIO(fetch("https://dadosabertos.camara.leg.br/arquivos/funcionarios/csv/funcionarios.csv", "funcionarios.csv").decode("utf-8-sig", "ignore")), delimiter=";")
    gab = collections.defaultdict(list)
    for r in rows:
        if r.get("grupo") != "Secretário Parlamentar": continue
        m = re.match(r"^\s*(SP\d{2})([SC])", r.get("cargo") or "")
        did = (r.get("uriLotacao") or "").rstrip("/").split("/")[-1] if "deputados/" in (r.get("uriLotacao") or "") else None
        if not m or not did: continue
        nivel, grg = m.group(1), m.group(2) == "C"; sal = (niveis.get(nivel) or {}).get("com_grg" if grg else "sem_grg")
        gab[did].append({"nome": r["nome"].title(), "nivel": nivel, "grg": grg, "salario": sal, "desde": (r.get("dataInicioHistorico") or r.get("dataNomeacao") or "")[:10], "lotacao": r.get("lotacao")})  # dataNomeacao repete o reenquadramento de fev/2026; o início real é dataInicioHistorico
    months = TODAY.month - 1 + TODAY.day / 30.0  # meses decorridos no ano (fração)
    people = {}
    for did, staff in gab.items():
        pid = f"br-p-cd-{did}"
        if pid not in P: continue
        staff.sort(key=lambda s: -(s["salario"] or 0))
        folha = sum(s["salario"] or 0 for s in staff); nomeados_ano = sum(1 for s in staff if s["desde"].startswith(str(TODAY.year)))
        surname = norm(P[pid]["name"]).split()[-1] if P[pid].get("name") else None
        same = [s["nome"] for s in staff if surname and len(surname) > 3 and surname in norm(s["nome"]).split()]
        cota = ((at.get(pid) or {}).get("cota") or {}).get("total") or 0
        people[pid] = {"assessores": len(staff), "folha_mensal_estimada": round(folha, 2), "com_grg": sum(1 for s in staff if s["grg"]), "nomeados_no_ano": nomeados_ano,
                       "niveis": dict(collections.Counter(s["nivel"] for s in staff).most_common(5)), "equipe": [{k: s[k] for k in ("nome", "nivel", "grg", "salario", "desde")} for s in staff],
                       "mesmo_sobrenome": same, "custo_ano": {"meses": round(months, 1), "subsidio": round(SUBSIDIO * months, 2), "cota": round(cota, 2), "gabinete_estimado": round(folha * months, 2), "total": round(SUBSIDIO * months + cota + folha * months, 2)}}
    med = lambda k, f: round(statistics.median(f(v) for v in people.values()), 2) if people else None
    medians = {"assessores": med("a", lambda v: v["assessores"]), "folha_mensal_estimada": med("f", lambda v: v["folha_mensal_estimada"]), "cota": med("c", lambda v: v["custo_ano"]["cota"]), "custo_ano_total": med("t", lambda v: v["custo_ano"]["total"]), "nomeados_no_ano": med("n", lambda v: v["nomeados_no_ano"])}
    out = {"generated_at": TODAY.isoformat(), "fonte": "Câmara dos Deputados, dados abertos (funcionários) e tabela de remuneração de secretário parlamentar (Lei 15.349/2026)", "subsidio_mensal": SUBSIDIO, "verba_gabinete_limite_mensal": 165806.07,
           "nota": "Folha do gabinete estimada pelo vencimento bruto de cada nível, sem encargos, auxílios nem 13º; a verba de gabinete real pode ser maior. Nomes de secretários parlamentares são públicos (cargos comissionados).",
           "medianas": medians, "people": people}
    (ROOT / "data" / "generated" / "gabinetes.yaml").write_text("# GERADO por etl/gabinetes.py. Não edite à mão.\n" + yaml.dump(out, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    print(f"gabinetes: {len(people)} deputados; medianas {medians}")
    top = sorted(people.items(), key=lambda kv: -kv[1]["folha_mensal_estimada"])[:3]
    for pid, v in top: print("  ", P[pid]["name"], v["assessores"], "assessores, folha", v["folha_mensal_estimada"], "| mesmo sobrenome:", v["mesmo_sobrenome"][:2])
    print("  com mesmo sobrenome:", sum(1 for v in people.values() if v["mesmo_sobrenome"]))
if __name__ == "__main__": main()
