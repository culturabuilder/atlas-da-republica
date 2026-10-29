#!/usr/bin/env python3
"""Servidor MCP do Atlas da República: o grafo do governo federal dentro do seu assistente.

Fala MCP por stdin/stdout (JSON-RPC 2.0), sem dependência nenhuma além da biblioteca padrão, e lê os
mesmos arquivos que o site publica — nada de banco, nada de chave, nada que não esteja no ar:

  https://atlasdarepublica.org/graph.br.js      núcleo (órgãos, cargos, relações, índice de pessoas)
  https://atlasdarepublica.org/nodes/<id>.json  detalhe de um órgão ou cargo
  https://atlasdarepublica.org/people/<id>.json detalhe de uma pessoa

Uso (Claude Code):
  claude mcp add atlas -- /caminho/para/.venv/bin/python /caminho/para/scripts/mcp_atlas.py
Uso (qualquer cliente MCP): comando acima como servidor stdio.
Para ler do build local em vez do site: ATLAS_MCP_BASE=file:///caminho/do/repo/site

Só leitura: não há ferramenta que escreva nada. Todo resultado traz a fonte e a data do dado, porque a
resposta do assistente deve poder ser conferida — é a mesma regra do site.
"""
import json, os, sys, re, unicodedata, urllib.request, pathlib

BASE = (os.environ.get("ATLAS_MCP_BASE") or "https://atlasdarepublica.org").rstrip("/")
UA = {"User-Agent": "atlas-mcp/1.0 (+https://atlasdarepublica.org)"}
VERSAO = "2024-11-05"
_cache = {}


def _ler(caminho):
    """Lê um caminho do site (ou do disco, se ATLAS_MCP_BASE for file://). Guarda em memória."""
    if caminho in _cache: return _cache[caminho]
    url = f"{BASE}/{caminho.lstrip('/')}"
    if url.startswith("file://"):
        texto = pathlib.Path(url[7:]).read_text(encoding="utf-8")
    else:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
            texto = r.read().decode("utf-8")
    _cache[caminho] = texto
    return texto


def grafo():
    if "_G" in _cache: return _cache["_G"]
    t = _ler("graph.br.js")
    # o arquivo publicado é "window.ATLAS={...};" — o JSON começa no primeiro "{"
    G = json.loads(t[t.index("{"):t.rindex("}") + 1])
    _cache["_G"] = G
    return G


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]+", " ", s).strip()


def _fonte(d):
    return {k: d[k] for k in ("cite", "cite_url", "official_url", "checked_at") if d.get(k)}


# ---------------------------------------------------------------- ferramentas
# "ministro do stf" é a formulação mais óbvia que um leigo escreve, e era a que falhava: o nó chama-se
# "Ministro do Supremo Tribunal Federal" e a sigla está no ÓRGÃO, não no cargo. Daí casar por palavra,
# sem as de ligação, e o cargo carregar o nome e as siglas do órgão que ele chefia — a mesma correção
# que a busca do site recebeu.
PALAVRA_VAZIA = {"de", "da", "do", "das", "dos", "e", "o", "a", "os", "as", "em", "no", "na", "para", "por", "um", "uma"}


def buscar(termo="", tipo="", limite=10):
    """Órgão, cargo ou pessoa pelo nome, sigla ou parte dele."""
    G = grafo()
    toks = [t for t in norm(termo).split() if t and t not in PALAVRA_VAZIA]
    if not toks: return {"erro": "diga o que procurar"}
    casa = lambda alvo: all(t in alvo for t in toks)
    out = []
    for n in G["nodes"].values():
        alvo = norm(" ".join([n.get("name") or ""] + (n.get("aliases") or [])))
        if n.get("type") == "dept_head" and n.get("head_of"):
            org = (G["nodes"] or {}).get(n["head_of"]) or {}
            alvo += " " + norm(" ".join([org.get("name") or ""] + (org.get("aliases") or [])))
        if casa(alvo):
            out.append({"id": n["id"], "nome": n.get("name"), "tipo": n.get("type"), "setor": n.get("sector"),
                        "sigla": (n.get("aliases") or [None])[0], "pagina": f"{BASE}/br/{n['id']}/"})
    for pid, p in (G.get("people") or {}).items():
        alvo = norm(" ".join([p.get("name") or "", p.get("party") or "", p.get("uf") or ""]))
        if casa(alvo):
            out.append({"id": pid, "nome": p.get("name"), "tipo": "pessoa", "partido": p.get("party"),
                        "uf": p.get("uf"), "pagina": f"{BASE}/br/pessoa/{pid}/"})
    if tipo: out = [x for x in out if x["tipo"] == tipo]
    out.sort(key=lambda x: (len(norm(x["nome"] or "")), x["nome"] or ""))
    return {"achados": len(out), "resultados": out[:max(1, min(int(limite or 10), 50))]}


