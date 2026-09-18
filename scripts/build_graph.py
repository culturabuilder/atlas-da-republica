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
ppl_path = DATA / "generated" / "parlamentares.yaml"
if ppl_path.exists():
    ppl = yaml.safe_load(open(ppl_path, encoding="utf-8")) or {}
    for pid, people in (ppl.get("positions") or {}).items():
        if pid in nodes: nodes[pid]["people"] = people
        else: warn(f"ocupantes para cargo inexistente {pid}")

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
sabat = sum(n.get("seats", 0) for n in nodes.values() if n["type"] == "dept_head" and n.get("sabatina"))
unverified = sum(1 for n in nodes.values() if not n["verified"] and n.get("source") != "siorg")
from_siorg = sum(1 for n in nodes.values() if n.get("source") == "siorg")
stats = {"nodes": len(nodes), "edges": len(edges), "by_type": dict(by_type), "by_sector": dict(by_sector),
         "by_subtype": dict(by_subtype), "by_edge_type": dict(by_edge), "seats_total": seats, "seats_filled": filled, "seats_sabatina": sabat,
         "unverified": unverified, "from_siorg": from_siorg, "siorg_matched": merge_report["matched"], "generated_at": datetime.date.today().isoformat()}
graph = {"layout": layout, "nodes": nodes, "edges": {e["id"]: e for e in edges}, "stats": stats}
js = json.dumps(graph, ensure_ascii=False, separators=(",", ":"))
(OUT / "graph.br.json").write_text(js, encoding="utf-8")
(OUT / "graph.br.js").write_text("window.ATLAS=" + js + ";", encoding="utf-8")
(ROOT / "web" / "graph.br.js").write_text("window.ATLAS=" + js + ";", encoding="utf-8")
print(f"OK  nós={stats['nodes']}  arestas={stats['edges']}  cadeiras={seats} (sabatinadas {sabat})  não verificados={unverified}")
print("   por tipo:", dict(by_type)); print("   por setor:", dict(by_sector)); print("   por aresta:", dict(by_edge))
print(f"   build/graph.br.json = {len(js)//1024} KB")
