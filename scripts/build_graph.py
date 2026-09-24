#!/usr/bin/env python3
"""Valida os YAML de data/ e gera build/graph.br.json e build/graph.br.js.

Uso: .venv/bin/python scripts/build_graph.py
Sai com código 1 se houver erro de validação. Avisos não bloqueiam.
"""
import glob, json, sys, hashlib, datetime, pathlib
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA, OUT = ROOT / "data", ROOT / "build"
OUT.mkdir(exist_ok=True)

layout = yaml.safe_load(open(DATA / "layout.yaml", encoding="utf-8"))
SECTORS = {s["id"] for s in layout["sectors"]}
NODE_TYPES = set(layout["node_types"])
EDGE_TYPES = set(layout["edge_types"])
INDIRETA = {"autarquia", "fundacao", "empresa_publica", "sociedade_economia_mista", "agencia_reguladora"}

errors, warnings = [], []
nodes = {}
for f in sorted(glob.glob(str(DATA / "nodes" / "*.yaml"))):
    for n in yaml.safe_load(open(f, encoding="utf-8")) or []:
        n["_file"] = pathlib.Path(f).name
        if n["id"] in nodes:
            errors.append(f"id duplicado: {n['id']} ({n['_file']} e {nodes[n['id']]['_file']})")
        nodes[n["id"]] = n

def err(msg): errors.append(msg)
def warn(msg): warnings.append(msg)

# ---- camada gerada (SIORG): curadoria manda; o gerado preenche o que falta
import unicodedata, re
def norm(s): return re.sub(r"[^a-z0-9]+", " ", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()).strip()
gen_path = DATA / "generated" / "siorg.yaml"
merge_report = {"matched": 0, "added": 0, "unmatched_curated": []}
if gen_path.exists():
    gen = yaml.safe_load(open(gen_path, encoding="utf-8")) or {}
    gen_nodes = (gen.get("nodes") or []) + (gen.get("collegiate") or [])
    by_key = {}
    for n in nodes.values():
        if n["type"] == "dept_head": continue
        for k in [n.get("name")] + list(n.get("aliases") or []):
            if k: by_key.setdefault(norm(k), n)
    gen_to_id = {}; matched = set()
    for g in gen_nodes:
        keys = [norm(g["name"])] + [norm(a) for a in (g.get("aliases") or [])]
        hit = next((by_key[k] for k in keys if k in by_key and len(k) > 1), None)
        if hit:
            merge_report["matched"] += 1; gen_to_id[g["id"]] = hit["id"]; matched.add(g["id"])
            hit["siorg_code"] = g.get("siorg_code")
            if not hit.get("official_url") and g.get("official_url"): hit["official_url"] = g["official_url"]
            if g.get("description"): hit["siorg_description"] = g["description"]
            for a in g.get("aliases") or []:
                if a and norm(a) not in [norm(x) for x in hit.get("aliases") or []]: hit.setdefault("aliases", []).append(a)
        else:
            gen_to_id[g["id"]] = g["id"]
    for g in gen_nodes:
        if g["id"] in matched: continue
        if g["id"] in nodes: warn(f"gerado {g['id']} colide com id curado; ignorado"); continue
        n = dict(g); n["parent"] = gen_to_id.get(g.get("siorg_parent_id"), g.get("siorg_parent_id")) if g.get("siorg_parent_id") else None
        n.pop("siorg_parent_id", None); n["_file"] = "generated/siorg.yaml"
        if n.get("subtype") == "tribunal" or (n["sector"] == "judiciario" and n["name"].startswith(("Tribunal", "Justiça", "Conselho", "Superior", "Supremo"))): n["subtype"] = "tribunal"
        if n["sector"] != "executivo" and not n.get("parent"): n["ring"] = 2
        if n.get("subtype") == "instituicao_de_ensino": n["cluster"] = "ensino"
        if n["type"] == "commission": n["cluster"] = "colegiado"
        if re.match(r"^Se[çc][aã]o Judici[aá]ria|^Justi[çc]a Federal de Primeiro Grau", n["name"]): n["subtype"] = "secao_judiciaria"; n["cluster"] = "secao_judiciaria"; n["ring"] = 4
        if re.match(r"^Tribunal Regional do Trabalho", n["name"]): n["subtype"] = "tribunal"; n["cluster"] = "trt"; n["parent"] = "br-tribunais-regionais-do-trabalho"; n["ring"] = 4
        if re.match(r"^Tribunal Regional Eleitoral", n["name"]): n["subtype"] = "tribunal"; n["cluster"] = "tre"; n["parent"] = "br-tribunais-regionais-eleitorais"; n["ring"] = 4
        if re.match(r"^Tribunal de Justi[çc]a do Distrito Federal", n["name"]): n["subtype"] = "tribunal"; n["parent"] = "br-superior-tribunal-de-justica"; n["ring"] = 3
        nodes[n["id"]] = n; merge_report["added"] += 1
    for _ in range(4):
        for n in nodes.values():
            if n.get("source") == "siorg" and n.get("parent") in nodes:
                pr = nodes[n["parent"]].get("ring") or 0
                if n["type"] != "dept_head" and (n.get("ring") or 0) <= pr: n["ring"] = min(pr + 1, 4)
    for n in nodes.values():
        if n["type"] in ("department",) and n.get("sector") == "executivo" and not n.get("siorg_code") and n.get("subtype") not in ("orgao_presidencia",):
            merge_report["unmatched_curated"].append(n["id"])

# ---- camada gerada (comissões do Congresso): nós novos + composição
com_path = DATA / "generated" / "comissoes.yaml"
if com_path.exists():
    com = yaml.safe_load(open(com_path, encoding="utf-8")) or {}
    for g in com.get("nodes") or []:
        if g.get("_merge_only"):
            if g["id"] in nodes and g.get("seats_count"): nodes[g["id"]]["seats_count"] = g["seats_count"]
            continue
        if g["id"] in nodes: warn(f"comissão gerada {g['id']} colide com id curado; ignorada"); continue
        n = dict(g); n["_file"] = "generated/comissoes.yaml"; nodes[n["id"]] = n; merge_report["added"] += 1

# ---- camada gerada (segundo escalão dos ministérios): secretarias + cargo de secretário + ocupantes das páginas oficiais
se_path = DATA / "generated" / "segundo-escalao.yaml"
_se_n = 0
if se_path.exists():
    se = yaml.safe_load(open(se_path, encoding="utf-8")) or {}
    _skip = {x.get("no_existente") + "-sec" for x in (se.get("resumo") or {}).get("ja_no_grafo") or [] if x.get("no_existente")}
    _skip_nm = {(x.get("orgao"), norm(x.get("unidade") or "")) for x in (se.get("resumo") or {}).get("ja_no_grafo") or []}
    _added = set()
    _dup = __import__("collections").Counter(norm(g.get("name") or "") for g in se.get("nodes") or [])
    for g in se.get("nodes") or []:
        if g["id"] in _skip or g["id"] in nodes or g.get("parent") not in nodes or (g.get("parent"), norm(g.get("name") or "")) in _skip_nm: continue
        n = dict(g); n["_file"] = "generated/segundo-escalao.yaml"
        if _dup[norm(n.get("name") or "")] > 1:  # "Secretaria-Executiva" existe em 40+ órgãos: o nome leva o órgão
            pn = nodes[n["parent"]]["name"]; art = "do" if re.match(r"(Ministério|Gabinete)", pn) else "da"
            n["aliases"] = list(dict.fromkeys((n.get("aliases") or []) + [n["name"]])); n["name"] = f"{n['name']} {art} {pn}"
        nodes[n["id"]] = n; _added.add(n["id"]); merge_report["added"] += 1; _se_n += 1
    for g in se.get("positions") or []:
        if g["id"] in nodes or g.get("head_of") not in _added: continue
        n = dict(g); n["_file"] = "generated/segundo-escalao.yaml"; ppl = n.pop("people", None) or []
        for q in ppl:
            if q.get("started_at") is not None: q["started_at"] = str(q["started_at"])
            if q.get("checked_at") is not None: q["checked_at"] = str(q["checked_at"])
            q.setdefault("source", "oficial"); q.setdefault("entry_mode", "nomeado")
        if ppl: n["people"] = ppl
        nodes[n["id"]] = n; merge_report["added"] += 1

# ---- camada gerada (dirigentes de tribunais regionais, estatais, autarquias, fundações e instituições de ensino)
di_path = DATA / "generated" / "dirigentes.yaml"
_di_n = 0
if di_path.exists():
    di = yaml.safe_load(open(di_path, encoding="utf-8")) or {}
    for g in di.get("nodes") or []:
        if g["id"] in nodes: continue
        n = dict(g); n["_file"] = "generated/dirigentes.yaml"; nodes[n["id"]] = n; merge_report["added"] += 1
    for g in di.get("positions") or []:
        if g["id"] in nodes or g.get("head_of") not in nodes: continue
        n = dict(g); n["_file"] = "generated/dirigentes.yaml"; ppl = n.pop("people", None) or []
        for q in ppl:
            for k in ("started_at", "checked_at"):
                if q.get(k) is not None: q[k] = str(q[k])
            q.setdefault("source", "oficial"); q.setdefault("entry_mode", "nomeado")
        if ppl: n["people"] = ppl
        nodes[n["id"]] = n; merge_report["added"] += 1; _di_n += 1

# ---- validação de nós
for n in nodes.values():
    i = n["id"]
    if not i.startswith("br-"): err(f"{i}: id sem prefixo br-")
    if n.get("type") not in NODE_TYPES: err(f"{i}: type inválido {n.get('type')}")
    if n["type"] != "constituency" and not n.get("name"): err(f"{i}: sem name")
    if len((n.get("description") or "")) < 40: err(f"{i}: descrição curta ou ausente")
    if not n.get("cite"): err(f"{i}: sem cite")
    if n["type"] == "dept_head":
        h = n.get("head_of")
        if h not in nodes: err(f"{i}: head_of inexistente {h}")
        for k in ("nomeado_por", "indicado_por", "eleito_por"):
            if n.get(k) and n[k] not in nodes: err(f"{i}: {k} inexistente {n[k]}")
        # herda setor e anel do órgão chefiado
        if h in nodes:
            n["sector"] = nodes[h].get("sector"); n["ring"] = nodes[h].get("ring")
    else:
        if n["type"] != "constituency" and n.get("sector") not in SECTORS: err(f"{i}: sector inválido {n.get('sector')}")
        if n.get("ring") not in (0, 1, 2, 3, 4): err(f"{i}: ring inválido {n.get('ring')}")
        p = n.get("parent")
        if p and p not in nodes: err(f"{i}: parent inexistente {p}")
        if p and p in nodes and nodes[p].get("ring", 0) >= n.get("ring", 0) and n["type"] not in ("commission", "advisory") and n.get("source") != "siorg":
            warn(f"{i}: anel {n.get('ring')} não é maior que o do parent {p} (anel {nodes[p].get('ring')})")
    if n.get("verified") is False: n["verified"] = False
    else: n["verified"] = True

# ---- ocupantes (camada gerada: Câmara e Senado)
def _slug(s): return re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()).strip("-")
sources = [("generated", DATA / "generated" / "parlamentares.yaml"), ("generated", DATA / "generated" / "comissoes.yaml")]
# curados (páginas oficiais) têm precedência sobre o Wikidata
of_path = DATA / "ocupantes-oficiais.yaml"
if of_path.exists():
    for block in yaml.safe_load(open(of_path, encoding="utf-8")) or []:
        for pid, people in (block.get("positions") or {}).items():
            if pid not in nodes: warn(f"ocupantes-oficiais: cargo inexistente {pid}"); continue
            if nodes[pid].get("people") and nodes[pid]["people"][0].get("source") != "oficial": continue
            recs = []
            for p in people:
                if isinstance(p, str): p = {"name": p}
                recs.append({"id": "br-p-" + _slug(p["name"]), "name": p["name"], "started_at": str(p["started_at"]) if p.get("started_at") else None, "entry_mode": block.get("entry_mode", "nomeado"), "acting": bool(p.get("acting")),
                             "note": p.get("note"), "source": "oficial", "source_url": block["source"], "checked_at": str(block.get("checked_at")), "verified": True})
            nodes[pid]["people"] = recs
    for n in nodes.values():
        if n["type"] == "dept_head" and n.get("people") and n["people"][0].get("source") == "oficial" and n.get("seats", 1) > len(n["people"]):
            n["vacant_seats"] = n["seats"] - len(n["people"])
