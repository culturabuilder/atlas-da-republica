#!/usr/bin/env python3
"""Gabinetes dos senadores → data/generated/gabinetes-senado.yaml (equipe, folha real do último mês, cotas, benefícios, custo do mandato).

Fonte: Senado, API administrativa de dados abertos (adm.senado.gov.br/adm-dadosabertos):
  /senadores/{cod}/recursos-utilizados  (cotas por tipo, gastos não inclusos, auxílio-moradia, imóvel funcional, pessoal por local)
  /servidores                            (servidores com hierarquia; gabinetes aparecem como "GSxxxx - GABINETE DO SENADOR ...")
  /servidores/remuneracoes/{ano}/{mes}/csv (folha mensal por nome: remuneração básica + função comissionada)
Custo do mandato no ano = subsídio × meses + cotas + gastos não inclusos + folha do gabinete × meses.
Uso: .venv/bin/python etl/gabinetes_senado.py
"""
import csv, io, re, sys, json, pathlib, datetime, unicodedata, collections, statistics, time, urllib.request
import yaml
ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / "build" / "cache-gabinetes"; CACHE.mkdir(parents=True, exist_ok=True)
B = "https://adm.senado.gov.br/adm-dadosabertos/api/v1"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh) atlas-da-republica/0.1", "Accept": "application/json"}
TODAY = datetime.date.today(); SUBSIDIO = 46366.19
def norm(s): return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())).strip()
def money(s): return float(str(s or "0").replace(".", "").replace(",", ".") or 0)
def get(url, name=None, max_age_h=20, text=False):
    p = CACHE / name if name else None
    if p and p.exists() and (datetime.datetime.now() - datetime.datetime.fromtimestamp(p.stat().st_mtime)).total_seconds() < max_age_h * 3600: return p.read_text(encoding="utf-8") if text else json.loads(p.read_text(encoding="utf-8"))
    for i in range(3):
        try:
            data = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120).read().decode("utf-8", "ignore"); break
        except Exception as e:
            if i == 2: print("falha", url, e, file=sys.stderr); return None
            time.sleep(2)
    if p: p.write_text(data, encoding="utf-8")
    return data if text else json.loads(data)