def ver_orgao(id=""):
    """Tudo o que o Atlas sabe de um órgão ou cargo: norma que o cria, quem o chefia e os blocos de dado."""
    G = grafo()
    n = (G["nodes"] or {}).get(id)
    if not n: return {"erro": f"não há nó com id {id!r}; use buscar primeiro"}
    try: det = json.loads(_ler(f"nodes/{id}.json"))
    except Exception: det = {}
    blocos = sorted(k for k, v in det.items() if v and k not in
                    ("id", "type", "name", "sector", "ring", "parent", "cluster", "source", "aliases",
                     "description", "siorg_description", "cite", "cite_url", "official_url", "verified",
                     "siorg_code", "positions", "people", "edges", "children"))
    return {"id": id, "nome": n.get("name"), "tipo": n.get("type"), "setor": n.get("sector"),
            "descricao": det.get("description") or n.get("description"),
            "fonte_legal": _fonte(det or n),
            "ocupantes": [{"id": q.get("id"), "nome": q.get("name"), "desde": q.get("started_at"),
                           "fonte": q.get("source"), "conferido_em": q.get("checked_at"), "nota": q.get("note")}
                          for q in (det.get("people") or [])][:40],
            "blocos_de_dado": blocos, "detalhe": {k: det[k] for k in blocos},
            "pagina": f"{BASE}/br/{id}/"}


def ver_pessoa(id=""):
    """O que o Atlas sabe de uma pessoa: cargos, atividade, gabinete, emendas, patrimônio, viagens."""
    G = grafo()
    p = (G.get("people") or {}).get(id)
    if not p: return {"erro": f"não há pessoa com id {id!r}; use buscar primeiro"}
    try: det = json.loads(_ler(f"people/{id}.json"))
    except Exception: det = {}
    return {"id": id, "nome": p.get("name"), "partido": p.get("party"), "uf": p.get("uf"),
            "cargos": [{"id": q.get("id"), "nome": (G["nodes"].get(q.get("id")) or {}).get("name"),
                        "desde": q.get("started_at"), "modo": q.get("entry_mode")} for q in (p.get("positions") or [])],
            "dados": {k: v for k, v in det.items() if k not in ("id", "positions") and v},
            "pagina": f"{BASE}/br/pessoa/{id}/"}


def quem_nomeia(id=""):
    """As relações legais de um nó: quem nomeia, sabatina, supervisiona, fiscaliza, integra — com a norma."""
    G = grafo()
    if id not in (G["nodes"] or {}): return {"erro": f"não há nó com id {id!r}"}
    saida, entrada = [], []
    for e in (G.get("edges") or {}).values():
        if e.get("source") == id: saida.append(e)
        elif e.get("target") == id: entrada.append(e)
    fmt = lambda e, lado: {"tipo": e.get("type"), "outro_lado": (G["nodes"].get(e.get(lado)) or {}).get("name"),
                           "outro_lado_id": e.get(lado), "norma": e.get("cite"), "norma_url": e.get("cite_url")}
    return {"id": id, "nome": G["nodes"][id].get("name"),
            "o_que_este_no_faz": [fmt(e, "target") for e in saida],
            "o_que_fazem_com_ele": [fmt(e, "source") for e in entrada]}


def o_que_esta_parado(limite=12):
    """Medidas provisórias, vetos e pedidos de CPI à espera do Congresso, com prazo e dias parados."""
    G = grafo(); om = G.get("omissao") or {}
    sai = {"resumo": om.get("summary")}
    for chave in ("mpvs", "vetos", "rcps"):
        itens = om.get(chave) or []
        sai[chave] = [{k: x.get(k) for k in ("id", "title", "date", "days", "legal_deadline", "situacao", "resumo") if x.get(k) is not None}
                      for x in itens[:max(1, min(int(limite or 12), 40))]]
    sai["fonte"] = "Câmara, Senado e Congresso Nacional; resumos em linguagem simples por modelo de linguagem, conferidos contra a ementa"
    return sai


def quem_publica():
    """Quanto cada poder deixa ver: órgãos sem nenhum dado aberto e taxa de negativa na Lei de Acesso."""
    G = grafo()
    fb = G.get("falabr") or {}
    return {"fala_br": {"ano": fb.get("ano"), "resumo": fb.get("resumo"),
                        "orgaos_que_mais_negam": (fb.get("mais_negam") or [])[:10],
                        "fonte": fb.get("fonte"), "lido_em": fb.get("generated_at")},
            "pagina": f"{BASE}/quem-publica/",
            "nota": "A contagem por órgão e por poder está na página; aqui vai o que cabe num resultado."}