sources.append(("generated", DATA / "generated" / "dou-assinaturas.yaml"))
sources.append(("generated", DATA / "generated" / "wikipedia.yaml"))
# aprovados pelo Senado (sabatina) sem ocupante conhecido: fallback com aviso, só para cargos sabatinados de mandato fixo
_sab_p = DATA / "generated" / "sabatinas.yaml"
if _sab_p.exists():
    _sab = (yaml.safe_load(open(_sab_p, encoding="utf-8")) or {}).get("sabatinas") or []
    _by_pos = {}
    for r in sorted(_sab, key=lambda r: str(r.get("deliberacao") or ""), reverse=True):
        pid = r.get("position_id"); nm = r.get("name")
        if not pid or pid not in nodes or nodes[pid]["type"] != "dept_head" or not nm or r.get("resultado") != "APROVADA_NO_PLENARIO": continue
        n = nodes[pid]
        if not n.get("sabatina") or n.get("sector") != "executivo" or not n.get("mandato_anos"): continue
        d = str(r.get("deliberacao") or "")
        if d < (datetime.date.today() - datetime.timedelta(days=365 * n["mandato_anos"])).isoformat(): continue
        lst = _by_pos.setdefault(pid, [])
        if any(norm(x["name"]) == norm(nm) for x in lst) or len(lst) >= (n.get("seats") or 1): continue
        lst.append({"id": "br-p-" + _slug(nm), "name": nm, "started_at": None, "entry_mode": "nomeado", "source": "sabatina", "source_url": r.get("url"), "verified": False,
                    "note": f"Aprovado pelo Senado em {d[8:10]}/{d[5:7]}/{d[:4]} ({r.get('msf')}); posse ainda não conferida em página oficial."})
    _sab_out = DATA / "generated" / "ocupantes-sabatinas.yaml"
    _sab_out.write_text("# GERADO por scripts/build_graph.py a partir de sabatinas.yaml. Não edite à mão.\n" + yaml.dump({"positions": _by_pos}, allow_unicode=True, sort_keys=False, width=110), encoding="utf-8")
    sources.append(("generated", _sab_out))
sources.append(("generated", DATA / "generated" / "ocupantes.yaml"))
# último recurso: o ato de nomeação no Diário Oficial, buscado pelo nome do cargo (etl/ocupantes_dou.py)
sources.append(("generated", DATA / "generated" / "ocupantes-dou.yaml"))
for _, ppl_path in sources:
    if not ppl_path.exists(): continue
    ppl = yaml.safe_load(open(ppl_path, encoding="utf-8")) or {}
    for pid, people in (ppl.get("positions") or {}).items():
        if pid not in nodes: warn(f"ocupantes para cargo inexistente {pid}"); continue
        if nodes[pid].get("people"): continue
        for p in people:
            if p.get("started_at") is not None: p["started_at"] = str(p["started_at"])
            if p.get("name"): p["name"] = re.sub(r"\b(De|Da|Do|Das|Dos|E)\b", lambda m: m.group(1).lower(), p["name"])
        # Wikidata: no Executivo, ocupante com início anterior ao governo atual (2023) é considerado desatualizado
        if nodes[pid].get("sector") == "executivo":
            people = [p for p in people if p.get("source") != "wikidata" or (p.get("started_at") or "") >= "2023-01-01"]
        if people: nodes[pid]["people"] = people

# ---- orçamento por programa (execução do SIAFI) e transferências a estados e municípios, anexados ao órgão
_pg_p = DATA / "generated" / "programas.yaml"
_pg_n = 0
if _pg_p.exists():
    _pg = yaml.safe_load(open(_pg_p, encoding="utf-8")) or {}
    for _nid, _o in (_pg.get("orgaos") or {}).items():
        if _nid not in nodes: continue
        _ant = _o.get("anterior") or {}
        nodes[_nid]["programas"] = {"ano": _o.get("ano"), "escopo": _o.get("escopo"), "codigo": _o.get("codigo"),
                                    "total_empenhado": _o.get("total_empenhado"), "total_pago": _o.get("total_pago"),
                                    "programas_total": _o.get("programas_total"), "outros": _o.get("outros"),
                                    "lista": [{k: pr.get(k) for k in ("codigo", "nome", "empenhado", "pago", "acoes_top")} for pr in (_o.get("programas") or [])[:12]],
                                    "anterior": {"ano": _ant.get("ano"), "total_pago": _ant.get("total_pago")} if _ant else None,
                                    "fonte": _pg.get("fonte"), "generated_at": str(_pg.get("generated_at") or "")[:10]}
        _pg_n += 1
_tr_p = DATA / "generated" / "transferencias.yaml"
transferencias = None
_tr_n = 0
if _tr_p.exists():
    _tr = yaml.safe_load(open(_tr_p, encoding="utf-8")) or {}
    for _nid, _o in (_tr.get("por_orgao") or {}).items():
        if _nid not in nodes: continue
        nodes[_nid]["transferencias"] = dict(_o, fonte=_tr.get("fonte"), generated_at=str(_tr.get("generated_at") or "")[:10])
        _tr_n += 1
    _rs = _tr.get("resumo") or {}
    transferencias = {"generated_at": str(_tr.get("generated_at") or "")[:10], "fonte": _tr.get("fonte"), "fonte_url": _tr.get("fonte_url"),
                      "anos": _tr.get("anos"), "por_uf": _tr.get("por_uf"),
                      "total_por_ano": _rs.get("total_por_ano"), "maiores_municipios": (_rs.get("maiores_municipios") or [])[:12],
                      "maiores_por_habitante": (_rs.get("maiores_por_habitante") or [])[:10], "criterio": _rs.get("criterio"),
                      "populacao_ibge": _rs.get("populacao_ibge"), "orgaos": _tr_n}

# ---- data do ato de nomeação encontrada no Diário Oficial (etl/posses.py), para ocupantes sem data
_ps_p = DATA / "generated" / "posses.yaml"
_posses = ((yaml.safe_load(open(_ps_p, encoding="utf-8")) or {}).get("posses") or {}) if _ps_p.exists() else {}

# ---- quanto o cargo paga, segundo a lei (subsídio e benefícios), anexado ao cargo
_sb_p = DATA / "generated" / "subsidios.yaml"
_sb_n = 0
if _sb_p.exists():
    _sb = yaml.safe_load(open(_sb_p, encoding="utf-8")) or {}
    for _cid, _c in (_sb.get("cargos") or {}).items():
        if _cid not in nodes: continue
        def _iso(v):
            if isinstance(v, (datetime.date, datetime.datetime)): return v.isoformat()
            if isinstance(v, dict): return {k2: _iso(v2) for k2, v2 in v.items()}
            if isinstance(v, list): return [_iso(x) for x in v]
            return v
        nodes[_cid]["subsidio"] = {k: _iso(_c.get(k)) for k in ("subsidio_mensal_bruto", "vigencia_desde", "norma", "norma_url", "beneficios", "familia", "checked_at", "observacao") if _c.get(k) is not None}
        _sb_n += 1

# ---- composição dos colegiados (norma que cria cada conselho), anexada ao nó
_cg_p = DATA / "generated" / "colegiados.yaml"
_cg_n = 0
if _cg_p.exists():
    _cg = yaml.safe_load(open(_cg_p, encoding="utf-8")) or {}
    for _cid, _c in (_cg.get("colegiados") or {}).items():
        if _cid not in nodes: warn(f"colegiados: nó inexistente {_cid}"); continue
        _ms = _c.get("membros") or []
        for _m in _ms:  # atualiza o ocupante a partir do estado atual do grafo, não do YAML
            _cid2 = _m.get("cargo_id")
            if _cid2 and _cid2 in nodes:
                _pp = (nodes[_cid2].get("people") or [{}])[0]
                _m["pessoa_nome"] = _pp.get("name"); _m["pessoa_id"] = _pp.get("id")
        nodes[_cid]["composicao"] = {k: _c.get(k) for k in ("norma", "norma_url", "presidido_por", "presidido_por_nome", "nota", "atualizado_em", "vagas_sociedade", "assentos_cargo") if _c.get(k) is not None}
        nodes[_cid]["composicao"]["membros"] = _ms
        _cg_n += 1

# ---- histórico de ocupantes do cargo (Wikidata), anexado ao cargo
_hi_p = DATA / "generated" / "historico.yaml"
_hi_n = 0
if _hi_p.exists():
    _hi = (yaml.safe_load(open(_hi_p, encoding="utf-8")) or {}).get("cargos") or {}
    for pid, h in _hi.items():
        if pid not in nodes: continue
        mand = [m for m in (h.get("mandatos") or []) if m.get("inicio")]
        mand = sorted(mand, key=lambda m: str(m.get("inicio")))
        mand = [m for m in mand if str(m.get("fim") or "9999") >= "1985-03-15"]
        if not mand: continue
        nodes[pid]["historico"] = {"qid": h.get("qid"), "rota": h.get("rota"), "ocupantes": len({m.get("qid") for m in mand}), "mediana_dias": h.get("mediana_dias"),
                                   "por_presidente": h.get("por_presidente") or {}, "wikidata_atualizado": bool(h.get("wikidata_atualizado")),
                                   "mandatos": [{k: m.get(k) for k in ("qid", "nome", "inicio", "fim", "dias", "interino", "presidente", "papel") if m.get(k) not in (None, False)} for m in mand[-40:]]}
        _hi_n += 1
    # ocupantes atuais conhecidos pela página oficial que o Wikidata ainda não registra entram com a data de posse oficial
    def _sp(a, b):
        ta, tb = norm(a).split(), norm(b).split()
        return bool(ta) and (ta == tb or (len(ta) >= 2 and len(tb) >= 2 and ta[0] == tb[0] and ta[-1] == tb[-1]) or (len(ta) >= 2 and len(tb) >= 2 and all(t in tb for t in ta)) or all(t in ta for t in tb))
    for pid, n in nodes.items():
        h = n.get("historico")
        if not h: continue
        for p in n.get("people") or []:
            if p.get("source") != "oficial" or not p.get("started_at"): continue
            if any(_sp(m.get("nome") or "", p["name"]) for m in h["mandatos"]): continue
            h["mandatos"].append({"nome": p["name"], "inicio": str(p["started_at"])[:10], "fonte": "oficial"})
        h["mandatos"].sort(key=lambda m: str(m.get("inicio")))
        h["ocupantes"] = len({(m.get("qid") or m.get("nome")) for m in h["mandatos"]})

# ---- sabatinas (Senado) anexadas ao cargo
sab_path = DATA / "generated" / "sabatinas.yaml"
sabatinas = []
if sab_path.exists():
    sabatinas = (yaml.safe_load(open(sab_path, encoding="utf-8")) or {}).get("sabatinas") or []
    for r in sabatinas:
        pid = r.get("position_id")
        if pid and pid in nodes: nodes[pid].setdefault("sabatinas", []).append({k: r.get(k) for k in ("msf", "name", "cargo", "apresentacao", "deliberacao", "resultado", "tramitando", "votos_sim", "votos_nao", "abstencoes", "secreta", "url")})

# ---- orçamento (Portal da Transparência)
orc_path = DATA / "generated" / "orcamento.yaml"
if orc_path.exists():
    orc = yaml.safe_load(open(orc_path, encoding="utf-8")) or {}
    for nid, years in (orc.get("nodes") or {}).items():
        if nid in nodes: nodes[nid]["budget"] = years

# ---- arestas derivadas
edges = []
def add(type_, frm, to, cite, note=None, seats=None, source="derivado", verified=True):
    if type_ not in EDGE_TYPES: err(f"aresta com type inválido {type_}"); return
    if frm not in nodes or to not in nodes: err(f"aresta {type_} {frm} -> {to}: nó inexistente"); return
    eid = hashlib.sha1(f"{type_}|{frm}|{to}|{note or ''}".encode()).hexdigest()[:8]
    e = {"id": eid, "type": type_, "from": frm, "to": to, "cite": cite, "source": source}
    if note: e["note"] = note
    if seats: e["seats"] = seats
    if not verified: e["verified"] = False
    edges.append(e)

