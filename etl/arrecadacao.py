#!/usr/bin/env python3
"""Arrecadômetro → data/generated/arrecadacao.yaml.

Fontes oficiais, sem estimativa escondida:
  - Portal da Transparência, receitas realizadas da União (CSV anual, atualizado diariamente): impostos, taxas e contribuições
    por mês de lançamento, para o ano corrente e os dois anteriores
  - IBGE/SIDRA 1737: IPCA número-índice mensal (para comparar anos em valor real)
  - IBGE/SIDRA 6579: população residente estimada (por habitante)
  - Banco Central/SGS 4607: juros nominais do governo federal, fluxo mensal (R$ milhões)
Uso: .venv/bin/python etl/arrecadacao.py
"""
import csv, io, json, sys, zipfile, pathlib, datetime, urllib.request, collections
import yaml
ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / "build" / "cache-arrecadacao"; CACHE.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (Macintosh) atlas-da-republica/0.1"}
TODAY = datetime.date.today()
TRIB = {"Impostos, Taxas e Contribuições de Melhoria", "Contribuições"}
def fetch(url, name, max_age_h=20):
    p = CACHE / name
    if p.exists() and (datetime.datetime.now() - datetime.datetime.fromtimestamp(p.stat().st_mtime)).total_seconds() < max_age_h * 3600: return p.read_bytes()
    print("GET", url, file=sys.stderr)
    data = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=300).read()
    p.write_bytes(data); return data
def receitas(ano):
    z = fetch(f"https://dadosabertos-download.cgu.gov.br/PortalDaTransparencia/saida/receitas/{ano}_Receitas.zip", f"{ano}_Receitas.zip", 20 if ano == TODAY.year else 24 * 30)
    zf = zipfile.ZipFile(io.BytesIO(z)); name = [n for n in zf.namelist() if n.endswith(".csv")][0]
    by_month = collections.defaultdict(float); by_kind = collections.defaultdict(float); by_day = collections.defaultdict(float); last = None
    with zf.open(name) as f:
        for row in csv.DictReader(io.TextIOWrapper(f, encoding="latin1"), delimiter=";"):
            if row["ORIGEM RECEITA"] not in TRIB: continue
            v = float((row["VALOR REALIZADO"] or "0").replace(".", "").replace(",", "."))
            d = row["DATA LANÇAMENTO"]; ym = f"{d[6:10]}-{d[3:5]}"; iso = f"{d[6:10]}-{d[3:5]}-{d[0:2]}"
            by_month[ym] += v; by_kind[row["ESPÉCIE RECEITA"]] += v; by_day[iso] += v
            if not last or iso > last: last = iso
    return dict(sorted(by_month.items())), dict(sorted(by_kind.items(), key=lambda kv: -kv[1])[:12]), last, dict(by_day)
def ipca():
    d = json.load(urllib.request.urlopen(urllib.request.Request("https://apisidra.ibge.gov.br/values/t/1737/n1/all/v/2266/p/all?formato=json", headers=UA), timeout=120))
    out = {}
    for r in d[1:]:
        m = r["D3C"]; out[f"{m[:4]}-{m[4:6]}"] = float(r["V"])
    return out
def populacao():
    d = json.load(urllib.request.urlopen(urllib.request.Request("https://apisidra.ibge.gov.br/values/t/6579/n1/all/v/9324/p/last%201?formato=json", headers=UA), timeout=120))
    return int(float(d[1]["V"])), d[1]["D3N"]
