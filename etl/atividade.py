#!/usr/bin/env python3
"""Atividade dos parlamentares → data/generated/atividade.yaml (presença em votações nominais, últimos votos, cota parlamentar).

Fontes:
  - Câmara, arquivos em lote: votacoesVotos-{ano}.csv (voto por deputado), votacoes-{ano}.csv (órgão e descrição da votação)
  - Câmara, cota parlamentar: https://www.camara.leg.br/cotas/Ano-{ano}.csv.zip (CEAP, por deputado, mês e tipo)
  - Senado, /dadosabertos/votacao?dataInicio&dataFim (votações nominais com o voto de cada senador)
Janela: o ano legislativo corrente (desde 2 de fevereiro). Uso: .venv/bin/python etl/atividade.py
"""
import csv, io, json, sys, zipfile, pathlib, datetime, urllib.request, collections, time
import yaml
ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / "build" / "cache-atividade"; CACHE.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (Macintosh) atlas-da-republica/0.1", "Accept": "application/json"}
TODAY = datetime.date.today(); SINCE = datetime.date(TODAY.year, 2, 2)  # início do ano legislativo (CF art. 57)
def fetch(url, name, max_age_h=20):
    p = CACHE / name
    if p.exists() and (datetime.datetime.now() - datetime.datetime.fromtimestamp(p.stat().st_mtime)).total_seconds() < max_age_h * 3600: return p.read_bytes()
    print("GET", url, file=sys.stderr)
    data = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=600).read(); p.write_bytes(data); return data
def rows(data, enc="utf-8-sig"):
    return csv.DictReader(io.StringIO(data.decode(enc, "ignore")), delimiter=";")

def camara():
    ano = TODAY.year
    vot = {r["id"]: r for r in rows(fetch(f"https://dadosabertos.camara.leg.br/arquivos/votacoes/csv/votacoes-{ano}.csv", f"votacoes-{ano}.csv"))}
    plen = {k for k, r in vot.items() if r.get("siglaOrgao") == "PLEN" and r.get("data", "") >= SINCE.isoformat()}
    per = collections.defaultdict(lambda: {"votes": 0, "last": []}); n_votacoes = set()
    for r in rows(fetch(f"https://dadosabertos.camara.leg.br/arquivos/votacoesVotos/csv/votacoesVotos-{ano}.csv", f"votacoesVotos-{ano}.csv")):
        vid = r["idVotacao"]
        if vid not in plen or not r.get("deputado_id"): continue
        n_votacoes.add(vid); d = per[r["deputado_id"]]; d["votes"] += 1
        if len(d["last"]) < 40: d["last"].append((r["dataHoraVoto"][:10], vid, r["voto"]))
    total = len(n_votacoes)
    out = {}
    for did, d in per.items():
        last = sorted(d["last"], key=lambda x: x[0], reverse=True)[:5]
        out[f"br-p-cd-{did}"] = {"house": "camara", "window": "ano", "votacoes_nominais": total, "votou_em": d["votes"], "pct": round(100 * d["votes"] / total, 1) if total else None,
                                "ultimos": [{"date": dt, "id": vid, "voto": v, "desc": (vot[vid].get("ultimaApresentacaoProposicao_descricao") or vot[vid].get("descricao") or "")[:140], "prop": vot[vid].get("ultimaApresentacaoProposicao_idProposicao") or None} for dt, vid, v in last]}
    # deputados que não votaram em nenhuma nominal: aparecem com 0 (só se estiverem na base de votos do ano)
    seen_year = {r["deputado_id"] for r in rows(fetch(f"https://dadosabertos.camara.leg.br/arquivos/votacoesVotos/csv/votacoesVotos-{ano}.csv", f"votacoesVotos-{ano}.csv"))}
    for did in seen_year:
        if not did: continue
        out.setdefault(f"br-p-cd-{did}", {"house": "camara", "window": "ano", "votacoes_nominais": total, "votou_em": 0, "pct": 0.0 if total else None, "ultimos": []})
    # cota parlamentar
    z = zipfile.ZipFile(io.BytesIO(fetch(f"https://www.camara.leg.br/cotas/Ano-{ano}.csv.zip", f"cota-{ano}.zip")))
    name = [n for n in z.namelist() if n.endswith(".csv")][0]
    tot = collections.defaultdict(float); bym = collections.defaultdict(lambda: collections.defaultdict(float)); byk = collections.defaultdict(lambda: collections.defaultdict(float)); names = {}
    with z.open(name) as f:
        for r in csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"), delimiter=";"):
            did = r.get("ideCadastro") or ""
            if not did: continue
            v = float(r.get("vlrLiquido") or 0); tot[did] += v; bym[did][int(r["numMes"])] += v; byk[did][r["txtDescricao"].title()[:40]] += v; names[did] = r["txNomeParlamentar"]
    months_done = max((m for d in bym.values() for m in d), default=0)
    for did, v in tot.items():
        rec = out.setdefault(f"br-p-cd-{did}", {"house": "camara", "window": "ano", "votacoes_nominais": total, "votou_em": None, "pct": None, "ultimos": []})
        rec["cota"] = {"ano": ano, "total": round(v, 2), "meses": months_done, "media_mes": round(v / months_done, 2) if months_done else None, "top": [{"k": k, "v": round(x, 2)} for k, x in sorted(byk[did].items(), key=lambda kv: -kv[1])[:4]]}
    return out, total