for n in nodes.values():
    i = n["id"]
    if n["type"] == "dept_head":
        add("chefia", i, n["head_of"], n["cite"], verified=n["verified"])
        if n.get("nomeado_por"):
            add("nomeia", n["nomeado_por"], i, n["cite"], seats=n.get("seats"), verified=n["verified"])
        if n.get("sabatina"):
            add("sabatina", "br-senado-federal", i, "CF/88 art. 52 III-IV; " + n["cite"], seats=n.get("seats"), verified=n["verified"])
        if n.get("indicado_por"):
            add("indica", n["indicado_por"], i, n["cite"], note="Indica o nome; a eleição cabe ao Conselho de Administração", verified=n["verified"])
        if n.get("eleito_por"):
            add("indica", n["eleito_por"], i, n["cite"], note="Eleito pelos membros do órgão", seats=n.get("seats"), verified=n["verified"])
    elif n.get("parent"):
        p = nodes[n["parent"]]
        if n.get("subtype") in INDIRETA:
            add("supervisiona", p["id"], i, "DL 200/1967 arts. 19-20; " + n["cite"], verified=n["verified"])
        else:
            add("integra", i, p["id"], n["cite"], verified=n["verified"])

for f in sorted(glob.glob(str(DATA / "edges" / "*.yaml"))):
    for e in yaml.safe_load(open(f, encoding="utf-8")) or []:
        if e.get("disabled"): continue
        if not e.get("cite"): err(f"aresta {e.get('type')} {e.get('from')} -> {e.get('to')}: sem cite")
        add(e["type"], e["from"], e["to"], e.get("cite", ""), e.get("note"), e.get("seats"), source="explicito", verified=e.get("verified", True))

# duplicatas
seen = set()
for e in edges:
    k = (e["type"], e["from"], e["to"])
    if k in seen: warn(f"aresta duplicada {k}")
    seen.add(k)

# ---- índices por nó
for n in nodes.values():
    n["edges"] = []; n["connected"] = []
    n.pop("_file", None)
for e in edges:
    for side in ("from", "to"):
        nodes[e[side]]["edges"].append(e["id"])
    a, b = nodes[e["from"]], nodes[e["to"]]
    if e["to"] not in a["connected"]: a["connected"].append(e["to"])
    if e["from"] not in b["connected"]: b["connected"].append(e["from"])
for n in nodes.values():
    n["children"] = sorted(m["id"] for m in nodes.values() if m.get("parent") == n["id"])
    n["positions"] = sorted(m["id"] for m in nodes.values() if m.get("head_of") == n["id"])

print(f"SIORG: {merge_report['matched']} curados casados, {merge_report['added']} nós adicionados; curados do Executivo sem código SIORG: {len(merge_report['unmatched_curated'])}")
if merge_report["unmatched_curated"]: print("   ", ", ".join(merge_report["unmatched_curated"][:40]))
if errors:
    print("ERROS:"); [print("  -", e) for e in errors]
if warnings:
    print("AVISOS:"); [print("  -", w) for w in warnings]
if errors: sys.exit(1)

# ---- estatísticas
from collections import Counter
by_type = Counter(n["type"] for n in nodes.values())
by_sector = Counter(n.get("sector") for n in nodes.values() if n["type"] != "dept_head" and n.get("sector"))
by_subtype = Counter(n.get("subtype") for n in nodes.values() if n.get("subtype"))
by_edge = Counter(e["type"] for e in edges)
seats = sum(n.get("seats", 0) for n in nodes.values() if n["type"] == "dept_head")
filled = sum(len(n.get("people") or []) for n in nodes.values() if n["type"] == "dept_head")
vacant = sum(n.get("vacant_seats", 0) for n in nodes.values() if n["type"] == "dept_head")
filled_official = sum(len(n.get("people") or []) for n in nodes.values() if n["type"] == "dept_head" and (n.get("people") or [{}])[0].get("source") in ("oficial", None) and n.get("people"))
sabat = sum(n.get("seats", 0) for n in nodes.values() if n["type"] == "dept_head" and n.get("sabatina"))
unverified = sum(1 for n in nodes.values() if not n["verified"] and n.get("source") != "siorg")
from_siorg = sum(1 for n in nodes.values() if n.get("source") == "siorg")
stats = {"nodes": len(nodes), "edges": len(edges), "by_type": dict(by_type), "by_sector": dict(by_sector),
         "by_subtype": dict(by_subtype), "by_edge_type": dict(by_edge), "seats_total": seats, "seats_filled": filled, "seats_vacant_known": vacant, "seats_sabatina": sabat,
         "unverified": unverified, "from_siorg": from_siorg, "siorg_matched": merge_report["matched"], "generated_at": datetime.date.today().isoformat()}
news_path = DATA / "generated" / "noticias.json"
news, power = [], []
if news_path.exists():
    store = json.load(open(news_path, encoding="utf-8"))
    arts = sorted(store.get("articles", {}).values(), key=lambda a: a.get("date") or "", reverse=True)
    cutoff90 = (datetime.date.today() - datetime.timedelta(days=90)).isoformat()
    def mark(text, a):
        """Marca no texto os nomes/siglas das entidades e pessoas ligadas ao artigo: <a href="#id">."""
        t = html_mod.escape(text)
        targets = []
        for eid in a.get("entities") or []:
            n = nodes.get(eid)
            if not n: continue
            for al in [n["name"]] + list(n.get("aliases") or []):
                if len(al) >= 3 and (al.isupper() or len(al.split()) >= 2): targets.append((al, eid))
        for p in a.get("people") or []:
            if p.get("name"): targets.append((p["name"], p.get("position")))
        targets.sort(key=lambda x: -len(x[0]))
        for al, tid in targets:
            if not tid: continue
            t2 = re.sub(r"(?<![\w>])(" + re.escape(html_mod.escape(al)) + r")(?![\w<])", lambda m: f'<a href="#{tid}">{m.group(1)}</a>', t, count=1, flags=re.I)
            if t2 != t: t = t2
        return t
    import html as html_mod
    for a in arts:
        first = re.split(r"(?<=[.!?])\s+", (a.get("summary") or "").strip())[0] if a.get("summary") else ""
        base = first if 40 <= len(first) <= 260 else (a.get("summary") or "")[:220]
        a["summary_html"] = mark(base, a) if base else ""
        a["title_html"] = mark(a.get("title") or "", a)
    news = [a for a in arts if a.get("entities") or a.get("people")][:60]
    mentions = {}
    today_d = datetime.date.today(); cutoff7 = (today_d - datetime.timedelta(days=7)).isoformat()
    for a in sorted(arts, key=lambda a: a.get("date") or "", reverse=True):
        if (a.get("date") or "") < cutoff90: continue
        for p in a.get("people") or []:
            m = mentions.setdefault(p["id"], {"id": p["id"], "name": p["name"], "position": p.get("position"), "articles": 0, "recent": 0, "last": None, "weeks": [0] * 12, "latest": None})
            m["articles"] += 1
            if (a.get("date") or "") >= cutoff7: m["recent"] += 1
            if not m["latest"]: m["latest"] = {"title": a.get("title"), "url": a.get("url"), "source": a.get("publication"), "date": a.get("date")}
            m["last"] = max(m["last"] or "", a.get("date") or "")
            try:
                wk = (today_d - datetime.date.fromisoformat(a["date"])).days // 7
                if 0 <= wk < 12: m["weeks"][11 - wk] += 1
            except Exception: pass
    for m in mentions.values():
        m["heat"] = round(m["recent"] * 2 + m["articles"] / 10, 2)
    power = sorted(mentions.values(), key=lambda m: (-m["heat"], -m["articles"]))[:20]
    # relações do grafo entre pessoas do power map (quem nomeia quem), como as linhas do CivLab
    pos_of = {m["position"]: m["id"] for m in power if m.get("position")}
    power_links = []
    for e in edges:
        if e["type"] in ("nomeia", "chefia", "sabatina", "indica") and e["from"] in pos_of and e["to"] in pos_of:
            power_links.append({"from": pos_of[e["from"]], "to": pos_of[e["to"]], "type": e["type"]})
    stats["power_links"] = len(power_links)
    stats["articles_90d"] = sum(1 for a in arts if (a.get("date") or "") >= cutoff90); stats["news_sources"] = len(store.get("feeds") or [])
stats["sabatinas"] = len(sabatinas)
# mudanças: sabatinas deliberadas + posses recentes (started_at) como eventos
changes = []
_sab_orfas = 0
for r in sabatinas:
    # o cargo pode ter sido extinto ou renomeado entre a sabatina e o build: a mudança sai da lista, não derruba o build
    if r.get("deliberacao") and r.get("position_id"):
        _nd = nodes.get(r["position_id"])
        if not _nd: _sab_orfas += 1; continue
        changes.append({"kind": "sabatina", "date": r["deliberacao"], "personName": r.get("name"), "positionId": r["position_id"], "positionName": _nd["name"], "result": r.get("resultado"), "votes": [r.get("votos_sim"), r.get("votos_nao")], "sourceUrl": r.get("url")})
if _sab_orfas: print(f"   aviso: {_sab_orfas} sabatina(s) apontam para cargo que não existe mais; fora da lista de mudanças")
for n in nodes.values():
    if n["type"] != "dept_head" and n["type"] != "elected": continue
    for p in n.get("people") or []:
        if p.get("started_at") and p["started_at"] >= "2025-01-01" and n["id"] not in ("br-deputado-federal", "br-senador"):
            changes.append({"kind": "posse", "date": p["started_at"], "personName": p.get("name"), "positionId": n["id"], "positionName": n["name"], "acting": p.get("acting"), "sourceUrl": p.get("source_url")})
# ---- histórico de ocupantes (tenures): compara com a execução anterior e gera pares saiu/entrou
ten_path = DATA / "generated" / "tenures.json"
today_s = datetime.date.today().isoformat()
tenures = json.load(open(ten_path, encoding="utf-8")) if ten_path.exists() else {"positions": {}, "first_run": today_s}
first_run = tenures.get("first_run") == today_s and not ten_path.exists()
for n in nodes.values():
    if n["type"] not in ("dept_head", "elected"): continue
    if n["id"] in ("br-deputado-federal", "br-senador"): continue
    cur = {p["id"]: p for p in (n.get("people") or []) if p.get("id")}
    hist = tenures["positions"].setdefault(n["id"], {})
    # saídas: quem estava e não está mais
    for pid, rec in list(hist.items()):
        if rec.get("ended") is None and pid not in cur:
            rec["ended"] = today_s
            if not first_run:
                changes.append({"kind": "saida", "date": today_s, "personName": rec["name"], "positionId": n["id"], "positionName": n["name"], "sourceUrl": rec.get("source_url"), "observed": True})
    # entradas: quem está e não estava
    for pid, p in cur.items():
        if pid not in hist or hist[pid].get("ended"):
            prev = [r for r in hist.values() if r.get("ended") and r.get("ended") >= (today_s if first_run else "0")]
            pred = sorted(prev, key=lambda r: r["ended"])[-1]["name"] if prev and (n.get("seats") or 1) == 1 else None
            hist[pid] = {"name": p.get("name"), "first_seen": today_s, "started_at": p.get("started_at"), "source": p.get("source", "api"), "source_url": p.get("source_url"), "ended": None}
            if not first_run:
                changes.append({"kind": "entrada", "date": p.get("started_at") or today_s, "personName": p.get("name"), "positionId": n["id"], "positionName": n["name"], "predecessorName": pred, "acting": p.get("acting"), "sourceUrl": p.get("source_url"), "observed": True})
        else:
            hist[pid]["last_seen"] = today_s