def juros():
    d = json.load(urllib.request.urlopen(urllib.request.Request(f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.4607/dados?formato=json&dataInicial=01/01/{TODAY.year-2}&dataFinal={TODAY.strftime('%d/%m/%Y')}", headers=UA), timeout=120))
    return {f"{x['data'][6:10]}-{x['data'][3:5]}": float(x["valor"]) * 1e6 for x in d}
def main():
    years = {}
    for ano in (TODAY.year - 2, TODAY.year - 1, TODAY.year):
        try: years[ano] = receitas(ano)
        except Exception as e: print("receitas", ano, "falhou:", e, file=sys.stderr)
    idx = ipca(); pop, pop_year = populacao(); jur = juros()
    cur = years[TODAY.year][0]; last_date = years[TODAY.year][2]
    last_month = last_date[:7]; complete_months = [m for m in cur if m < last_month]  # meses fechados
    ytd_months = complete_months + [last_month]
    ref_idx = idx.get(max(k for k in idx if k <= last_month)) or list(idx.values())[-1]
    def real(v, ym): 
        i = idx.get(ym) or idx.get(max((k for k in idx if k <= ym), default=None) or "")
        return v * ref_idx / i if i else v
    prev = years.get(TODAY.year - 1, ({}, {}, None, {}))[0]; prev_days = years.get(TODAY.year - 1, ({}, {}, None, {}))[3]
    ytd_now = sum(cur[m] for m in ytd_months)
    # mesmo período do ano anterior: meses fechados inteiros + o mês corrente só até o mesmo dia
    prev_same = [m.replace(str(TODAY.year), str(TODAY.year - 1), 1) for m in complete_months]
    pm = last_month.replace(str(TODAY.year), str(TODAY.year - 1), 1); cut = pm + last_date[7:]
    prev_partial = sum(v for d, v in prev_days.items() if d.startswith(pm) and d <= cut)
    ytd_prev = sum(prev.get(m, 0) for m in prev_same) + prev_partial
    ytd_prev_real = sum(real(prev.get(m, 0), m) for m in prev_same) + real(prev_partial, pm)
    # ritmo: média por segundo dos últimos 3 meses fechados
    last3 = complete_months[-3:] if len(complete_months) >= 3 else complete_months
    secs = sum(((datetime.date.fromisoformat(m + "-01").replace(day=28) + datetime.timedelta(days=4)).replace(day=1) - datetime.date.fromisoformat(m + "-01")).days * 86400 for m in last3) or 1
    rate = sum(cur[m] for m in last3) / secs
    # âncora do contador: total até a data dos dados + ritmo (o que passa da âncora é projeção)
    j_ytd = sum(v for k, v in jur.items() if k.startswith(str(TODAY.year))); j_prev = sum(v for k, v in jur.items() if k.startswith(str(TODAY.year - 1)))
    out = {"generated_at": TODAY.isoformat(), "source_date": last_date, "year": TODAY.year, "months": {str(y): years[y][0] for y in years}, "kinds": years[TODAY.year][1], "prev_partial_month": {"month": pm, "through": cut, "value": prev_partial},
           "ipca_ref_month": max(k for k in idx if k <= last_month), "population": pop, "population_year": pop_year,
           "ytd": {"months": ytd_months, "nominal": ytd_now, "prev_nominal": ytd_prev, "prev_real": ytd_prev_real, "growth_nominal_pct": (ytd_now / ytd_prev - 1) * 100 if ytd_prev else None, "growth_real_pct": (ytd_now / ytd_prev_real - 1) * 100 if ytd_prev_real else None, "per_capita": ytd_now / pop},
           "rate_per_second": rate, "rate_months": last3, "anchor": {"date": last_date, "value": ytd_now},
           "full_years": {str(y): sum(years[y][0].values()) for y in years if y < TODAY.year},
           "juros": {"months": {k: v for k, v in jur.items()}, "ytd": j_ytd, "prev_year": j_prev, "last_month": max(jur) if jur else None}}
    (ROOT / "data" / "generated" / "arrecadacao.yaml").write_text("# GERADO por etl/arrecadacao.py. Não edite à mão.\n" + yaml.dump(out, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    print(f"arrecadação {TODAY.year} até {last_date}: R$ {ytd_now/1e9:.1f} bi ({len(ytd_months)} meses); mesmo período {TODAY.year-1}: R$ {ytd_prev/1e9:.1f} bi nominal, R$ {ytd_prev_real/1e9:.1f} bi em reais de hoje; real {out['ytd']['growth_real_pct']:.1f}%")
    print(f"ritmo: R$ {rate:,.0f}/s ({last3}); por habitante: R$ {ytd_now/pop:,.0f}; juros {TODAY.year}: R$ {j_ytd/1e9:.1f} bi até {out['juros']['last_month']}; {TODAY.year-1}: R$ {j_prev/1e9:.1f} bi")
if __name__ == "__main__": main()
