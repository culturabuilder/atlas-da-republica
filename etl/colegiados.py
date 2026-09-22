#!/usr/bin/env python3
"""Composição por cargo dos colegiados do Executivo → data/generated/colegiados.yaml.

Fonte: data/colegiados-composicao.yaml, curado à mão a partir da norma que cria cada colegiado
(decreto ou lei no Planalto, planalto.gov.br/ccivil_03), com artigo, URL e data de conferência.
A composição desses conselhos é quase sempre por cargo (membro nato): o membro é o cargo, e o
ocupante vem do próprio grafo. Este ETL valida os ids contra build/graph.br.json, casa cada cargo
da norma com o nó de cargo (dept_head/elected) e anexa o ocupante atual.
Uso: .venv/bin/python etl/colegiados.py
"""
import sys, json, pathlib, datetime
import yaml
ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "colegiados-composicao.yaml"
OUT = ROOT / "data" / "generated" / "colegiados.yaml"
GRAPH = ROOT / "build" / "graph.br.json"
TODAY = datetime.date.today()
TIPOS = {"nato", "indicado", "eleito", "externo"}
COLEGIADO_TYPES = {"commission", "advisory"}
CARGO_TYPES = {"dept_head", "elected"}

def ocupante(node):
    """Primeira pessoa no cargo (titular efetivo quando houver; senão o interino)."""
    people = node.get("people") or []
    if not people: return None
    return next((p for p in people if not p.get("acting")), people[0])