tenures["updated_at"] = today_s
json.dump(tenures, open(ten_path, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
# contadores
acting = sum(1 for n in nodes.values() if n["type"] == "dept_head" for p in (n.get("people") or []) if p.get("acting") or re.search(r"substitut|interin", (p.get("note") or "") + (p.get("role") or ""), re.I))
vacant_known = sum(n.get("vacant_seats", 0) for n in nodes.values() if n["type"] == "dept_head")
stats["acting_officials"] = acting; stats["vacant_seats_known"] = vacant_known
stats["last_change"] = max((c["date"] for c in changes if c.get("date")), default=None)

dou_path = DATA / "generated" / "dou.json"
if dou_path.exists():
    for a in (json.load(open(dou_path, encoding="utf-8")).get("acts") or {}).values():
        for r in a.get("records") or []:
            if not r.get("position_id") or r["position_id"] not in nodes: continue
            kind = {"NOMEAR": "nomeacao", "EXONERAR": "exoneracao", "DESIGNAR": "designacao", "DISPENSAR": "exoneracao"}.get(r["verb"], "nomeacao")
            changes.append({"kind": kind, "date": a["date"], "personName": r.get("name"), "positionId": r["position_id"], "positionName": nodes[r["position_id"]]["name"], "cargoText": r.get("cargo"), "sourceUrl": a.get("url"), "act": a.get("title")})
            nodes[r["position_id"]].setdefault("dou", []).append({"date": a["date"], "verb": r["verb"], "name": r.get("name"), "cargo": r.get("cargo"), "url": a.get("url"), "act": a.get("title")})
changes.sort(key=lambda c: c["date"], reverse=True)
# ---- trajetória até o cargo: quem chamou, quando, sabatina, posse, fim do mandato
_pres = yaml.safe_load(open(DATA / "presidentes.yaml", encoding="utf-8")) or []
def president_at(d):
    for p in _pres:
        if str(p["start"]) <= d and (not p.get("end") or d <= str(p["end"])): return p
    return None
_wd_by_pos = {}
_wd_p = DATA / "generated" / "ocupantes.yaml"
if _wd_p.exists():
    for pid, ppl in ((yaml.safe_load(open(_wd_p, encoding="utf-8")) or {}).get("positions") or {}).items():
        for p in ppl:
            if p.get("name") and p.get("started_at"): _wd_by_pos.setdefault(pid, {})[norm(p["name"])] = str(p["started_at"])
def same_person(a, b):
    """'Cristiano Zanin' ~ 'Cristiano Zanin Martins': o nome mais curto (>= 2 palavras) está contido, em ordem, no mais longo."""
    ta, tb = norm(a).split(), norm(b).split()
    if not ta or not tb: return False
    if ta == tb: return True
    s, l = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if len(s) < 2 or s[0] != l[0]: return False
    it = iter(l); return all(w in it for w in s)
ELECTIONS = {"2023": "2022-10-02", "2019": "2018-10-07", "2015": "2014-10-05", "2027": "2026-10-04"}
def _add_years(d, y):
    try: return (datetime.date.fromisoformat(d).replace(year=datetime.date.fromisoformat(d).year + y) - datetime.timedelta(days=1)).isoformat()
    except Exception: return None
_nasc_p = DATA / "generated" / "nascimentos.yaml"
_nasc = ((yaml.safe_load(open(_nasc_p, encoding="utf-8")) or {}).get("people") or {}) if _nasc_p.exists() else {}
def _plus_years(d, y):
    try: dd = datetime.date.fromisoformat(str(d)[:10]); return dd.replace(year=dd.year + y).isoformat()
    except Exception: return None
for n in nodes.values():
    if n["type"] not in ("dept_head", "elected"): continue
    for p in n.get("people") or []:
        nm = norm(p.get("name") or "")
        if not p.get("started_at") and nm in _wd_by_pos.get(n["id"], {}):
            p["started_at"] = _wd_by_pos[n["id"]][nm]; p["started_at_source"] = "wikidata"
        e = {"mode": None, "by_id": None, "by_name": None, "by_person": None, "by_person_id": None, "date": p.get("started_at"), "sabatina": None, "dou": None, "term_end": None, "term_note": None, "election": None}
        sab = [s for s in n.get("sabatinas") or [] if s.get("name") and same_person(s["name"], p.get("name") or "") and s.get("deliberacao")]
        if sab:
            s = max(sab, key=lambda s: str(s["deliberacao"]))
            e["sabatina"] = {"date": str(s["deliberacao"]), "sim": s.get("votos_sim"), "nao": s.get("votos_nao"), "msf": s.get("msf"), "url": s.get("url"), "resultado": s.get("resultado")}
        _pos = _posses.get(f"{n['id']}#{p.get('id')}") or _posses.get(n["id"])
        if _pos and _pos.get("data") and (not p.get("started_at")) and same_person(_pos.get("pessoa_nome") or "", p.get("name") or ""):
            e["dou"] = {"date": str(_pos["data"]), "url": _pos.get("dou_url"), "act": _pos.get("ato")}
            e["date"] = str(_pos["data"]); p["started_at"] = e["date"]; p["started_at_source"] = "dou"; e["date_is_ato"] = True
        dou = [d for d in n.get("dou") or [] if d.get("name") and same_person(d["name"], p.get("name") or "") and d.get("verb") in ("NOMEAR", "DESIGNAR")]
        if dou:
            d = max(dou, key=lambda d: str(d["date"])); e["dou"] = {"date": str(d["date"]), "url": d.get("url"), "act": d.get("act")}
            if not e["date"]: e["date"] = str(d["date"]); p["started_at"] = e["date"]; p["started_at_source"] = "dou"
        ref = e["date"] or (e["sabatina"] or {}).get("date")
        if p.get("entry_mode") == "suplente": e["mode"] = "suplente"
        elif n.get("eleito_por") == "br-eleitorado" or n["id"] in ("br-presidente-da-republica", "br-vice-presidente-da-republica"):
            e["mode"] = "eleito"; e["by_id"] = "br-eleitorado"; e["by_name"] = "Povo brasileiro"
            if e["date"]: e["election"] = ELECTIONS.get(e["date"][:4]); 
            if n["id"] == "br-presidente-da-republica" or n["id"] == "br-vice-presidente-da-republica": e["election"] = "2022-10-30"; e["term_end"] = "2026-12-31"
            elif n["id"] == "br-senador" and e["date"]: e["term_end"] = _add_years(e["date"], 8)
            elif e["date"]: e["term_end"] = _add_years(e["date"], 4)
        elif n.get("eleito_por"):
            e["mode"] = "eleito_pares"; e["by_id"] = n["eleito_por"]; e["by_name"] = nodes[n["eleito_por"]]["name"]
            if e["date"]: e["term_end"] = _add_years(e["date"], n.get("mandato_anos") or 2)
        elif n.get("indicado_por") or n.get("nomeado_por"):
            e["mode"] = "indicado" if n.get("indicado_por") and not n.get("nomeado_por") else "nomeado"
            e["by_id"] = n.get("nomeado_por") or n.get("indicado_por"); e["by_name"] = nodes[e["by_id"]]["name"]
            if e["by_id"] == "br-presidente-da-republica" and ref:
                pr = president_at(ref)
                if pr: e["by_person"] = pr["short"]; e["by_person_id"] = pr.get("person_id")
            if n.get("mandato_anos"):
                e["term_end"] = _add_years(e["date"], n["mandato_anos"]) if e["date"] else None; e["term_note"] = f"mandato de {n['mandato_anos']} anos"
            elif n.get("sector") == "judiciario" or n.get("subtype") == "tribunal" or "tribunal" in n["id"] or "supremo" in n["id"]: e["term_note"] = "cargo vitalício; aposentadoria compulsória aos 75 anos"
            elif n.get("sector") == "executivo" and not n.get("sabatina"): e["term_note"] = "livre nomeação e exoneração"
        else: e["mode"] = p.get("entry_mode")
        if p.get("acting"): e["acting"] = True
        # aposentadoria compulsória aos 75 (vitalícios e TCU): data de nascimento do Wikidata
        if (e.get("term_note") and "vital" in e["term_note"]) or "tcu" in n["id"]:
            b = _nasc.get(p.get("id")) or next((v for v in _nasc.values() if norm(v.get("name") or "") == nm), None)
            if b and b.get("birth"):
                e["birth"] = str(b["birth"]); e["retire_at"] = _plus_years(b["birth"], 75)
                if not e.get("term_end") and e["retire_at"]: e["term_end"] = e["retire_at"]; e["term_kind"] = "compulsoria"
        p["entry"] = e
people_index = {}
for n in nodes.values():
    if n["type"] not in ("dept_head", "elected") and not (n["type"] == "commission" and n.get("sector") == "legislativo"): continue
    for p in n.get("people") or []:
        if not p.get("id"): continue
        rec = people_index.setdefault(p["id"], {"id": p["id"], "name": p.get("name"), "party": p.get("party"), "uf": p.get("uf"), "positions": [], "image": p.get("image_url") or p.get("image_commons"), "source": p.get("source", "api")})
        rec["positions"].append({"id": n["id"], "name": n["name"], "since": p.get("started_at"), "role": p.get("role"), "entry": p.get("entry"), "acting": bool(p.get("acting")), "note": p.get("note"), "source": p.get("source")})
        if p.get("party") and not rec.get("party"): rec["party"] = p["party"]
# ordem: cargo/mandato primeiro; depois comissões (presidência antes de titularidade e suplência)
_rank = lambda q: (0 if nodes[q["id"]]["type"] != "commission" else 1, {"Presidente": 0, "Vice-Presidente": 1, "1º Vice-Presidente": 1, "2º Vice-Presidente": 1, "Titular": 3, "Suplente": 4}.get(q.get("role") or "", 2))
for rec in people_index.values(): rec["positions"].sort(key=_rank)
img_dir = ROOT / "assets" / "img"
import base64, shutil as _sh
# a mesma pessoa pode ter ids diferentes conforme a fonte (oficial, Wikidata, Câmara): reaproveita a foto pelo nome
_man_p = ROOT / "build" / "fotos-manifesto.json"
_byname = json.load(open(_man_p, encoding="utf-8")) if _man_p.exists() else {}
_byname = {k: v for k, v in _byname.items() if (img_dir / (v + ".jpg")).exists()}
for rec in people_index.values():
    if (img_dir / (rec["id"] + ".jpg")).exists(): _byname.setdefault(norm(rec["name"] or ""), rec["id"])
json.dump(_byname, open(_man_p, "w", encoding="utf-8"), ensure_ascii=False)
for rec in people_index.values():
    f = img_dir / (rec["id"] + ".jpg")
    if not f.exists() and norm(rec["name"] or "") in _byname:
        _sh.copy(img_dir / (_byname[norm(rec["name"])] + ".jpg"), f)
for rec in people_index.values():
    f = img_dir / (rec["id"] + ".jpg")
    rec["photo"] = f.exists()
    # protótipo publicado não carrega imagens externas: embute as fotos de quem não é parlamentar (poucas e pequenas)
    if f.exists() and rec.get("source") != "api":
        rec["photo_data"] = "data:image/jpeg;base64," + base64.b64encode(f.read_bytes()).decode()
# ---- placar da omissão, arrecadômetro e atividade parlamentar (camadas geradas, compactas para o núcleo)
def _plain(o):
    if isinstance(o, dict): return {k: _plain(v) for k, v in o.items()}
    if isinstance(o, list): return [_plain(v) for v in o]
    if isinstance(o, (datetime.date, datetime.datetime)): return o.isoformat()
    return o
def _load_yaml(name):
    p = DATA / "generated" / name
    return _plain(yaml.safe_load(open(p, encoding="utf-8")) or {}) if p.exists() else {}
_om = _load_yaml("omissao.yaml")
omissao = None
if _om:
    _v = [x for x in _om.get("vetos") or []]; _m = [x for x in _om.get("mpvs") or [] if (x.get("days_left") is None or x["days_left"] >= -3) and "ANTES DA EC" not in (x.get("status") or "")]; _r = _om.get("rcps") or []
    for x in _v + _m + _r + list(_om.get("curated") or []):
        rp = x.get("responsible_position")
        if rp and rp in nodes: x["responsible_name"] = nodes[rp]["name"]; x["responsible_person"] = ((nodes[rp].get("people") or [{}])[0]).get("name"); x["responsible_person_id"] = ((nodes[rp].get("people") or [{}])[0]).get("id")
    omissao = {"generated_at": str(_om.get("generated_at")), "summary": _om.get("summary"), "vetos": _v[:12], "vetos_by_year": {}, "mpvs": sorted(_m, key=lambda x: (x.get("days_left") if x.get("days_left") is not None else 9999))[:15],
               "rcps": [x for x in _r if x.get("status") in ("aguardando", "indeferido", "outro")][:15], "curated": _om.get("curated") or []}
    for x in _v: omissao["vetos_by_year"][str(x.get("date") or "")[:4] or "?"] = omissao["vetos_by_year"].get(str(x.get("date") or "")[:4] or "?", 0) + 1
_ar = _load_yaml("arrecadacao.yaml")
arrecadacao = None
if _ar:
    y = str(_ar.get("year")); py = str(int(_ar["year"]) - 1)
    arrecadacao = {k: _ar.get(k) for k in ("generated_at", "source_date", "year", "population", "population_year", "ipca_ref_month", "ytd", "rate_per_second", "rate_months", "anchor", "full_years", "prev_partial_month")}
    arrecadacao["months"] = {y: _ar.get("months", {}).get(y, {}), py: _ar.get("months", {}).get(py, {})}
    arrecadacao["kinds"] = _ar.get("kinds"); arrecadacao["juros"] = {k: v for k, v in (_ar.get("juros") or {}).items() if k != "months"}; arrecadacao["juros"]["months"] = {k: v for k, v in ((_ar.get("juros") or {}).get("months") or {}).items() if k >= f"{int(y)-1}-01"}
    _saude = next((n for n in nodes.values() if n["id"] == "br-ministerio-da-saude"), None); _edu = next((n for n in nodes.values() if n["id"] == "br-ministerio-da-educacao"), None)
    arrecadacao["compare"] = {"saude": ((_saude or {}).get("budget") or {}).get(y) or ((_saude or {}).get("budget") or {}).get(py), "educacao": ((_edu or {}).get("budget") or {}).get(y) or ((_edu or {}).get("budget") or {}).get(py)}
_rs = (_load_yaml("resumos.yaml") or {}).get("resumos") or {}
if omissao:
    for x in omissao["vetos"] + omissao["mpvs"] + omissao["rcps"] + omissao["curated"]:
        if x.get("id") in _rs: x["resumo"] = _rs[x["id"]]["resumo"]
_tm = _load_yaml("temas.yaml")
temas = None
if _tm:
    order = {"prazo_vencido": 0, "parado": 1, "em_movimento": 2, "sem_processo": 3, "encerrado": 4}
    temas = {"generated_at": str(_tm.get("generated_at")), "temas": sorted([{k: v for k, v in t.items() if k != "keywords"} for t in _tm.get("temas") or []], key=lambda t: (0 if t.get("silent_and_stalled") else 1, order.get(t.get("state"), 9), -(t.get("stalled_days") or 0)))}
    for t in temas["temas"]:
        if f"tema-{t.get('id')}" in _rs: t["resumo"] = _rs[f"tema-{t.get('id')}"]["resumo"]
        if t.get("curated") and omissao:
            c = next((x for x in omissao.get("curated") or [] if x.get("id") == t["curated"]), None)
            if c: t["curated_item"] = {k: c.get(k) for k in ("title", "summary", "signatures", "date", "days", "legal_deadline", "responsible_position", "responsible_name", "responsible_person", "responsible_person_id", "sources")}
_em = _load_yaml("emendas.yaml")
emendas = None
if _em:
    emendas = {k: _em.get(k) for k in ("generated_at", "year", "por_ano", "por_tipo_ano", "ano_eleitoral", "autores_top", "coletivos_top", "municipios_por_habitante_top", "autores_sem_pessoa")}
    emendas["por_ano"] = {y: v for y, v in (emendas.get("por_ano") or {}).items() if int(y) >= 2014}
_rn = _load_yaml("renuncias.yaml")
renuncias = {k: _rn.get(k) for k in ("generated_at", "ano", "fonte", "fonte_url", "total", "por_funcao", "gastos_top", "compare", "nota")} if _rn else None
_tt = _load_yaml("teto.yaml")
teto = None
if _tt:
    teto = {k: _tt.get(k) for k in ("generated_at", "mes", "teto", "teto_fonte", "servidores", "com_abate_teto", "valor_abatido_mes", "indenizatorias_mes", "acima_do_teto_com_indenizatorias", "nota")}
    teto["orgaos"] = (_tt.get("orgaos") or [])[:20]
_at = _load_yaml("atividade.yaml")
atividade = (_at.get("people") or {}) if _at else {}
_em_people = (_em.get("people") or {}) if _em else {}
_cd = _load_yaml("candidaturas.yaml"); _cd_people = (_cd.get("people") or {}) if _cd else {}
_gb = _load_yaml("gabinetes.yaml"); _gb_people = (_gb.get("people") or {}) if _gb else {}
_gs = _load_yaml("gabinetes-senado.yaml"); _gs_people = (_gs.get("people") or {}) if _gs else {}
_pt = _load_yaml("patrimonio.yaml"); _pt_people = (_pt.get("people") or {}) if _pt else {}
_rm = _load_yaml("remuneracao.yaml"); _rm_people = (_rm.get("people") or {}) if _rm else {}
_do = _load_yaml("doadores-2022.yaml"); _do_people = (_do.get("people") or {}) if _do else {}
_pp_ = _load_yaml("proposicoes.yaml"); _pr_people = (_pp_.get("people") or {}) if _pp_ else {}
if _pp_: stats["proposicoes"] = {"resumo": _pp_.get("resumo"), "fonte": _pp_.get("fonte"), "generated_at": str(_pp_.get("generated_at")), "desde": str(_pp_.get("since") or "")}
_vg = _load_yaml("viagens.yaml"); _vg_people = (_vg.get("people") or {}) if _vg else {}
_ct = _load_yaml("cartao.yaml"); _ct_people = {}  # o extrato do CPGF identifica o portador (servidor de execução), não o ocupante: sem bloco por pessoa
viagens = {k: _vg.get(k) for k in ("generated_at", "ano", "fonte", "orgaos", "total", "viagens_total", "nota")} if _vg else None
cartao = {k: _ct.get(k) for k in ("generated_at", "ano", "meses", "fonte", "orgaos", "total", "nota", "orgaos_casados")} if _ct else None
if _do: stats["doadores"] = {"eleicao": _do.get("eleicao"), "fonte": _do.get("fonte"), "limiar_pf": _do.get("limiar_pf"), "generated_at": str(_do.get("generated_at"))}
if _rm: stats["remuneracao"] = {"mes": _rm.get("mes"), "fonte": _rm.get("fonte"), "nota": _rm.get("nota"), "generated_at": str(_rm.get("generated_at"))}
if _pt: stats["patrimonio"] = {"fonte": _pt.get("fonte"), "ipca_fator_2018_2022": _pt.get("ipca_fator_2018_2022"), "generated_at": str(_pt.get("generated_at"))}
stats["gabinetes"] = {}
if _gb: stats["gabinetes"]["camara"] = {"medianas": _gb.get("medianas"), "subsidio_mensal": _gb.get("subsidio_mensal"), "verba_gabinete_limite_mensal": _gb.get("verba_gabinete_limite_mensal"), "nota": _gb.get("nota"), "fonte": _gb.get("fonte"), "generated_at": str(_gb.get("generated_at"))}
if _gs: stats["gabinetes"]["senado"] = {"medianas": _gs.get("medianas"), "subsidio_mensal": _gs.get("subsidio_mensal"), "folha_mes": _gs.get("folha_mes"), "nota": _gs.get("nota"), "fonte": _gs.get("fonte"), "generated_at": str(_gs.get("generated_at"))}
for pid, rec in people_index.items():
    if pid in atividade: rec["activity"] = atividade[pid]
    if pid in _em_people: rec["emendas"] = _em_people[pid]
    if pid in _cd_people: rec["candidaturas"] = _cd_people[pid]
    if pid in _pt_people: rec["patrimonio"] = _pt_people[pid]
    if pid in _rm_people: rec["remuneracao"] = _rm_people[pid]
    if pid in _do_people: rec["doadores"] = _do_people[pid]
    if pid in _vg_people: rec["viagens"] = _vg_people[pid]
    if pid in _pr_people: rec["proposicoes"] = _pr_people[pid]
    if pid in _ct_people: rec["cartao"] = _ct_people[pid]
    if pid in _gb_people: rec["gabinete"] = dict(_gb_people[pid], casa="camara")
    elif pid in _gs_people: rec["gabinete"] = _gs_people[pid]
# por órgão: dirigentes/ministros que já foram candidatos, com o partido da candidatura mais recente (nunca "filiado")
for n in nodes.values():
    if n["type"] == "dept_head": continue
    parts = {}; total = 0
    for pid in n.get("positions") or []:
        for p in nodes[pid].get("people") or []:
            if not p.get("id"): continue
            total += 1; c = _cd_people.get(p["id"])
            if c: parts[c[0]["partido"]] = parts.get(c[0]["partido"], 0) + 1
    if parts: n["candidaturas"] = {"ocupantes": total, "ex_candidatos": sum(parts.values()), "partidos": dict(sorted(parts.items(), key=lambda kv: -kv[1]))}
if _em and _em.get("voto_emenda") and emendas: emendas["voto_emenda"] = _em["voto_emenda"]
# ---- sinais "para verificar": fatos cruzados que merecem conferência humana; redação neutra, com o dado que os gerou
def _sinais(rec):
    out = []
    gb = rec.get("gabinete") or {}
    if gb.get("mesmo_sobrenome"):
        out.append({"tipo": "sobrenome", "texto": f"{len(gb['mesmo_sobrenome'])} {'pessoa da equipe tem' if len(gb['mesmo_sobrenome']) == 1 else 'pessoas da equipe têm'} sobrenome em comum com o parlamentar: {', '.join(gb['mesmo_sobrenome'][:4])}{'…' if len(gb['mesmo_sobrenome']) > 4 else ''}.",
                    "nota": "Sobrenome igual não prova parentesco. A Súmula Vinculante 13 do STF veda nomear cônjuge, companheiro ou parente até o 3º grau para cargo em comissão."})
    if gb.get("casa") == "camara" and gb.get("assessores") and gb.get("nomeados_no_ano") and gb["nomeados_no_ano"] >= max(6, 0.5 * gb["assessores"]):
        out.append({"tipo": "equipe", "texto": f"{gb['nomeados_no_ano']} das {gb['assessores']} pessoas do gabinete começaram neste ano.", "nota": "Troca grande de equipe num ano eleitoral pode ter explicações comuns; vale olhar as datas."})
    em = rec.get("emendas") or {}; vt = em.get("votos_2022") or {}
    if vt.get("emendas_nos_top15_pct") is not None and vt["emendas_nos_top15_pct"] >= 80 and (vt.get("emendas_com_municipio") or 0) >= 1e6:
        out.append({"tipo": "emendas_voto", "texto": f"{vt['emendas_nos_top15_pct']}% das emendas com município definido foram para os 15 municípios onde teve mais votos em 2022.", "nota": "Emenda é instrumento legítimo de representação local; a concentração só indica onde a base eleitoral está."})
    do = rec.get("doadores") or {}
    if do.get("maiores") and em.get("favorecidos_pj"):
        dn = {norm(d["doador"]): d for d in do["maiores"] if "física" not in (d.get("origem") or "").lower()}
        hits = [(f, dn[norm(f["nome"])]) for f in em["favorecidos_pj"] if norm(f["nome"]) in dn]
        for f, d in hits[:3]:
            out.append({"tipo": "doador_favorecido", "texto": f"{f['nome']} doou {d['valor']:,.0f} reais à campanha de 2022 e recebeu {f['valor']:,.0f} reais em pagamentos de emendas do mesmo parlamentar desde {em.get('desde')}.".replace(",", "."),
                        "nota": "Coincidência entre doador e favorecido não indica irregularidade por si; pagamentos de emendas passam por convênio ou contrato público."})
    pt = rec.get("patrimonio") or {}
    if pt.get("variacao_real_pct") is not None and pt["variacao_real_pct"] >= 100 and (pt.get("2022") or {}).get("total", 0) >= 500000:
        out.append({"tipo": "patrimonio", "texto": f"O patrimônio declarado ao TSE mais que dobrou em valor real entre 2018 e 2022 (+{pt['variacao_real_pct']}%).", "nota": "Declarações são do próprio candidato, a valor de aquisição; herança, venda de bens ou mudança de critério explicam muitas variações."})
    return out
for pid, rec in people_index.items():
    s = _sinais(rec)
    if s: rec["sinais"] = s

# ---- custo anual de cada cadeira: o que a lei permite (ficha B) e o que a cadeira custa por ano (ficha C)
#
# O que a auditoria de 23/9/2026 fixou e este bloco implementa:
#   1. Nunca multiplicar por 12 às cegas. Cada família tem um fator anual escrito em norma (décimo terceiro,
#      terço de férias) e o fator vai publicado ao lado do número, com a norma que o justifica.
#   2. Nada marcado `papel: componente_do_salario` é somado ao salário: já está dentro do contracheque.
#      Era daí que vinham os reitores como segunda cadeira mais cara do país.
#   3. Limite da lei (`tipo_valor: teto`) nunca entra numa soma com gasto real: vira o topo de um intervalo.
#   4. Quando há folha, a base é o bruto DEPOIS do abate-teto, sem as rubricas eventuais — que são 13º,
#      terço e retroativos e seriam multiplicadas de novo pelo fator.
#   5. Regra de amostra: 5 ocupantes ou mais viram mediana; 3 ou 4 viram faixa; 2 ou menos não projetam nada.
#   6. Total acumulado vira média mensal dividindo pelos meses COMPLETOS do arquivo, não pelos do calendário.
_TETO_CONSTITUCIONAL = 46366.19  # subsídio de Ministro do STF; art. 37, XI, da Constituição

_NOTA_1333 = "doze meses, mais décimo terceiro, mais um terço de férias"
_NOTA_1367 = ("doze meses, mais décimo terceiro, mais dois terços de férias — as férias são de sessenta dias em "
              "dois períodos e o terço incide uma vez por período")
_NOTA_13 = ("doze meses, mais décimo terceiro — a folha paga a gratificação natalina em duas metades, em junho e "
            "em dezembro; não há terço de férias, porque parlamentar tem recesso, não férias remuneradas")
_NOTA_12 = "doze meses; não foi localizada norma que institua décimo terceiro ou terço de férias para o cargo"

_F_8112 = "Lei 8.112/1990, arts. 63 e 76"
_F_MILITAR = "CF art. 142 §3º VIII; Decreto 4.307/2002, arts. 80 e 81"
_F_MAGISTRADO = ("Tese de repercussão geral do STF de 25/3/2026, item 6; Resolução Conjunta CNJ/CNMP 14/2026, "
                 "art. 4º; LC 75/1993, art. 220 §2º")
_F_PARLAMENTAR = ("Folha da Câmara e do Senado de 2025, rubrica Gratificação Natalina em junho e em dezembro; "
                  "nenhuma norma a institui — o Decreto Legislativo 172/2022 fixa apenas subsídio mensal")
_F_NAO_LOCALIZADA = "norma não localizada"

# família → (fator anual, o que o fator soma, norma que o justifica)
_FATOR_ANUAL = {f: (13.33, _NOTA_1333, _F_8112) for f in (
    "secretario-executivo-de-ministerio", "secretario-nacional-ou-finalistico-de-ministerio",
    "secretario-especial-extraordinario-ou-geral", "dirigente-de-autarquia-ou-fundacao-federal",
    "dirigente-maximo-de-agencia-reguladora", "diretor-de-agencia-reguladora",
    "presidente-e-diretor-do-banco-central", "reitor-de-instituicao-federal-de-ensino",
    "dirigente-de-orgao-singular-do-executivo", "dirigente-de-empresa-estatal",
    "chefia-da-advocacia-publica-federal")}
_FATOR_ANUAL.update({f: (13.67, _NOTA_1367, _F_MAGISTRADO) for f in (
    "ministro-do-supremo-tribunal-federal", "ministro-de-tribunal-superior",
    "ministro-do-tribunal-superior-eleitoral", "presidente-de-tribunal-regional",
    "conselheiro-do-conselho-nacional-de-justica", "procurador-geral-da-republica",
    "chefia-de-ramo-do-ministerio-publico-da-uniao", "conselheiro-do-conselho-nacional-do-ministerio-publico",
    "ministro-do-tribunal-de-contas-da-uniao")})
_FATOR_ANUAL.update({f: (13.0, _NOTA_13, _F_PARLAMENTAR) for f in ("deputado-federal", "senador")})
_FATOR_ANUAL.update({f: (12.0, _NOTA_12, _F_NAO_LOCALIZADA) for f in (
    "ministro-de-estado", "presidente-e-vice-presidente-da-republica", "advogado-geral-da-uniao")})
_FATOR_ANUAL["comandante-de-forca-armada"] = (13.33, _NOTA_1333, _F_MILITAR)
_FATOR_ANUAL["defensor-publico-geral-federal"] = (13.33, _NOTA_1333, _F_8112 + " (regra do servidor federal; a "
                                                  "norma própria da Defensoria Pública da União não foi conferida)")

# mandato em anos, para amortizar a ajuda de custo de início e de fim em vez de lançá-la como pico anual
_MANDATO_ANOS = {"deputado-federal": 4, "senador": 8, "presidente-e-vice-presidente-da-republica": 4}

# Encargos da equipe do gabinete: 13º, terço de férias e auxílio-alimentação dos secretários parlamentares são
# pagos pela Casa FORA do teto da verba de gabinete. O Instituto Millenium mediu R$ 49.624,89/mês sobre uma
# verba de R$ 125.478,70 (~40%), com memória de cálculo publicada. Como esses 40% já contêm o 13º e o terço,
# a folha da equipe é anualizada por 12 e não pelo fator da família — somar os dois contaria o 13º duas vezes.
_ENCARGOS_EQUIPE = 0.40
# Folha reconstruída dos gabinetes do Senado: `gabinetes-senado.yaml` traz `folha_mensal: 0` para 81 de 81
# senadores (a API devolve a composição sem valor). A auditoria casou os 3.259 nomes das equipes com a folha
# nominal de ago/2026 do Senado (98,7% dos nomes casam, nenhum nome em dois gabinetes): mediana por gabinete.
_SENADO_FOLHA_GABINETE_MES = 505649.0
_SENADO_FOLHA_FONTE = ("folha nominal do Senado de ago/2026 casada com a composição dos gabinetes "
                       "(mediana de 81 gabinetes, 37 pessoas cada)")
# Meses completos equivalentes de cada arquivo acumulado do ano corrente = total do arquivo ÷ média dos meses
# completos. A cota da Câmara tem 9 meses com lançamento mas só 6,55 completos (os últimos chegam com
# defasagem); o SCDP tem 7,18. Dividir pelos meses do calendário subestima a cota em 37% e as viagens em 25%.
_MESES_CEAP = 6.55
_MESES_SCDP = 7.18

_FORA_PADRAO = ["encargos previdenciários do empregador sobre o salário de quem ocupa o cargo",
                "imóvel funcional, segurança e transporte oficial",
                "estrutura predial e serviços gerais",
                "aposentadoria futura"]

def _mediana(vals):
    vals = sorted(v for v in vals if v)
    if not vals: return None
    n = len(vals); return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2

def _amostra_de(n):
    """Regra de publicação da auditoria: mediana só com 5 ou mais; faixa com 3 ou 4; abaixo disso não se projeta."""
    return "mediana" if n >= 5 else ("faixa" if n >= 3 else "insuficiente")

def _bloco_real(k, nome, vals, base, itens, faltando, motivo):
    """Bloco apoiado em dado real de ocupantes. Devolve None e registra a lacuna quando a amostra não dá."""
    vals = sorted(v for v in vals if v)
    n = len(vals); a = _amostra_de(n)
    if a == "insuficiente":
        faltando.append(f"{motivo} ({n} ocupante com dado; a regra exige 3)" if n == 1
                        else f"{motivo} ({n} ocupantes com dado; a regra exige 3)" if n
                        else motivo)
        return None
    lo = hi = _mediana(vals) if a == "mediana" else None
    if a == "faixa": lo, hi = vals[0], vals[-1]
    return {"k": k, "nome": nome, "ano_min": round(lo, 2), "ano_max": round(hi, 2), "base": base,
            "n": n, "amostra": a, "itens": itens(lo, hi, n)}

def _salario_mes_da_folha(o):
    """Remuneração mensal depois do abate-teto e sem as rubricas eventuais (13º, terço, retroativos).

    Multiplicar o `bruto` cru pelo fator anual contaria o 13º duas vezes quando o mês tem 13º e nenhuma vez
    quando não tem; e o que a Constituição permite pagar é o valor DEPOIS do abate, não antes.
    """
    r = o.get("remuneracao") or {}
    b = r.get("bruto_apos_abate")
    if b is None: b = r.get("bruto")
    if not b: return None
    v = b - ((r.get("componentes") or {}).get("eventuais") or 0.0)
    if v <= 0: return None
    return min(v, _TETO_CONSTITUCIONAL)  # trava do art. 37, XI: nenhum salário mensal passa do teto

def _folha_gabinete_mes(o):
    """Folha mensal da equipe do gabinete, e de onde ela veio."""
    g = o.get("gabinete") or {}
    v = g.get("folha_mensal_estimada") or g.get("folha_mensal")
    if v: return float(v), g.get("assessores")
    if g.get("casa") == "senado" and g.get("assessores"):
        return _SENADO_FOLHA_GABINETE_MES, g.get("assessores")
    return None, None

def _cota_mes(o):
    """Custeio do mandato por mês, dividido pelos meses COMPLETOS do arquivo, nunca pelos meses decorridos."""
    c = (o.get("activity") or {}).get("cota") or {}
    if c.get("total"): return c["total"] / _MESES_CEAP
    ca = (o.get("gabinete") or {}).get("custo_ano") or {}
    if ca.get("cota") and ca.get("meses"): return ca["cota"] / ca["meses"]
    return None

def _custo_cadeira(n):
    sub = n.get("subsidio") or {}
    fam = sub.get("familia")
    fator, fator_nota, fator_fonte = _FATOR_ANUAL.get(fam, (12.0, _NOTA_12, _F_NAO_LOCALIZADA))
    ocupantes = [people_index.get(x.get("id")) for x in (n.get("people") or [])]
    ocupantes = [o for o in ocupantes if o]
    seats = n.get("seats") or 1
    beneficios = sub.get("beneficios") or []

    # ---- ficha B: o que o cargo permite, parcela a parcela, sem somar nada
    parcelas = [{"nome": b.get("nome"), "papel": b.get("papel"), "tipo": b.get("tipo_valor") or "sem_valor",
                 "valor": b.get("valor_mensal_ou_teto"), "periodicidade": b.get("periodicidade"),
                 "norma": b.get("norma"), "url": b.get("norma_url"), "nota": b.get("note")} for b in beneficios]
    lei = {"salario_mes": sub.get("subsidio_mensal_bruto"), "salario_norma": sub.get("norma"),
           "salario_url": sub.get("norma_url"), "parcelas": parcelas}

    # ---- ficha C: quanto custa a cadeira por ano
    blocos, faltando, fora = [], [], list(_FORA_PADRAO)

    # salário: folha quando a amostra permite; senão o valor que a norma fixa
    sal_mes = [v for v in (_salario_mes_da_folha(o) for o in ocupantes) if v]
    bl = None
    if sal_mes:
        bl = _bloco_real("pessoa", "Salário da pessoa", [v * fator for v in sal_mes], "folha",
                         lambda lo, hi, k: [{"nome": f"remuneração da folha depois do abate-teto, sem as parcelas "
                                                     f"eventuais, × {fator}", "ano": round(lo, 2)}],
                         [], "")
    if bl is None and lei["salario_mes"]:
        v = round(lei["salario_mes"] * fator, 2)
        bl = {"k": "pessoa", "nome": "Salário da pessoa", "ano_min": v, "ano_max": v, "base": "lei",
              "n": len(sal_mes), "amostra": "insuficiente",
              "itens": [{"nome": f"subsídio fixado em norma × {fator}", "ano": v}]}
        if sal_mes:
            faltando.append(f"o salário vem da norma, não da folha: só {len(sal_mes)} ocupante"
                            f"{'s' if len(sal_mes) != 1 else ''} deste cargo aparece na folha nominal")
    if bl is None:
        # Sem salário não há cadeira a custear: publicar só benefícios e custeio daria um número menor que a
        # verdade e ordenaria o cargo como "barato" por falta de dado. O cargo sai da conta inteiro.
        return None
    blocos.append(bl)

    # benefícios que viram renda da pessoa: `beneficio` e a ajuda de custo amortizada pelo mandato.
    # `componente_do_salario` fica de fora por definição (já está no salário) e `equipe`/`custeio` têm bloco próprio.
    ben_min = ben_max = 0.0; ben_itens = []; sem_valor = []
    anos_mandato = _MANDATO_ANOS.get(fam) or n.get("mandato_anos")
    for b in beneficios:
        papel, tipo, per, v = b.get("papel"), b.get("tipo_valor"), b.get("periodicidade"), b.get("valor_mensal_ou_teto")
        if papel == "beneficio":
            if tipo == "sem_valor" or not v:
                if tipo == "sem_valor": sem_valor.append(b.get("nome"))
                continue
            ano = v * 12 if per == "mensal" else (v if per == "anual" else None)
            if ano is None: continue
            ben_max += ano
            if tipo == "teto":
                ben_itens.append({"nome": f"{b.get('nome')} — limite da lei, não gasto medido", "ano": round(ano, 2)})
            else:
                ben_min += ano; ben_itens.append({"nome": b.get("nome"), "ano": round(ano, 2)})
        elif papel == "eventual" and per == "por_mandato" and v and anos_mandato:
            ano = v * 2 / anos_mandato  # início e fim do mandato, amortizados pelos anos do mandato
            ben_min += ano; ben_max += ano
            ben_itens.append({"nome": f"{b.get('nome')}: duas parcelas amortizadas em {anos_mandato} anos de mandato",
                              "ano": round(ano, 2)})
    if ben_max:
        blocos.append({"k": "pessoa", "nome": "Benefícios da pessoa", "ano_min": round(ben_min, 2),
                       "ano_max": round(ben_max, 2), "base": "lei", "n": 0, "amostra": "insuficiente",
                       "itens": ben_itens[:8]})
    if sem_valor:
        faltando.append("a norma prevê sem publicar valor: " + ", ".join(sem_valor[:4]).lower())

    # equipe do gabinete: folha mensal × 12 × (1 + encargos). O 13º e o terço da equipe estão dentro dos encargos.
    eq = [_folha_gabinete_mes(o) for o in ocupantes]
    eq_vals = [v for v, _ in eq if v]
    eq_pes = _mediana([p for v, p in eq if v and p])
    senado = any((o.get("gabinete") or {}).get("casa") == "senado" for o in ocupantes)
    if eq_vals:
        def _itens_eq(lo, hi, k, _pes=eq_pes, _sen=senado):
            folha = lo / (1 + _ENCARGOS_EQUIPE)
            base = (_SENADO_FOLHA_FONTE if _sen else
                    "folha do gabinete reconstruída pela tabela de níveis de secretário parlamentar da Câmara")
            return [{"nome": f"{base}{f', {int(_pes)} pessoas' if _pes else ''}, doze meses", "ano": round(folha, 2)},
                    {"nome": "encargos com a equipe, 40% sobre a folha: décimo terceiro, terço de férias e "
                             "auxílio-alimentação dos assessores, pagos pela Casa fora do teto da verba",
                     "ano": round(lo - folha, 2)}]
        b = _bloco_real("equipe", "Equipe do gabinete", [v * 12 * (1 + _ENCARGOS_EQUIPE) for v in eq_vals],
                        "folha", _itens_eq, faltando,
                        "a folha da equipe do gabinete não entra na conta")
        if b: blocos.append(b)
    elif any((o.get("gabinete") or {}).get("assessores") for o in ocupantes):
        _eq = _mediana([(o.get("gabinete") or {}).get("assessores") for o in ocupantes])
        faltando.append(f"a folha da equipe não é publicada com valor (mediana de {int(_eq)} pessoas por gabinete)")

    # custeio do mandato (cota parlamentar)
    cota = [v for v in (_cota_mes(o) for o in ocupantes) if v]
    if cota:
        b = _bloco_real("custeio", "Custeio do mandato", [v * 12 for v in cota], "gasto real",
                        lambda lo, hi, k: [{"nome": "gasto real da cota, dividido pelos meses completos do "
                                                    "arquivo e não pelos meses decorridos", "ano": round(lo, 2)}],
                        faltando, "o custeio do mandato não entra na conta")
        if b: blocos.append(b)
        if senado:
            faltando.append("a cota do Senado é divulgada como total acumulado, sem quebra mensal: não dá para "
                            "medir quantos meses do arquivo estão completos, como se faz com a da Câmara")

    # viagens a serviço (SCDP)
    vg = [(o.get("viagens") or {}).get("total") for o in ocupantes]
    vg = [v for v in vg if v]
    if vg:
        b = _bloco_real("custeio", "Viagens a serviço", [v / _MESES_SCDP * 12 for v in vg], "gasto real",
                        lambda lo, hi, k: [{"nome": "diárias e passagens pagas no ano, divididas pelos meses "
                                                    "completos do arquivo do SCDP", "ano": round(lo, 2)}],
                        faltando, "as viagens a serviço não entram na conta")
        if b: blocos.append(b)

    if not blocos: return None
    total_min = round(sum(b["ano_min"] for b in blocos), 2)
    total_max = round(sum(b["ano_max"] for b in blocos), 2)
    if any(p.get("tipo") == "teto" and p.get("papel") in ("custeio", "equipe") for p in parcelas):
        fora.append("o teto da cota e o da verba de gabinete são limite, não gasto: a conta usa o gasto medido")
    if fam in ("deputado-federal", "senador"):
        fora.append("a execução orçamentária da Câmara e do Senado não é publicada por cadeira")
    return {"familia": fam, "fator_anual": fator, "fator_nota": fator_nota, "fator_fonte": fator_fonte, "lei": lei,
            "cadeira": {"blocos": blocos, "total_min": total_min, "total_max": total_max,
                        "intervalo": total_max > total_min, "cadeiras": seats,
                        "faltando": faltando, "fora": fora}}

_cu_n = 0
for _n in nodes.values():
    if _n["type"] != "dept_head": continue
    _c = _custo_cadeira(_n)
    if _c: _n["custo"] = _c; _cu_n += 1
stats["cargos_com_custo"] = _cu_n
stats["cargos_sem_custo_por_amostra"] = sum(
    1 for _n in nodes.values() if _n["type"] == "dept_head" and not _n.get("custo"))
FAMILIA_ROTULO = {
    "deputado-federal": "Deputado federal", "senador": "Senador", "ministro-de-estado": "Ministro de Estado",
    "presidente-e-vice-presidente-da-republica": "Presidente e vice-presidente", "advogado-geral-da-uniao": "Advogado-Geral da União",
    "ministro-do-supremo-tribunal-federal": "Ministro do Supremo", "ministro-de-tribunal-superior": "Ministro de tribunal superior",
    "ministro-do-tribunal-de-contas-da-uniao": "Ministro do Tribunal de Contas", "presidente-de-tribunal-regional": "Presidente de tribunal regional",
    "conselheiro-do-conselho-nacional-de-justica": "Conselheiro do Conselho Nacional de Justiça", "procurador-geral-da-republica": "Procurador-Geral da República",
    "chefia-de-ramo-do-ministerio-publico-da-uniao": "Chefia de ramo do Ministério Público", "chefia-da-advocacia-publica-federal": "Chefia da advocacia pública federal",
    "defensor-publico-geral-federal": "Defensor Público-Geral", "secretario-executivo-de-ministerio": "Secretário-executivo de ministério",
    "secretario-nacional-ou-finalistico-de-ministerio": "Secretário nacional", "secretario-especial-extraordinario-ou-geral": "Secretário especial",
    "presidente-e-diretor-do-banco-central": "Presidente e diretores do Banco Central", "dirigente-maximo-de-agencia-reguladora": "Presidente de agência reguladora",
    "diretor-de-agencia-reguladora": "Diretor de agência reguladora", "dirigente-de-autarquia-ou-fundacao-federal": "Dirigente de autarquia ou fundação",
    "reitor-de-instituicao-federal-de-ensino": "Reitor de universidade ou instituto federal",
    "comandante-de-forca-armada": "Comandante de Força Armada", "dirigente-de-orgao-singular-do-executivo": "Dirigente de órgão singular",
    "dirigente-de-empresa-estatal": "Dirigente de estatal",
}
# Comparação entre famílias de cargo. Duas perguntas diferentes, e o Atlas publicava as duas com o mesmo número:
# a mediana entre os cargos responde "quanto custa uma cadeira deste tipo"; o custo do colegiado é a SOMA dos
# cargos vezes as cadeiras de cada um — nunca a mediana multiplicada pelo total de cadeiras, que distorcia 7,6%
# no Senado. A ordenação é pelo custo da cadeira, não pelo número de camadas que cada família conseguiu medir.
_fam = {}
for _n in nodes.values():
    _c = _n.get("custo")
    if not _c or not (_n.get("people") or []): continue
    _f = _c.get("familia") or _n.get("name")
    _ca = _c["cadeira"]
    _d = _fam.setdefault(_f, {"familia": _f, "cadeiras": 0, "cargos": 0, "colegiado": 0.0, "colegiado_max": 0.0,
                              "exemplo": _n["id"], "exemplo_seats": 0, "blocos": {}, "faltando": set()})
    _s = _ca["cadeiras"] or 1
    if _s > _d["exemplo_seats"]: _d["exemplo"] = _n["id"]; _d["exemplo_seats"] = _s
    _d["cadeiras"] += _ca["cadeiras"]; _d["cargos"] += 1
    _d["colegiado"] += _ca["total_min"] * _s; _d["colegiado_max"] += _ca["total_max"] * _s
    _d["faltando"].update(_ca["faltando"])
    for _x in _ca["blocos"]:
        _b = _d["blocos"].setdefault((_x["k"], _x["nome"]), {"k": _x["k"], "nome": _x["nome"], "min": 0.0, "max": 0.0})
        _b["min"] += _x["ano_min"] * _s; _b["max"] += _x["ano_max"] * _s
_top = []
for _f, _d in _fam.items():
    _cad = _d["cadeiras"] or 1
    # a cadeira típica da família é o custo do colegiado dividido pelas cadeiras, e não a mediana entre cargos:
    # a mediana entre dois cargos de tamanhos muito diferentes (81 senadores e 1 Presidente do Senado) não
    # reproduz a soma e fazia o Atlas publicar dois totais divergentes para a mesma família.
    _mn, _mx = _d["colegiado"] / _cad, _d["colegiado_max"] / _cad
    if not _mx: continue
    _bl = [{"k": v["k"], "nome": v["nome"], "ano_min": round(v["min"] / _cad, 2), "ano_max": round(v["max"] / _cad, 2)}
           for v in _d["blocos"].values()]
    _bl = [b for b in _bl if b["ano_max"]]
    _rot = FAMILIA_ROTULO.get(_f) or (_f[:1].upper() + _f[1:]).replace("-", " ")
    _top.append({"id": _d["exemplo"], "nome": _rot, "familia": _f, "total_min": round(_mn, 2), "total_max": round(_mx, 2),
                 "cadeiras": _d["cadeiras"], "cargos": _d["cargos"],
                 "total_colegiado_ano": round(_d["colegiado"], 2), "blocos": _bl, "faltando": sorted(_d["faltando"])[:3]})
_top.sort(key=lambda x: -(x["total_min"] or x["total_max"]))
stats["custos_top"] = _top[:12]
stats["custo_total_colegiados"] = round(
    sum(n["custo"]["cadeira"]["total_min"] * (n["custo"]["cadeira"]["cadeiras"] or 1)
        for n in nodes.values() if n.get("custo")), 2)

# ---- agenda pública (e-Agendas/CGU) por pessoa e por órgão
_ag_p = DATA / "generated" / "agendas.yaml"
_ag_n = 0
if _ag_p.exists():
    _ag = yaml.safe_load(open(_ag_p, encoding="utf-8")) or {}
    for pid, a in (_ag.get("people") or {}).items():
        if pid in people_index and a:
            people_index[pid]["agenda"] = dict(a, generated_at=str(_ag.get("generated_at") or "")[:10], janela_dias=_ag.get("janela_dias")); _ag_n += 1
    for nid, a in (_ag.get("orgaos") or {}).items():
        if nid in nodes and a: nodes[nid]["agenda"] = dict(a, generated_at=str(_ag.get("generated_at") or "")[:10], janela_dias=_ag.get("janela_dias"))
    stats["agendas_pessoas"] = _ag_n
_ap_p = DATA / "generated" / "agenda-planalto.yaml"
if _ap_p.exists():
    _ap = yaml.safe_load(open(_ap_p, encoding="utf-8")) or {}
    for pid, a in (_ap.get("people") or {}).items():
        if pid in people_index and a and not people_index[pid].get("agenda"):
            people_index[pid]["agenda"] = dict({k: v for k, v in a.items() if k != "dias"}, generated_at=str(_ap.get("generated_at") or "")[:10], janela_dias=_ap.get("janela_dias")); stats["agendas_pessoas"] = stats.get("agendas_pessoas", 0) + 1
stats["sinais"] = {"pessoas": sum(1 for r in people_index.values() if r.get("sinais")), "por_tipo": dict(__import__("collections").Counter(x["tipo"] for r in people_index.values() for x in r.get("sinais") or []))}
stats["omissao"] = (omissao or {}).get("summary"); stats["resumos"] = len(_rs); stats["historico_cargos"] = _hi_n; stats["colegiados_com_composicao"] = _cg_n; stats["orgaos_com_programas"] = _pg_n; stats["dirigentes"] = _di_n; stats["cargos_com_subsidio"] = _sb_n; stats["orgaos_com_transferencias"] = _tr_n; stats["segundo_escalao"] = _se_n; stats["atividade_pessoas"] = len(atividade)
stats["people"] = len(people_index)
# ---- números do projeto: o README descreve o que existe hoje, gerado a partir deste build
def _cobertura():
    _pos = [n for n in nodes.values() if n["type"] == "dept_head"]
    _com = sum(1 for n in _pos if n.get("people"))
    _heads = {n.get("head_of") for n in _pos}
    _orgs = [n for n in nodes.values() if n["type"] == "department"]
    _sem_chefia = [n for n in _orgs if n["id"] not in _heads]
    _cole = [n for n in nodes.values() if n["type"] in ("commission", "advisory")]
    _cole_sem = [n for n in _cole if not n.get("people")]
    _nom = [(n, p) for n in _pos for p in (n.get("people") or []) if n.get("nomeado_por") or n.get("indicado_por")]
    _sem_data = sum(1 for n, p in _nom if not p.get("started_at"))
    return {"nos": stats["nodes"], "arestas": stats["edges"], "pessoas": len(people_index), "cargos": len(_pos), "cargos_com": _com,
            "cargos_sem": len(_pos) - _com, "orgaos_sem_chefia": len(_sem_chefia), "colegiados": len(_cole), "colegiados_sem_membros": len(_cole_sem),
            "nomeacoes": len(_nom), "nomeacoes_sem_data": _sem_data, "cadeiras": stats["seats_total"], "cadeiras_ocupadas": stats["seats_filled"]}

_cov = _cobertura(); stats["cobertura"] = _cov

# ---- registro de execução: o que cada conector fez na última rodada e quando cada bloco do site foi lido
# (scripts/update.sh escreve build/_execucao.tsv; os "lido em" por bloco vêm do generated_at de cada arquivo)
BLOCOS = {  # rótulo no site -> arquivo que o alimenta
    "Ocupantes (Câmara e Senado)": "parlamentares.yaml", "Comissões do Congresso": "comissoes.yaml", "Estrutura (SIORG)": "siorg.yaml",
    "Segundo escalão": "segundo-escalao.yaml", "Sabatinas": "sabatinas.yaml", "Notícias": "noticias.json", "Diário Oficial": "dou.json",
    "Quem assina os atos": "dou-assinaturas.yaml", "Histórico dos cargos": "historico.yaml", "Sem decisão": "omissao.yaml",
    "Temas": "temas.yaml", "Arrecadação": "arrecadacao.yaml", "Atividade parlamentar": "atividade.yaml", "Proposições": "proposicoes.yaml",
    "Gabinetes": "gabinetes.yaml", "Gabinetes do Senado": "gabinetes-senado.yaml", "Emendas": "emendas.yaml", "Renúncias fiscais": "renuncias.yaml",
    "Acima do teto": "teto.yaml", "Remuneração": "remuneracao.yaml", "Viagens": "viagens.yaml", "Cartão corporativo": "cartao.yaml",
    "Orçamento": "orcamento.yaml", "Agenda pública": "agendas.yaml", "Agenda do Planalto": "agenda-planalto.yaml",
    "Patrimônio (TSE)": "patrimonio.yaml", "Doadores (TSE)": "doadores-2022.yaml", "Candidaturas (TSE)": "candidaturas.yaml",
    "Votos por município (TSE)": "votos-2022.yaml", "Resumos em linguagem simples": "resumos.yaml",
}
_ex_path = DATA / "generated" / "_execucao.yaml"
_ant = (yaml.safe_load(open(_ex_path, encoding="utf-8")) if _ex_path.exists() else None) or {}
_conectores = dict((_ant.get("conectores") or {}))
_tsv = OUT / "_execucao.tsv"
if _tsv.exists():
    _hoje = datetime.date.today().isoformat()
    for _ln in _tsv.read_text(encoding="utf-8").splitlines():
        _pt = _ln.split("\t")
        if len(_pt) != 3: continue
        _nm, _st, _sg = _pt[0], _pt[1], int(_pt[2] or 0)
        _r = _conectores.get(_nm) or {}
        _r.update({"status": _st, "segundos": _sg, "rodou_em": _hoje})
        if _st == "ok": _r["ok_em"] = _hoje
        _conectores[_nm] = _r
_blocos = {}
for _lbl, _fn in BLOCOS.items():
    _fp = DATA / "generated" / _fn
    if not _fp.exists(): _blocos[_lbl] = {"arquivo": _fn, "existe": False}; continue
    try:
        _d = json.load(open(_fp, encoding="utf-8")) if _fn.endswith(".json") else yaml.safe_load(open(_fp, encoding="utf-8"))
        _ga = str((_d or {}).get("generated_at") or "")[:10]
    except Exception: _ga = ""
    if not _ga: _ga = datetime.date.fromtimestamp(_fp.stat().st_mtime).isoformat()
    _blocos[_lbl] = {"arquivo": _fn, "existe": True, "lido_em": _ga}
_exec = {"generated_at": datetime.date.today().isoformat(),
         "nota": "GERADO por scripts/build_graph.py a partir de build/_execucao.tsv (scripts/update.sh) e do generated_at de cada arquivo.",
         "conectores": _conectores, "blocos": _blocos}
_ex_path.write_text("# GERADO por scripts/build_graph.py. Não edite à mão.\n" + yaml.dump(_exec, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
_falhas = sorted(k for k, v in _conectores.items() if v.get("status") == "falhou")
_velhos = sorted(k for k, v in _blocos.items() if v.get("lido_em") and v["lido_em"] < (datetime.date.today() - datetime.timedelta(days=7)).isoformat())
stats["execucao"] = {"gerado_em": _exec["generated_at"], "conectores": len(_conectores), "falhas": _falhas, "blocos": _blocos, "blocos_velhos": _velhos}
print(f"   execução: {len(_conectores)} conectores registrados, {len(_falhas)} com falha; {len(_velhos)} blocos com mais de 7 dias")
_readme = ROOT / "README.md"
if _readme.exists() and "<!-- ATLAS:NUMEROS -->" in _readme.read_text(encoding="utf-8"):
    _t = _readme.read_text(encoding="utf-8")
    _bloco = f"""<!-- ATLAS:NUMEROS -->
<!-- Gerado por scripts/build_graph.py a cada build. Não edite à mão. -->
| O que o grafo tem hoje | |
|---|---|
| Nós e relações | **{_cov['nos']}** nós · **{_cov['arestas']}** relações, cada uma com citação legal |
| Pessoas | **{_cov['pessoas']}** ocupando **{_cov['cadeiras_ocupadas']}** de **{_cov['cadeiras']}** cadeiras |
| Cargos de chefia | **{_cov['cargos_com']}** de **{_cov['cargos']}** com ocupante ({_cov['cargos_sem']} vazios) |
| Órgãos sem cargo de chefia mapeado | **{_cov['orgaos_sem_chefia']}** (tribunais regionais, estatais, universidades) |
| Colegiados sem composição registrada | **{_cov['colegiados_sem_membros']}** de **{_cov['colegiados']}** |
| Nomeações sem data de posse | **{_cov['nomeacoes_sem_data']}** de **{_cov['nomeacoes']}** |

Atualizado em {stats['generated_at']}.
<!-- /ATLAS:NUMEROS -->"""
    import re as _re
    _t = _re.sub(r"<!-- ATLAS:NUMEROS -->.*?<!-- /ATLAS:NUMEROS -->", lambda _m: _bloco, _t, flags=_re.S)
    _readme.write_text(_t, encoding="utf-8")
    print("   README atualizado com os números deste build")

graph = {"layout": layout, "nodes": nodes, "edges": {e["id"]: e for e in edges}, "stats": stats, "news": news, "power": power, "power_links": power_links if news_path.exists() else [], "changes": changes[:200], "people": people_index, "omissao": omissao, "arrecadacao": arrecadacao, "temas": temas, "emendas": emendas, "teto": teto, "renuncias": renuncias, "viagens": viagens, "cartao": cartao, "transferencias": transferencias}
# núcleo (topologia + home) e detalhe por nó, para carregar sob demanda no site estático
HEAVY = ("description", "siorg_description", "people", "sabatinas", "historico", "agenda", "composicao", "subsidio", "custo", "programas", "transferencias", "budget", "dou", "candidaturas", "cite", "cite_url", "official_url", "competencia", "note", "siorg_code", "checked_at", "mandato_anos", "vacant_seats")
DERIVED = ("connected", "edges", "children", "positions", "verified", "source", "siorg_tipo", "natureza_juridica", "nomeado_por", "indicado_por", "eleito_por")
core_nodes = {}
(OUT / "nodes").mkdir(exist_ok=True)
for nid, n in nodes.items():
    core = {k: v for k, v in n.items() if k not in HEAVY and k not in DERIVED}
    core["n_people"] = len(n.get("people") or [])
    if n.get("vacant_seats"): core["vacant_seats"] = n["vacant_seats"]
    core_nodes[nid] = core
    (OUT / "nodes" / f"{nid}.json").write_text(json.dumps({k: n.get(k) for k in HEAVY + ("nomeado_por", "indicado_por", "eleito_por", "verified", "source") if n.get(k) is not None}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
core_edges = {eid: {k: v for k, v in e.items() if k in ("id", "type", "from", "to", "cite", "seats")} for eid, e in graph["edges"].items()}
core_news = [{k: v for k, v in a.items() if k != "summary"} for a in news]
core_changes = [{k: v for k, v in c.items() if k not in ("cargoText", "act")} for c in changes[:120]]
core_people = {pid: {"id": r["id"], "name": r["name"], "party": r.get("party"), "uf": r.get("uf"), "positions": [q["id"] for q in r["positions"] if nodes[q["id"]]["type"] != "commission"], "photo": r.get("photo", False)} for pid, r in people_index.items()}  # sem photo_data: o site serve /img/
# detalhe por pessoa (comissões, papéis, datas) carregado sob demanda
_pp = OUT / "people"; _pp.mkdir(exist_ok=True)
for pid, r in people_index.items():
    json.dump({"id": pid, "positions": r["positions"], "source": r.get("source"), "activity": r.get("activity"), "emendas": r.get("emendas"), "candidaturas": r.get("candidaturas"), "gabinete": r.get("gabinete"), "patrimonio": r.get("patrimonio"), "remuneracao": r.get("remuneracao"), "doadores": r.get("doadores"), "sinais": r.get("sinais"), "viagens": r.get("viagens"), "cartao": r.get("cartao"), "proposicoes": r.get("proposicoes"), "agenda": r.get("agenda")}, open(_pp / (pid + ".json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
core = {"layout": layout, "nodes": core_nodes, "edges": core_edges, "stats": stats, "news": core_news, "power": power, "power_links": graph.get("power_links", []), "changes": core_changes, "people": core_people, "omissao": omissao, "arrecadacao": arrecadacao, "temas": temas, "emendas": emendas, "teto": teto, "renuncias": renuncias, "viagens": viagens, "cartao": cartao, "transferencias": transferencias, "detail_base": "/nodes/", "people_base": "/people/", "img_base": "/img/"}
cjs = json.dumps(core, ensure_ascii=False, separators=(",", ":"))
(OUT / "graph.core.js").write_text("window.ATLAS=" + cjs + ";", encoding="utf-8")
print(f"   build/graph.core.js = {len(cjs)//1024} KB + {len(core_nodes)} arquivos de detalhe")
js = json.dumps(graph, ensure_ascii=False, separators=(",", ":"))
(OUT / "graph.br.json").write_text(js, encoding="utf-8")
(OUT / "graph.br.js").write_text("window.ATLAS=" + js + ";", encoding="utf-8")
(ROOT / "web" / "graph.br.js").write_text("window.ATLAS=" + js + ";", encoding="utf-8")
print(f"extras: notícias={len(news)} power={len(power)} mudanças={len(changes)} sabatinas={len(sabatinas)}")
print(f"OK  nós={stats['nodes']}  arestas={stats['edges']}  cadeiras={seats} (sabatinadas {sabat})  não verificados={unverified}")
print("   por tipo:", dict(by_type)); print("   por setor:", dict(by_sector)); print("   por aresta:", dict(by_edge))
print(f"   build/graph.br.json = {len(js)//1024} KB")
