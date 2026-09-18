#!/usr/bin/env python3
"""Conector SIORG → data/generated/siorg.yaml

Baixa órgãos e entidades da esfera federal (poderes 1-4) e, opcionalmente, a estrutura completa do
Executivo para resolver pais que são unidades internas e para extrair unidades colegiadas.

Uso:
  .venv/bin/python etl/siorg.py            # baixa e gera
  .venv/bin/python etl/siorg.py --cache DIR  # usa JSON já baixado em DIR (siorg-oe-{1..4}.json, siorg-full-1.json)
"""
import json, re, sys, pathlib, unicodedata, urllib.request, argparse
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASE = "https://estruturaorganizacional.dados.gov.br/doc"
PODER_SECTOR = {1: "executivo", 2: "legislativo", 3: "judiciario", 4: "essenciais"}
NAT = {1: "empresa_publica", 2: "fundacao", 3: "orgao_singular", 4: "autarquia", 6: "sociedade_economia_mista", 7: "orgao_autonomo"}
SUBNAT = {16: "autarquia", 17: "instituicao_de_ensino", 18: "instituicao_de_ensino", 19: "agencia_reguladora", 20: "instituicao_de_ensino", 5: "orgao_autonomo"}
INDIRETA = {"autarquia", "fundacao", "empresa_publica", "sociedade_economia_mista", "agencia_reguladora", "instituicao_de_ensino"}

def slug(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s

def code(url): return (url or "").rstrip("/").split("/")[-1]

def fetch(url, cache=None, name=None):
    if cache and name and (pathlib.Path(cache) / name).exists():
        return json.load(open(pathlib.Path(cache) / name, encoding="utf-8"))
    print("GET", url, file=sys.stderr)
    with urllib.request.urlopen(url, timeout=300) as r:
        data = json.load(r)
    if cache and name:
        json.dump(data, open(pathlib.Path(cache) / name, "w", encoding="utf-8"), ensure_ascii=False)
    return data

def clean(t, n=420):
    if not t: return ""
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"^(À|Ao|A|O)\s+.{3,90}?\s+compete[,:]?\s*", "", t)  # "À Agência X compete ..."
    if len(t) > n:
        cut = t[:n]; i = max(cut.rfind(". "), cut.rfind("; ")); t = (cut[:i+1] if i > 120 else cut).rstrip(" ;,") + ("" if cut.endswith(".") else "…")
    return t