def main():
    g = json.load(open(ROOT / "build" / "graph.br.json", encoding="utf-8")); P = g["people"]; N = g["nodes"]
    sens = {p["id"]: p for p in (N.get("br-senador") or {}).get("people") or []}
    # servidores por gabinete
    serv = (get(f"{B}/servidores", "sen_servidores.json") or {}).get("data") or []
    by_gab = collections.defaultdict(list)
    for s in serv:
        h = next((x["nome"] for x in (s.get("hierarquiaCompleta") or []) if re.search(r"GABINETE D[OA] SENADORA? ", x.get("nome", ""), re.I)), None)
        if not h: continue
        nm = re.sub(r"^.*GABINETE D[OA] SENADORA? ", "", h, flags=re.I).strip()
        d = s.get("dataAdmissao") or ""; adm = f"{d[6:10]}-{d[3:5]}-{d[0:2]}" if re.match(r"\d{2}/\d{2}/\d{4}", d) else None
        by_gab[norm(nm)].append({"nome": (s.get("nome") or "").title(), "funcao": (s.get("funcao") or s.get("cargo") or "").title(), "vinculo": (s.get("tipoVinculo") or "").title(), "desde": adm})
    # folha do último mês disponível
    pay = {}; mes_ref = None
    for back in range(1, 5):
        d = (TODAY.replace(day=1) - datetime.timedelta(days=1)); 
        for _ in range(back - 1): d = (d.replace(day=1) - datetime.timedelta(days=1))
        txt = get(f"{B}/servidores/remuneracoes/{d.year}/{d.month}/csv", f"sen_rem_{d.year}{d.month:02d}.csv", text=True)
        if txt and txt.count("\n") > 100:
            for r in csv.DictReader(io.StringIO(txt), delimiter=";"):
                pay[norm(r["NOME"])] = pay.get(norm(r["NOME"]), 0) + money(r.get("REMUNERAÇÃO BÁSICA")) + money(r.get("FUNÇÃO COMISSIONADA")) + money(r.get("VANTAGENS PESSOAIS"))
            mes_ref = f"{d.year}-{d.month:02d}"; break
    months = TODAY.month - 1 + TODAY.day / 30.0
    people = {}
    for pid, p in sens.items():
        cod = pid.split("-")[-1]
        ru = (get(f"{B}/senadores/{cod}/recursos-utilizados", f"sen_ru_{cod}.json") or {}).get("data") or []
        time.sleep(0.2)
        ru = next((x for x in ru if x.get("ano") == TODAY.year), ru[0] if ru else None)
        if not ru: continue
        cotas = ((ru.get("cotas") or {}).get("despesas") or []); cot_total = (ru.get("cotas") or {}).get("totalValor") or 0
        nao = ((ru.get("gastosNaoInclusos") or {}).get("despesas") or []); nao_total = (ru.get("gastosNaoInclusos") or {}).get("totalValor") or 0
        ben = {b.get("beneficio"): b.get("utilizacao") for b in ru.get("beneficios") or []}
        pes = {x.get("local"): x.get("quantidade") for x in ru.get("pessoal") or []}
        staff = by_gab.get(norm(p["name"]), []) or by_gab.get(norm(p.get("full_name") or ""), [])
        for s in staff: s["salario"] = round(pay.get(norm(s["nome"]), 0), 2) or None
        staff.sort(key=lambda s: -(s.get("salario") or 0))
        folha = sum(s.get("salario") or 0 for s in staff)
        surname = norm(p.get("full_name") or p["name"]).split()[-1]
        same = [s["nome"] for s in staff if len(surname) > 3 and surname in norm(s["nome"]).split()]
        people[pid] = {"casa": "senado", "assessores": len(staff), "assessores_gabinete_oficial": pes.get("Gabinete"), "escritorios_apoio": pes.get("Escritório(s) de Apoio"), "folha_mensal": round(folha, 2), "folha_mes": mes_ref,
                       "equipe": [{k: s.get(k) for k in ("nome", "funcao", "vinculo", "salario", "desde")} for s in staff], "mesmo_sobrenome": same,
                       "cotas": {c["recurso"]: c["valor"] for c in cotas if c.get("valor")}, "cotas_total": cot_total, "nao_inclusos": {c["recurso"]: c["valor"] for c in nao if c.get("valor")}, "nao_inclusos_total": nao_total,
                       "auxilio_moradia": ben.get("Auxílio-Moradia"), "imovel_funcional": ben.get("Imóvel Funcional"),
                       "custo_ano": {"meses": round(months, 1), "subsidio": round(SUBSIDIO * months, 2), "cota": round(cot_total + nao_total, 2), "gabinete_estimado": round(folha * months, 2), "total": round(SUBSIDIO * months + cot_total + nao_total + folha * months, 2)}}
    med = lambda f: round(statistics.median(f(v) for v in people.values() if f(v) is not None), 2) if people else None
    medians = {"assessores": med(lambda v: v["assessores"]), "folha_mensal_estimada": med(lambda v: v["folha_mensal"]), "cota": med(lambda v: v["custo_ano"]["cota"]), "custo_ano_total": med(lambda v: v["custo_ano"]["total"]), "escritorios_apoio": med(lambda v: v.get("escritorios_apoio"))}
    out = {"generated_at": TODAY.isoformat(), "fonte": "Senado Federal, API administrativa de dados abertos (recursos utilizados, servidores e remunerações)", "subsidio_mensal": SUBSIDIO, "folha_mes": mes_ref,
           "nota": f"Equipe: servidores lotados no gabinete do senador, em Brasília e nos escritórios de apoio no estado. Folha: remuneração básica, função comissionada e vantagens pessoais dessas pessoas em {mes_ref}, pela folha publicada pelo Senado, sem auxílios nem 13º. Nomes de servidores comissionados são públicos.",
           "medianas": medians, "people": people}
    (ROOT / "data" / "generated" / "gabinetes-senado.yaml").write_text("# GERADO por etl/gabinetes_senado.py. Não edite à mão.\n" + yaml.dump(out, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    print(f"gabinetes senado: {len(people)} senadores; folha de {mes_ref}; medianas {medians}")
    for pid, v in sorted(people.items(), key=lambda kv: -kv[1]["folha_mensal"])[:3]: print("  ", P[pid]["name"], v["assessores"], "no gabinete (oficial", v["assessores_gabinete_oficial"], ") folha", v["folha_mensal"], "| cotas", v["cotas_total"], "| apoio", v["escritorios_apoio"])
if __name__ == "__main__": main()