def main():
    if not GRAPH.exists(): sys.exit(f"falta {GRAPH.relative_to(ROOT)}: rode scripts/build_graph.py antes")
    if not SRC.exists(): sys.exit(f"falta {SRC.relative_to(ROOT)}")
    N = json.load(open(GRAPH, encoding="utf-8"))["nodes"]
    src = yaml.safe_load(SRC.read_text(encoding="utf-8")) or {}
    erros, avisos = [], []
    colegiados, positions = {}, {}
    n_membros = n_assentos = n_casados = n_vagas = 0

    for c in src.get("colegiados") or []:
        cid = c.get("id")
        node = N.get(cid)
        if node is None: erros.append(f"{cid}: id não existe no grafo"); continue
        if node["type"] not in COLEGIADO_TYPES: erros.append(f"{cid}: tipo {node['type']!r}, esperado commission/advisory"); continue
        if not c.get("norma") or not c.get("norma_url"): erros.append(f"{cid}: sem norma ou norma_url"); continue
        if node.get("positions"): avisos.append(f"{cid}: já tinha {len(node['positions'])} cargo(s) no grafo")

        pres = c.get("presidido_por")
        pres_nome = pres_pessoa = pres_pessoa_id = None
        if pres:
            pn = N.get(pres)
            if pn is None or pn["type"] not in CARGO_TYPES: erros.append(f"{cid}: presidido_por {pres!r} não é cargo do grafo"); continue
            pres_nome = pn["name"]; h = ocupante(pn)
            if h: pres_pessoa, pres_pessoa_id = h.get("name"), h.get("id")

        membros, seen = [], set()
        for m in c.get("membros") or []:
            texto = (m.get("cargo_texto") or "").strip()
            if not texto: erros.append(f"{cid}: membro sem cargo_texto"); continue
            tipo = m.get("tipo")
            if tipo not in TIPOS: erros.append(f"{cid}: membro {texto!r} com tipo {tipo!r} fora de {sorted(TIPOS)}"); continue
            assentos = int(m.get("assentos") or 1)
            cargo_id = m.get("cargo_id")
            pessoa = pessoa_id = cargo_nome = None
            if cargo_id:
                cn = N.get(cargo_id)
                if cn is None: erros.append(f"{cid}: cargo_id {cargo_id!r} não existe no grafo"); continue
                if cn["type"] not in CARGO_TYPES: erros.append(f"{cid}: cargo_id {cargo_id!r} é {cn['type']!r}, esperado dept_head/elected"); continue
                if cargo_id in seen: avisos.append(f"{cid}: cargo {cargo_id} repetido")
                seen.add(cargo_id); cargo_nome = cn["name"]
                h = ocupante(cn)
                if h: pessoa, pessoa_id = h.get("name"), h.get("id")
                n_casados += 1
            membros.append({k: v for k, v in (("cargo_id", cargo_id), ("cargo_texto", texto), ("cargo_nome", cargo_nome), ("tipo", tipo),
                                              ("assentos", assentos), ("pessoa_nome", pessoa), ("pessoa_id", pessoa_id), ("note", m.get("note"))) if v is not None})
            n_membros += 1; n_assentos += assentos
        if not membros: erros.append(f"{cid}: nenhum membro válido"); continue

        vagas = int(c.get("vagas_sociedade") or 0); n_vagas += vagas
        colegiados[cid] = {k: v for k, v in (
            ("nome", node["name"]), ("norma", c["norma"]), ("norma_url", c["norma_url"]),
            ("presidido_por", pres), ("presidido_por_nome", pres_nome), ("presidido_por_pessoa", pres_pessoa), ("presidido_por_pessoa_id", pres_pessoa_id),
            ("membros", membros), ("vagas_sociedade", vagas or None), ("assentos_cargo", sum(m["assentos"] for m in membros)),
            ("nota", c.get("nota")), ("atualizado_em", str(c.get("checked_at") or TODAY)),
        ) if v is not None}
        positions[cid] = [m["cargo_id"] for m in membros if m.get("cargo_id")]

    nao = [{"id": x.get("id"), "nome": (N.get(x.get("id")) or {}).get("name"), "motivo": x.get("motivo")} for x in (src.get("nao_resolvidos") or [])]
    for x in nao:
        if x["id"] and x["id"] not in N: erros.append(f"{x['id']}: (nao_resolvidos) id não existe no grafo")

    for a in avisos: print("aviso:", a, file=sys.stderr)
    if erros:
        for e in erros: print("erro:", e, file=sys.stderr)
        sys.exit(f"{len(erros)} erro(s) em {SRC.relative_to(ROOT)}; nada foi escrito")

    out = {"generated_at": TODAY.isoformat(),
           "fonte": src.get("fonte") or "Normas de criação (leis e decretos) no Planalto, curadas à mão em data/colegiados-composicao.yaml",
           "nota": "Composição por cargo (membros natos): o assento pertence ao cargo, e o ocupante vem do grafo. "
                   "Assentos da sociedade civil são contados em vagas_sociedade, sem nomear pessoas.",
           "colegiados": colegiados, "positions": positions, "nao_resolvidos": nao,
           "resumo": {"colegiados": len(colegiados), "membros": n_membros, "assentos_cargo": n_assentos,
                      "casados_com_cargo_do_grafo": n_casados, "sem_cargo_no_grafo": n_membros - n_casados,
                      "com_ocupante": sum(1 for c in colegiados.values() for m in c["membros"] if m.get("pessoa_id")),
                      "vagas_sociedade": n_vagas, "nao_resolvidos": len(nao)}}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("# GERADO por etl/colegiados.py. Não edite à mão.\n" + yaml.dump(out, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    r = out["resumo"]
    print(f"colegiados: {r['colegiados']} | membros(cargo): {r['membros']} em {r['assentos_cargo']} assentos | "
          f"casados com cargo do grafo: {r['casados_com_cargo_do_grafo']} ({r['com_ocupante']} com ocupante) | "
          f"só texto da norma: {r['sem_cargo_no_grafo']} | vagas de sociedade civil: {r['vagas_sociedade']} | não resolvidos: {r['nao_resolvidos']}")
    for cid, c in sorted(colegiados.items(), key=lambda kv: -len(kv[1]["membros"]))[:5]:
        print("  ", cid, f"{len(c['membros'])} membros", "|", c["norma"])
if __name__ == "__main__": main()
