#!/usr/bin/env python3
"""Câmara + Senado → data/generated/parlamentares.yaml (ocupantes das cadeiras eletivas e da Mesa da Câmara).

Fontes sem chave:
  https://dadosabertos.camara.leg.br/api/v2/deputados      (513 deputados em exercício, partido, UF, foto)
  https://dadosabertos.camara.leg.br/api/v2/orgaos/4/membros (Mesa Diretora da Câmara)
  https://legis.senado.leg.br/dadosabertos/senador/lista/atual (81 senadores em exercício)
Uso: .venv/bin/python etl/parlamentares.py [--cache DIR]
"""
import json, sys, pathlib, argparse, urllib.request, re
import yaml
ROOT = pathlib.Path(__file__).resolve().parent.parent

def get(url, cache, name):
    if cache and (pathlib.Path(cache) / name).exists(): return json.load(open(pathlib.Path(cache) / name, encoding="utf-8"))
    print("GET", url, file=sys.stderr)
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "atlas-da-republica/0.1"})
    with urllib.request.urlopen(req, timeout=120) as r: data = json.load(r)
    if cache: json.dump(data, open(pathlib.Path(cache) / name, "w", encoding="utf-8"), ensure_ascii=False)
    return data

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--cache"); a = ap.parse_args()
    cam = get("https://dadosabertos.camara.leg.br/api/v2/deputados?itens=600&ordem=ASC&ordenarPor=nome", a.cache, "camara.json")["dados"]
    mesa = get("https://dadosabertos.camara.leg.br/api/v2/orgaos/4/membros", a.cache, "mesa.json")["dados"]
    sen = get("https://legis.senado.leg.br/dadosabertos/senador/lista/atual", a.cache, "senado.json")["ListaParlamentarEmExercicio"]["Parlamentares"]["Parlamentar"]
    deputados = [{"id": f"br-p-cd-{d['id']}", "name": d["nome"], "party": d.get("siglaPartido"), "uf": d.get("siglaUf"),
                  "image_url": d.get("urlFoto"), "entry_mode": "eleito", "started_at": "2023-02-01", "legislatura": d.get("idLegislatura"),
                  "source_url": d["uri"]} for d in cam]
    senadores = []
    for s in sen:
        i = s["IdentificacaoParlamentar"]; m = s.get("Mandato") or {}
        leg = (m.get("PrimeiraLegislaturaDoMandato") or {})
        senadores.append({"id": f"br-p-sf-{i['CodigoParlamentar']}", "name": i["NomeParlamentar"], "full_name": i.get("NomeCompletoParlamentar"),
                          "party": i.get("SiglaPartidoParlamentar"), "uf": i.get("UfParlamentar"), "image_url": i.get("UrlFotoParlamentar"),
                          "entry_mode": "eleito" if (m.get("DescricaoParticipacao") or "Titular") == "Titular" else "suplente",
                          "started_at": leg.get("DataInicio"), "mesa": i.get("MembroMesa") == "Sim", "source_url": i.get("UrlPaginaParlamentar")})
    mesa_cd = [{"id": f"br-p-cd-{x['id']}", "name": x["nome"], "party": x.get("siglaPartido"), "uf": x.get("siglaUf"), "image_url": x.get("urlFoto"),
                "role": x.get("titulo"), "entry_mode": "eleito", "started_at": x.get("dataInicio"), "source_url": x.get("uri")} for x in mesa]
    pres_cd = [dict(x, role=None) for x in mesa_cd if x.get("role") == "Presidente"]
    out = {"generated_from": "dadosabertos.camara.leg.br + legis.senado.leg.br", "positions": {
        "br-deputado-federal": deputados, "br-senador": senadores,
        "br-mesa-da-camara-dos-deputados": [x for x in mesa_cd if x.get("role") and "Suplente" not in x["role"]],
        "br-presidente-da-camara-dos-deputados": pres_cd}}
    class D(yaml.SafeDumper):
        def increase_indent(self, flow=False, indentless=False): return super().increase_indent(flow, False)
    (ROOT / "data" / "generated" / "parlamentares.yaml").write_text("# GERADO por etl/parlamentares.py. Não edite à mão.\n" + yaml.dump(out, Dumper=D, allow_unicode=True, sort_keys=False, width=110), encoding="utf-8")
    from collections import Counter
    print(f"deputados={len(deputados)} senadores={len(senadores)} mesa_cd={len(out['positions']['br-mesa-da-camara-dos-deputados'])} presidente_cd={[p['name'] for p in pres_cd]}")
    print("partidos CD:", Counter(d["party"] for d in deputados).most_common(8)); print("partidos SF:", Counter(s["party"] for s in senadores).most_common(6))
if __name__ == "__main__": main()
