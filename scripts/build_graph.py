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
        if p and p in nodes and nodes[p].get("ring", 0) >= n.get("ring", 0) and n["type"] not in ("commission", "advisory"):
            warn(f"{i}: anel {n.get('ring')} não é maior que o do parent {p} (anel {nodes[p].get('ring')})")
    if n.get("verified") is False: n["verified"] = False
    else: n["verified"] = True

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
sabat = sum(n.get("seats", 0) for n in nodes.values() if n["type"] == "dept_head" and n.get("sabatina"))
unverified = sum(1 for n in nodes.values() if not n["verified"]) + sum(1 for e in edges if e.get("verified") is False)
stats = {"nodes": len(nodes), "edges": len(edges), "by_type": dict(by_type), "by_sector": dict(by_sector),
         "by_subtype": dict(by_subtype), "by_edge_type": dict(by_edge), "seats_total": seats, "seats_sabatina": sabat,
         "unverified": unverified, "generated_at": datetime.date.today().isoformat()}
graph = {"layout": layout, "nodes": nodes, "edges": {e["id"]: e for e in edges}, "stats": stats}
js = json.dumps(graph, ensure_ascii=False, separators=(",", ":"))
(OUT / "graph.br.json").write_text(js, encoding="utf-8")
(OUT / "graph.br.js").write_text("window.ATLAS=" + js + ";", encoding="utf-8")
(ROOT / "web" / "graph.br.js").write_text("window.ATLAS=" + js + ";", encoding="utf-8")
print(f"OK  nós={stats['nodes']}  arestas={stats['edges']}  cadeiras={seats} (sabatinadas {sabat})  não verificados={unverified}")
print("   por tipo:", dict(by_type)); print("   por setor:", dict(by_sector)); print("   por aresta:", dict(by_edge))
print(f"   build/graph.br.json = {len(js)//1024} KB")