FERRAMENTAS = [
    ("buscar", "Acha órgão, cargo ou pessoa no governo federal pelo nome, sigla ou parte dele. Comece sempre por aqui para descobrir o id.",
     {"type": "object", "properties": {"termo": {"type": "string", "description": "nome, sigla ou parte"},
                                       "tipo": {"type": "string", "description": "filtro opcional: department, dept_head, commission, elected, pessoa"},
                                       "limite": {"type": "integer", "description": "máximo de resultados (padrão 10, teto 50)"}},
      "required": ["termo"]}, buscar),
    ("ver_orgao", "Tudo o que o Atlas sabe de um órgão ou cargo: a norma que o cria, quem o chefia hoje, e os blocos de dado (orçamento, contratos, punições, pedidos de informação, agenda).",
     {"type": "object", "properties": {"id": {"type": "string", "description": "id do nó, como br-ministerio-da-fazenda"}}, "required": ["id"]}, ver_orgao),
    ("ver_pessoa", "O que o Atlas sabe de uma pessoa: cargos que ocupa, atividade parlamentar, gabinete, emendas, patrimônio declarado, viagens.",
     {"type": "object", "properties": {"id": {"type": "string", "description": "id da pessoa, como br-p-cd-204379"}}, "required": ["id"]}, ver_pessoa),
    ("quem_nomeia", "As relações legais de um nó, com a norma de cada uma: quem nomeia, sabatina, supervisiona, fiscaliza e integra quem.",
     {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}, quem_nomeia),
    ("o_que_esta_parado", "Medidas provisórias, vetos e pedidos de CPI à espera do Congresso, com o prazo legal e quantos dias estão parados.",
     {"type": "object", "properties": {"limite": {"type": "integer"}}}, o_que_esta_parado),
    ("quem_publica", "Quanto o governo federal deixa ver: taxa de negativa na Lei de Acesso à Informação e os órgãos que mais negam.",
     {"type": "object", "properties": {}}, quem_publica),
]
POR_NOME = {n: f for n, _, _, f in FERRAMENTAS}


def responder(req):
    m, rid = req.get("method"), req.get("id")
    if m == "initialize":
        return {"protocolVersion": VERSAO, "capabilities": {"tools": {}},
                "serverInfo": {"name": "atlas-da-republica", "version": "1.0.0"},
                "instructions": ("Grafo do governo federal brasileiro: órgãos, cargos, colegiados, quem nomeia quem, "
                                 "e o dinheiro e as punições de cada órgão. Comece por buscar para achar o id. "
                                 "Toda resposta traz a fonte oficial e a data da leitura: cite-as, e não afirme o que "
                                 "o resultado não disser. Dado que falta aparece como ausente, nunca como zero.")}
    if m in ("notifications/initialized", "notifications/cancelled"): return None
    if m == "tools/list":
        return {"tools": [{"name": n, "description": d, "inputSchema": e} for n, d, e, _ in FERRAMENTAS]}
    if m == "tools/call":
        p = req.get("params") or {}
        fn = POR_NOME.get(p.get("name"))
        if not fn: return {"content": [{"type": "text", "text": f"ferramenta desconhecida: {p.get('name')}"}], "isError": True}
        try:
            r = fn(**(p.get("arguments") or {}))
        except TypeError as e:
            return {"content": [{"type": "text", "text": f"argumento inválido: {e}"}], "isError": True}
        except Exception as e:
            return {"content": [{"type": "text", "text": f"não consegui ler o Atlas: {type(e).__name__}: {e}"}], "isError": True}
        return {"content": [{"type": "text", "text": json.dumps(r, ensure_ascii=False, indent=1)}]}
    if m == "ping": return {}
    raise LookupError(m)


def main():
    for linha in sys.stdin:
        linha = linha.strip()
        if not linha: continue
        try: req = json.loads(linha)
        except Exception: continue
        try:
            res = responder(req)
        except LookupError as e:
            res = None
            if req.get("id") is not None:
                print(json.dumps({"jsonrpc": "2.0", "id": req["id"], "error": {"code": -32601, "message": f"método não suportado: {e}"}}), flush=True)
            continue
        except Exception as e:
            if req.get("id") is not None:
                print(json.dumps({"jsonrpc": "2.0", "id": req["id"], "error": {"code": -32603, "message": str(e)}}), flush=True)
            continue
        if res is not None and req.get("id") is not None:
            print(json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": res}, ensure_ascii=False), flush=True)


if __name__ == "__main__": main()