def senado():
    per = collections.defaultdict(lambda: {"votes": 0, "last": []}); n = 0
    start = SINCE
    while start <= TODAY:
        end = min(start + datetime.timedelta(days=29), TODAY)
        try:
            d = json.load(urllib.request.urlopen(urllib.request.Request(f"https://legis.senado.leg.br/dadosabertos/votacao?dataInicio={start}&dataFim={end}", headers=UA), timeout=120)) or []
        except Exception as e: print("senado votacao falhou", start, e, file=sys.stderr); d = []
        for v in d:
            votos = v.get("votos") or []
            if not votos: continue
            n += 1; secret = v.get("votacaoSecreta") == "S" or v.get("votacaoSecreta") is True
            for x in votos:
                s = (x.get("siglaVotoParlamentar") or "").strip()
                present = s not in ("", "NCom", "Não Compareceu", "Ausente", "P-NRV", "LP", "MIS", "AP", "LS", "LA", "NA")  # ausências e licenças
                if present:
                    r = per[str(x.get("codigoParlamentar"))]; r["votes"] += 1
                    if len(r["last"]) < 40: r["last"].append((v.get("dataSessao"), v.get("identificacao"), "voto secreto" if secret else s, (v.get("ementa") or v.get("descricaoVotacao") or "")[:140]))
        start = end + datetime.timedelta(days=1); time.sleep(0.5)
    out = {}
    for cod, r in per.items():
        last = sorted(r["last"], key=lambda x: x[0] or "", reverse=True)[:5]
        out[f"br-p-sf-{cod}"] = {"house": "senado", "window": "ano", "votacoes_nominais": n, "votou_em": r["votes"], "pct": round(100 * r["votes"] / n, 1) if n else None,
                                "ultimos": [{"date": dt, "id": ident, "voto": s, "desc": desc} for dt, ident, s, desc in last]}
    return out, n

def main():
    cd, ncd = camara(); sf, nsf = senado()
    out = {"generated_at": TODAY.isoformat(), "since": SINCE.isoformat(), "camara_votacoes": ncd, "senado_votacoes": nsf, "people": {**cd, **sf}}
    (ROOT / "data" / "generated" / "atividade.yaml").write_text("# GERADO por etl/atividade.py. Não edite à mão.\n" + yaml.dump(out, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    print(f"câmara: {ncd} votações nominais em plenário no ano legislativo, {len(cd)} deputados; senado: {nsf} votações, {len(sf)} senadores")
    top = sorted((v for v in cd.values() if v.get("cota")), key=lambda v: -v["cota"]["total"])[:3]
    for v in top: print("  cota:", v["cota"]["total"], v["cota"]["top"][:2])
    low = sorted((v for v in cd.values() if v.get("pct") is not None), key=lambda v: v["pct"])[:3]; print("  menor presença CD:", [(k, v["pct"]) for k, v in cd.items() if v in low][:3])
if __name__ == "__main__": main()
