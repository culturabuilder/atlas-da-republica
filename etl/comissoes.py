#!/usr/bin/env python3
"""Senado + Câmara → data/generated/comissoes.yaml (Mesa do Senado, comissões permanentes das duas Casas e mistas, com composição).

Fontes sem chave:
  https://legis.senado.leg.br/dadosabertos/composicao/mesaSF            (Mesa do Senado)
  https://legis.senado.leg.br/dadosabertos/comissao/lista/colegiados    (colegiados em atividade)
  https://legis.senado.leg.br/dadosabertos/comissao/{codigo}            (cargos e membros por bloco)
  https://legis.senado.leg.br/dadosabertos/comissao/lista/mistas        (comissões mistas do Congresso, com membros)
  https://dadosabertos.camara.leg.br/api/v2/orgaos?codTipoOrgao=2       (comissões permanentes da Câmara)
  https://dadosabertos.camara.leg.br/api/v2/orgaos/{id}/membros         (composição)
Uso: .venv/bin/python etl/comissoes.py [--cache DIR]
"""
import json, sys, pathlib, argparse, urllib.request, re, unicodedata, time
import yaml
ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = "Mozilla/5.0 (Macintosh) atlas-da-republica/0.1"

def get(url, cache, name):
    if cache and (pathlib.Path(cache) / name).exists(): return json.load(open(pathlib.Path(cache) / name, encoding="utf-8"))
    print("GET", url, file=sys.stderr)
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": UA})
    for i in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as r: data = json.load(r); break
        except Exception as e:
            if i == 2: raise
            time.sleep(2)
    if cache: pathlib.Path(cache).mkdir(parents=True, exist_ok=True); json.dump(data, open(pathlib.Path(cache) / name, "w", encoding="utf-8"), ensure_ascii=False)
    return data

def slug(s): return re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()).strip("-")
def lst(x): return x if isinstance(x, list) else ([x] if x else [])
def clean_name(s): return re.sub(r"^(Senador|Senadora|Deputado|Deputada)\s+", "", (s or "").strip())
def bancada(b):
    m = re.match(r"\(?([A-ZÃÇÉÍÓÚa-z]+)-([A-Z]{2})\)?", b or ""); return (m.group(1), m.group(2)) if m else (None, None)
def role_title(t):
    t = (t or "").strip(); t = t.replace("PRESIDENTE", "Presidente").replace("VICE-Presidente", "Vice-Presidente").replace("SECRETÁRIO", "Secretário").replace("SECRETÁRIA", "Secretária").replace("SUPLENTE", "Suplente")
    return t

