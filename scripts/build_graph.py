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
sources = [("generated", DATA / "generated" / "parlamentares.yaml")]
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
                recs.append({"id": "br-p-" + _slug(p["name"]), "name": p["name"], "started_at": str(p["started_at"]) if p.get("started_at") else None, "entry_mode": block.get("entry_mode", "nomeado"),
                             "note": p.get("note"), "source": "oficial", "source_url": block["source"], "checked_at": str(block.get("checked_at")), "verified": True})
            nodes[pid]["people"] = recs
    for n in nodes.values():
        if n["type"] == "dept_head" and n.get("people") and n["people"][0].get("source") == "oficial" and n.get("seats", 1) > len(n["people"]):
            n["vacant_seats"] = n["seats"] - len(n["people"])
sources.append(("generated", DATA / "generated" / "ocupantes.yaml"))
for _, ppl_path in sources:
    if not ppl_path.exists(): continue
    ppl = yaml.safe_load(open(ppl_path, encoding="utf-8")) or {}
    for pid, people in (ppl.get("positions") or {}).items():
        if pid not in nodes: warn(f"ocupantes para cargo inexistente {pid}"); continue
        if nodes[pid].get("people"): continue
        for p in people:
            if p.get("started_at") is not None: p["started_at"] = str(p["started_at"])
        # Wikidata: no Executivo, ocupante com início anterior ao governo atual (2023) é considerado desatualizado
        if nodes[pid].get("sector") == "executivo":
            people = [p for p in people if p.get("source") != "wikidata" or (p.get("started_at") or "") >= "2023-01-01"]
        if people: nodes[pid]["people"] = people

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
    news = [a for a in arts if a.get("entities") or a.get("people")][:60]
    mentions = {}
    for a in arts:
        if (a.get("date") or "") < cutoff90: continue
        for p in a.get("people") or []:
            m = mentions.setdefault(p["id"], {"id": p["id"], "name": p["name"], "position": p.get("position"), "articles": 0, "last": None})
            m["articles"] += 1; m["last"] = max(m["last"] or "", a.get("date") or "")
    power = sorted(mentions.values(), key=lambda m: -m["articles"])[:20]
    stats["articles_90d"] = sum(1 for a in arts if (a.get("date") or "") >= cutoff90); stats["news_sources"] = len(store.get("feeds") or [])
stats["sabatinas"] = len(sabatinas)
# mudanças: sabatinas deliberadas + posses recentes (started_at) como eventos
changes = []
for r in sabatinas:
    if r.get("deliberacao") and r.get("position_id"):
        changes.append({"kind": "sabatina", "date": r["deliberacao"], "personName": r.get("name"), "positionId": r["position_id"], "positionName": nodes[r["position_id"]]["name"], "result": r.get("resultado"), "votes": [r.get("votos_sim"), r.get("votos_nao")], "sourceUrl": r.get("url")})
for n in nodes.values():
    if n["type"] != "dept_head" and n["type"] != "elected": continue
    for p in n.get("people") or []:
        if p.get("started_at") and p["started_at"] >= "2025-01-01" and n["id"] not in ("br-deputado-federal", "br-senador"):
            changes.append({"kind": "posse", "date": p["started_at"], "personName": p.get("name"), "positionId": n["id"], "positionName": n["name"], "acting": p.get("acting"), "sourceUrl": p.get("source_url")})
dou_path = DATA / "generated" / "dou.json"
if dou_path.exists():
    for a in (json.load(open(dou_path, encoding="utf-8")).get("acts") or {}).values():
        for r in a.get("records") or []:
            if not r.get("position_id") or r["position_id"] not in nodes: continue
            kind = {"NOMEAR": "nomeacao", "EXONERAR": "exoneracao", "DESIGNAR": "designacao", "DISPENSAR": "exoneracao"}.get(r["verb"], "nomeacao")
            changes.append({"kind": kind, "date": a["date"], "personName": r.get("name"), "positionId": r["position_id"], "positionName": nodes[r["position_id"]]["name"], "cargoText": r.get("cargo"), "sourceUrl": a.get("url"), "act": a.get("title")})
            nodes[r["position_id"]].setdefault("dou", []).append({"date": a["date"], "verb": r["verb"], "name": r.get("name"), "cargo": r.get("cargo"), "url": a.get("url"), "act": a.get("title")})
changes.sort(key=lambda c: c["date"], reverse=True)
graph = {"layout": layout, "nodes": nodes, "edges": {e["id"]: e for e in edges}, "stats": stats, "news": news, "power": power, "changes": changes[:200]}
js = json.dumps(graph, ensure_ascii=False, separators=(",", ":"))
(OUT / "graph.br.json").write_text(js, encoding="utf-8")
(OUT / "graph.br.js").write_text("window.ATLAS=" + js + ";", encoding="utf-8")
(ROOT / "web" / "graph.br.js").write_text("window.ATLAS=" + js + ";", encoding="utf-8")
print(f"extras: notícias={len(news)} power={len(power)} mudanças={len(changes)} sabatinas={len(sabatinas)}")
print(f"OK  nós={stats['nodes']}  arestas={stats['edges']}  cadeiras={seats} (sabatinadas {sabat})  não verificados={unverified}")
print("   por tipo:", dict(by_type)); print("   por setor:", dict(by_sector)); print("   por aresta:", dict(by_edge))
print(f"   build/graph.br.json = {len(js)//1024} KB")