def ato_cite(a):
    if not a: return None
    tipo = a.get("tipoAto") or ""; num = a.get("numero") or ""; data = (a.get("dataAssinatura") or a.get("dataPublicacao") or "")
    ano = data[:4] if data else ""
    if not tipo and not num: return None
    return f"{tipo} {num}{('/' + ano) if ano and ano not in num else ''}".strip()

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--cache"); ap.add_argument("--no-full", action="store_true", help="não baixa a estrutura completa (30+ MB)"); ap.add_argument("--out", default=str(ROOT / "data" / "generated" / "siorg.yaml"))
    args = ap.parse_args()
    orgs = []
    for p in (1, 2, 3, 4):
        d = fetch(f"{BASE}/orgao-entidade/completa?codigoPoder={p}&codigoEsfera=1", args.cache, f"siorg-oe-{p}.json")
        for x in d.get("unidades") or []: x["_poder"] = p; orgs.append(x)
    full = {} if args.no_full else fetch(f"{BASE}/estrutura-organizacional/completa?codigoPoder=1&codigoEsfera=1", args.cache, "siorg-full-1.json")
    units = {code(x["codigoUnidade"]): x for x in full.get("unidades") or []}
    org_codes = {code(x["codigoUnidade"]) for x in orgs}

    def resolve_parent(x):
        p = code(x.get("codigoUnidadePai"))
        if not p or p == code(x["codigoUnidade"]): return None
        if p in org_codes: return p
        u = units.get(p)
        if u:
            o = code(u.get("codigoOrgaoEntidade"))
            if o in org_codes and o != code(x["codigoUnidade"]): return o
        return None

    nodes = []
    by_code = {}
    for x in orgs:
        c = code(x["codigoUnidade"]); nat = int(code(x["codigoNaturezaJuridica"]) or 0); sub = int(code(x.get("codigoSubNaturezaJuridica")) or 0)
        subtype = SUBNAT.get(sub) or NAT.get(nat, "orgao_singular")
        site = None
        for ct in (x.get("contato") or []):
            for s in (ct.get("site") or []):
                if s.get("site"): site = s["site"]; break
        if site and not site.startswith("http"): site = "https://" + site
        desc = clean(x.get("finalidade") or x.get("competencia") or x.get("missao") or "")
        n = {"id": "br-" + slug(x["nome"]), "siorg_code": int(c), "type": "department", "subtype": subtype,
             "sector": PODER_SECTOR[x["_poder"]], "name": x["nome"].strip(), "aliases": [x["sigla"]] if x.get("sigla") else [],
             "description": desc, "cite": ato_cite(x.get("atoNormativo")) or "SIORG (ato normativo não informado)",
             "cite_url": f"https://estruturaorganizacional.dados.gov.br/id/unidade-organizacional/{c}",
             "official_url": site, "siorg_parent": resolve_parent(x), "siorg_tipo": code(x["codigoTipoUnidade"]),
             "natureza_juridica": nat, "source": "siorg", "verified": False}
        if not n["description"] or len(n["description"]) < 40:
            n["description"] = f"{x['nome'].strip()}, {NAT.get(nat, 'órgão').replace('_', ' ')} da esfera federal registrada no SIORG."
        nodes.append(n); by_code[c] = n

    # anel: órgão da administração direta ligado à PR = 2 (ministério); direta abaixo de ministério = 3; indireta = 4
    PR = next((n for n in nodes if (n["aliases"] or [""])[0] == "PR"), None)
    for n in nodes:
        parent = by_code.get(n["siorg_parent"]) if n["siorg_parent"] else None
        n["siorg_parent_id"] = parent["id"] if parent else None
        if n["subtype"] in INDIRETA: n["ring"] = 4
        elif PR and n is PR: n["ring"] = 1
        elif parent is PR or parent is None: n["ring"] = 2
        else: n["ring"] = 3
        n.pop("siorg_parent")

    # unidades colegiadas do Executivo (conselhos, comitês, câmaras) ligadas a órgãos/entidades
    coleg = []
    for c, u in units.items():
        if not u["codigoTipoUnidade"].endswith("colegiada"): continue
        o = code(u.get("codigoOrgaoEntidade")); org = by_code.get(o)
        if not org: continue
        nm = u["nome"].strip()
        if not re.match(r"^(Conselho|Comitê|Comissão|Câmara|Colegiado|Junta)\b", nm): continue
        # só colegiados de primeiro nível (pai = o próprio órgão) de órgãos da administração direta,
        # com alcance nacional no nome; corta comitês internos de estatais e autarquias
        if code(u.get("codigoUnidadePai")) != o: continue
        if org["natureza_juridica"] != 3: continue
        if not re.search(r"Nacional|Federal|Interministerial|de Governo|Monetário|da República|de Política|Gestor|Deliberativ", nm): continue
        coleg.append({"id": "br-" + slug(nm), "siorg_code": int(c), "type": "commission", "sector": org["sector"], "ring": 3,
                      "name": nm, "aliases": [u["sigla"]] if u.get("sigla") else [], "siorg_parent_id": org["id"],
                      "description": (lambda d: d if len(d) >= 40 else f"Colegiado vinculado a {org['name']}, registrado no SIORG como unidade colegiada de primeiro nível. Competência não informada na fonte.")(clean(u.get("competencia") or u.get("finalidade") or "")),
                      "cite": ato_cite(u.get("atoNormativo")) or "SIORG (ato normativo não informado)",
                      "cite_url": f"https://estruturaorganizacional.dados.gov.br/id/unidade-organizacional/{c}", "source": "siorg", "verified": False})
    # dedupe ids
    seen = {}
    for n in nodes + coleg:
        if n["id"] in seen: n["id"] = f"{n['id']}-{n['siorg_code']}"
        seen[n["id"]] = n
    out = {"generated_from": "SIORG estruturaorganizacional.dados.gov.br", "generated_at": ((full.get("servico") or {}).get("data")) or (d.get("servico") or {}).get("data"),
           "nodes": nodes, "collegiate": coleg}
    class D(yaml.SafeDumper):
        def increase_indent(self, flow=False, indentless=False): return super().increase_indent(flow, False)
    D.add_representer(str, lambda dp, s: dp.represent_scalar('tag:yaml.org,2002:str', s, style='>' if len(s) > 90 else None))
    pathlib.Path(args.out).write_text("# GERADO por etl/siorg.py. Não edite à mão: a curadoria vive em data/nodes/.\n" + yaml.dump(out, Dumper=D, allow_unicode=True, sort_keys=False, width=110), encoding="utf-8")
    from collections import Counter
    print(f"órgãos/entidades: {len(nodes)}  colegiadas: {len(coleg)}  sem pai: {sum(1 for n in nodes if not n['siorg_parent_id'])}")
    print("subtypes:", dict(Counter(n["subtype"] for n in nodes))); print("setores:", dict(Counter(n["sector"] for n in nodes)))

if __name__ == "__main__": main()