# ids curados em data/nodes/05-legislativo.yaml (sigla → id)
CURATED = {"SF:CCJ": "br-comissao-de-constituicao-justica-e-cidadania-do-senado", "SF:CAE": "br-comissao-de-assuntos-economicos-do-senado",
           "SF:CRE": "br-comissao-de-relacoes-exteriores-e-defesa-nacional-do-senado", "SF:CI": "br-comissao-de-infraestrutura-do-senado",
           "CD:CCJC": "br-comissao-de-constituicao-e-justica-e-de-cidadania-da-camara", "CD:CFT": "br-comissao-de-financas-e-tributacao-da-camara",
           "CN:CMO": "br-comissao-mista-de-orcamento"}

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--cache"); a = ap.parse_args()
    nodes, positions = [], {}

    # ---- Mesa do Senado
    mesa = get("https://legis.senado.leg.br/dadosabertos/composicao/mesaSF", a.cache, "mesaSF.json")["MesaSenado"]["Colegiados"]["Colegiado"]
    mesa = lst(mesa)[0]; ppl = []
    for c in lst(mesa["Cargos"]["Cargo"]):
        role = role_title(" ".join(lst(c.get("Cargo")))); party, uf = bancada(c.get("Bancada"))
        ppl.append({"id": f"br-p-sf-{c['Http']}", "name": clean_name(c["NomeParlamentar"]), "party": party, "uf": uf, "role": role, "entry_mode": "eleito", "source": "senado",
                    "source_url": "https://www25.senado.leg.br/web/senadores/mesa-diretora"})
    import datetime as _dt
    _t = _dt.date.today(); _y = _t.year if (_t.year % 2 == 1 and _t >= _dt.date(_t.year, 2, 1)) else (_t.year - 1 if _t.year % 2 == 0 else _t.year - 2)
    for p in ppl: p["started_at"] = f"{_y}-02-01"; p["note"] = "biênio da Mesa; eleição em 1º de fevereiro"
    positions["br-mesa-do-senado-federal"] = [p for p in ppl if "Suplente" not in p["role"]]
    pres = [dict(p, role=None) for p in ppl if p["role"] == "Presidente"]
    if pres: positions["br-presidente-do-senado-federal"] = pres

    # ---- comissões permanentes do Senado
    col = get("https://legis.senado.leg.br/dadosabertos/comissao/lista/colegiados", a.cache, "colegiados.json")["ListaColegiados"]["Colegiados"]["Colegiado"]
    perm_sf = [c for c in lst(col) if c.get("SiglaTipoColegiado") == "PERMANENTE" and c.get("SiglaCasa") == "SF"]
    for c in sorted(perm_sf, key=lambda c: c["Sigla"]):
        d = get(f"https://legis.senado.leg.br/dadosabertos/comissao/{c['Codigo']}", a.cache, f"sf-{c['Codigo']}.json")["ComissoesCongressoNacional"]["Colegiados"]["Colegiado"]
        d = lst(d)[0]; sig = c["Sigla"]
        nid = CURATED.get(f"SF:{sig}") or f"br-{slug(c['Nome'])}-do-senado"
        q = (d.get("QuantidadesMembros") or {}).get("Distribuicao") or {}
        tit, sup = q.get("SenadoresTitulares"), q.get("SenadoresSuplentes")
        cargos = {clean_name(x["NomeParlamentar"]): role_title(x["TipoCargo"]) for x in lst((d.get("Cargos") or {}).get("Cargo"))}
        ppl = []
        for bl in lst((d.get("MembrosBlocoSF") or {}).get("PartidoBloco")):
            for m in lst((bl.get("MembrosSF") or {}).get("Membro")):
                nm = clean_name(m["NomeParlamentar"])
                if not m.get("CodigoParlamentar") or nm.upper() == "VAGO": continue
                ppl.append({"id": f"br-p-sf-{m['CodigoParlamentar']}", "name": nm, "party": m.get("Partido"), "uf": m.get("SiglaUf"), "role": cargos.get(nm) or m.get("TipoVaga"),
                            "entry_mode": "eleito", "source": "senado", "source_url": f"https://legis.senado.leg.br/comissoes/comissao?codcol={c['Codigo']}"})
        # presidente e vice primeiro, depois titulares, depois suplentes
        order = {"Presidente": 0, "Vice-Presidente": 1, "Titular": 2, "Suplente": 3}
        ppl.sort(key=lambda p: order.get(p["role"], 2))
        seen = set(); ppl = [p for p in ppl if not (p["id"] in seen or seen.add(p["id"]))]
        positions[nid] = ppl
        if f"SF:{sig}" not in CURATED:
            nodes.append({"id": nid, "type": "commission", "sector": "legislativo", "ring": 3, "parent": "br-senado-federal", "cluster": "comissao", "source": "senado",
                          "name": f"{c['Nome']} do Senado", "aliases": [sig, c["Nome"]],
                          "description": f"Comissão permanente do Senado Federal ({sig}). Aprecia, na sua área temática, os projetos e requerimentos que lhe são distribuídos, realiza audiências públicas e pode votar projetos em caráter terminativo. Composição: {tit or '?'} titulares e {sup or '?'} suplentes, distribuídos pelos blocos partidários.",
                          "cite": "CF/88 art. 58; RISF arts. 72-73", "cite_url": "https://www25.senado.leg.br/web/atividade/regimento-interno",
                          "official_url": f"https://legis.senado.leg.br/comissoes/comissao?codcol={c['Codigo']}", "seats_count": int(tit) if tit else None, "verified": True})
        else:
            nodes.append({"id": nid, "_merge_only": True, "seats_count": int(tit) if tit else None})

    # ---- comissões permanentes da Câmara
    org = get("https://dadosabertos.camara.leg.br/api/v2/orgaos?codTipoOrgao=2&itens=100&ordem=ASC&ordenarPor=sigla", a.cache, "cd-orgaos.json")["dados"]
    for o in org:
        members = []
        for pg in (1, 2, 3):
            d = get(f"https://dadosabertos.camara.leg.br/api/v2/orgaos/{o['id']}/membros?itens=100&pagina={pg}", a.cache, f"cd-{o['id']}-{pg}.json")["dados"]
            members += d
            if len(d) < 100: break
        sig = o["sigla"]; nid = CURATED.get(f"CD:{sig}") or f"br-{slug(o['nome'])}-da-camara"
        ppl = [{"id": f"br-p-cd-{m['id']}", "name": m["nome"], "party": m.get("siglaPartido"), "uf": m.get("siglaUf"), "image_url": m.get("urlFoto"), "role": m.get("titulo"),
                "started_at": m.get("dataInicio"), "entry_mode": "eleito", "source": "camara", "source_url": m.get("uri")} for m in members]
        order = lambda r: 0 if r == "Presidente" else 1 if "Vice" in (r or "") else 2 if r == "Titular" else 3
        ppl.sort(key=lambda p: order(p["role"]))
        seen = set(); ppl = [p for p in ppl if not (p["id"] in seen or seen.add(p["id"]))]
        tit = sum(1 for p in ppl if p["role"] != "Suplente")
        positions[nid] = ppl
        if f"CD:{sig}" not in CURATED:
            nodes.append({"id": nid, "type": "commission", "sector": "legislativo", "ring": 3, "parent": "br-camara-dos-deputados", "cluster": "comissao", "source": "camara",
                          "name": f"{o['nome']} da Câmara", "aliases": [sig, o["nome"]],
                          "description": f"Comissão permanente da Câmara dos Deputados ({sig}). Discute e vota as proposições da sua área temática, podendo aprová-las em caráter conclusivo sem passar pelo Plenário, e fiscaliza os atos do Executivo no seu campo. Composição atual: {tit} titulares.",
                          "cite": "CF/88 art. 58; RICD arts. 22 e 32", "cite_url": "https://www.camara.leg.br/internet/legislacao/regimento_interno/RIpdf/RegInterno.pdf",
                          "official_url": f"https://www.camara.leg.br/comissoes/{sig.lower()}", "seats_count": tit, "verified": True})
        else:
            nodes.append({"id": nid, "_merge_only": True, "seats_count": tit})

    # ---- comissões mistas (CMO e outras permanentes do Congresso)
    mistas = get("https://legis.senado.leg.br/dadosabertos/comissao/lista/mistas", a.cache, "mistas.json")["ComissoesMistasCongresso"]["Colegiados"]["Colegiado"]
    for d in lst(mistas):
        sig = d.get("SiglaColegiado"); nome = d.get("NomeColegiado") or ""
        if not sig: continue
        if sig != "CMO" and not re.search(r"Or[çc]amento|Intelig[êe]ncia|Mudan[çc]as Clim|Mercosul", nome): continue
        nid = CURATED.get(f"CN:{sig}") or f"br-{slug(nome)}"
        cargos = {clean_name(x["NomeParlamentar"]): role_title(x["TipoCargo"]) for x in lst((d.get("Cargos") or {}).get("Cargo"))}
        ppl = []
        for casa, pre in (("sf", "br-p-sf-"), ("cd", "br-p-cd-")):
            blk = d.get(f"Membros_bloco_{casa}") or d.get(f"MembrosBloco{casa.upper()}") or {}
            for bl in lst(blk.get("PartidoBloco")) + lst(blk.get("Membro")):
                if not isinstance(bl, dict): continue
                for m in lst((bl.get(f"Membros_{casa}") or bl.get(f"Membros{casa.upper()}") or {}).get("Membro")):
                    if not isinstance(m, dict): continue
                    nm = clean_name(m["NomeParlamentar"])
                    if not m.get("CodigoParlamentar") or nm.upper() == "VAGO": continue
                    ppl.append({"id": pre + str(m["CodigoParlamentar"]), "name": nm, "party": m.get("Partido"), "uf": m.get("SiglaUf"), "role": cargos.get(nm) or m.get("TipoVaga"),
                                "entry_mode": "eleito", "source": "senado", "source_url": "https://www.congressonacional.leg.br/comissoes"})
        order = {"Presidente": 0, "Vice-Presidente": 1, "Titular": 2, "Suplente": 3}
        ppl.sort(key=lambda p: order.get(p["role"], 2))
        seen = set(); ppl = [p for p in ppl if not (p["id"] in seen or seen.add(p["id"]))]
        if not ppl: continue
        positions[nid] = ppl
        q = d.get("QuantidadesMembros") or {}
        if f"CN:{sig}" not in CURATED:
            nodes.append({"id": nid, "type": "commission", "sector": "legislativo", "ring": 3, "parent": "br-congresso-nacional", "cluster": "comissao", "source": "senado",
                          "name": nome, "aliases": [sig],
                          "description": (d.get("Finalidade") or f"Comissão mista permanente do Congresso Nacional ({sig}), composta por deputados e senadores.") + f" Composição: {q.get('Titulares') or '?'} titulares ({q.get('SenadoresTitulares') or '?'} senadores e {q.get('DeputadosTitulares') or '?'} deputados).",
                          "cite": "CF/88 art. 58; " + (d.get("Subtitulo") or "Regimento Comum do Congresso Nacional"), "cite_url": "https://www.congressonacional.leg.br/comissoes",
                          "official_url": "https://www.congressonacional.leg.br/comissoes", "seats_count": int(q["Titulares"]) if q.get("Titulares") else None, "verified": True})
        else:
            nodes.append({"id": nid, "_merge_only": True, "seats_count": int(q["Titulares"]) if q.get("Titulares") else None})

    # foto e nome completo vêm do cadastro de parlamentares (mesmos ids)
    parl_p = ROOT / "data" / "generated" / "parlamentares.yaml"
    if parl_p.exists():
        parl = yaml.safe_load(open(parl_p, encoding="utf-8")) or {}
        idx = {p["id"]: p for v in (parl.get("positions") or {}).values() for p in v if p.get("id")}
        for ppl in positions.values():
            for p in ppl:
                q = idx.get(p["id"])
                if q and not p.get("image_url") and q.get("image_url"): p["image_url"] = q["image_url"]
    out = {"generated_from": "legis.senado.leg.br/dadosabertos + dadosabertos.camara.leg.br", "nodes": nodes, "positions": positions}
    class D(yaml.SafeDumper):
        def increase_indent(self, flow=False, indentless=False): return super().increase_indent(flow, False)
    (ROOT / "data" / "generated" / "comissoes.yaml").write_text("# GERADO por etl/comissoes.py. Não edite à mão.\n" + yaml.dump(out, Dumper=D, allow_unicode=True, sort_keys=False, width=110), encoding="utf-8")
    new = [n for n in nodes if not n.get("_merge_only")]
    print(f"comissões: novas={len(new)} curadas atualizadas={len(nodes)-len(new)} posições={len(positions)} pessoas-vínculos={sum(len(v) for v in positions.values())}")
    for nid, ppl in positions.items():
        pres = [p["name"] for p in ppl if p.get("role") == "Presidente"]
        print(f"  {nid}: {len(ppl)} ({'presid. ' + pres[0] if pres else 'sem presidente'})")
if __name__ == "__main__": main()
