#!/usr/bin/env python3
"""e-Agendas (CGU) → data/generated/agendas.yaml: agenda pública dos ocupantes de cargos do Executivo federal.

Fonte: e-Agendas, Sistema Eletrônico de Agendas do Poder Executivo Federal (Lei 12.813/2013; Decreto 10.889/2021),
https://eagendas.cgu.gov.br. A API oficial (/api/v2, documentada em /api/docs e em
github.com/cgugovbr/eagendas-publico/tree/main/api-consulta) exige token pessoal gerado após login gov.br; este
script usa em vez disso as rotas públicas que o próprio site consulta, sem autenticação:
  GET /pesquisa/orgaos/ativo/true                                              órgãos ativos (id, sigla, nome)
  GET /pesquisa/agentes-publicos-obrigados-por-orgao/orgao/{orgao_id}/ativo/{true|false|null}
                                                                                agentes obrigados do órgão (pertenencia_id,
                                                                                nome, cargo, tipo_exercicio, fecha_inicio,
                                                                                cargo_confianca.autoridade_maxima_orgao)
  GET /?filtro_servidor={pertenencia_id}&filtro_orgao={orgao_id}&tipo_filtro=ap
                                                                                página do calendário do agente; traz TODOS os
                                                                                compromissos desde 2023 em ng-init="events=[..]"
                                                                                (tipo, title, start, end, local, detalhe HTML com
                                                                                participantes, compromisso_id); não filtra data
  GET /info-compromisso/agenda/{pertenencia_id}/compromisso/{compromisso_id}   página de um compromisso (link público)
Participantes vêm no HTML `detalhe`: "Agentes públicos participantes" (NOME (CPF mascarado) / CARGO / ÓRGÃO) e "Agentes
privados participantes" (Nome / Cargo <strong>representando</strong> Entidade (CNPJ)). CPF/CNPJ são descartados; só nome e
entidade são guardados. Afastamentos e presentes/hospitalidades (tipos "afastamento" e "donativo") não contam como compromisso.
Casamento: pessoas de nós dept_head do setor executivo do grafo, por nome completo normalizado (exato ou subsequência de
palavras, para nomes curtos como "Luiz Marinho" ou prefixos de patente militar), desempate pelo órgão do cargo no grafo.
Uso: .venv/bin/python etl/agendas.py [--amostra N] [--janela 90] [--sem-cache]
"""
import re, sys, json, html, time, pathlib, datetime, unicodedata, collections, argparse, urllib.request, urllib.error
import yaml
ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / "build" / "cache-agendas"; CACHE.mkdir(parents=True, exist_ok=True)
OUT = ROOT / "data" / "generated" / "agendas.yaml"
BASE = "https://eagendas.cgu.gov.br"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh) atlas-da-republica/0.1", "Accept": "application/json, text/html"}
TODAY = datetime.date.today()
THROTTLE = 0.35; _last = [0.0]
STOP = {"de", "da", "do", "das", "dos", "e", "a", "o", "em", "para", "por", "sa", "s", "a"}
TIPOS = {"reuniao": "reuniao", "audiencia": "audiencia", "audiencia-publica": "audiencia", "viagem": "viagem",
         "viagem-scdp": "viagem", "evento-publico": "evento"}
IGNORAR = {"afastamento", "donativo", "cargos_confianca", "substituindo"}
CONECT = {"de", "da", "do", "das", "dos", "e", "di", "van", "von", "y"}

def norm(s): return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())).strip()
def fresh(p, max_age_h): return p.exists() and (time.time() - p.stat().st_mtime) < max_age_h * 3600
def get(path, name, max_age_h=20, timeout=180):
    p = CACHE / name
    if fresh(p, max_age_h): return p.read_bytes()
    url = BASE + path
    for tent in range(4):
        wait = THROTTLE - (time.time() - _last[0])
        if wait > 0: time.sleep(wait)
        try:
            print("GET", url, file=sys.stderr)
            data = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read(); _last[0] = time.time()
            p.write_bytes(data); return data
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            _last[0] = time.time(); print(f"  erro ({e}); tentativa {tent + 1}/4", file=sys.stderr); time.sleep(2 * (tent + 1))
    return None

def titulo_nome(s):
    """'VINICIUS MARQUES DE CARVALHO' → 'Vinicius Marques de Carvalho'; deixa em paz o que já tem minúsculas."""
    if not s or s != s.upper(): return s
    return " ".join(w.lower() if w.lower() in CONECT else w.capitalize() for w in s.split())
def limpa(s):
    s = html.unescape(re.sub(r"<[^>]+>", "", s or ""))
    s = re.sub(r"\(?\s*CPF:?[^)]*\)?", "", s); s = re.sub(r"\(?\s*CNPJ:?[^)]*\)?", "", s)
    s = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "", s); s = re.sub(r"\(?\d{2}\)?\s*9?\d{4}-?\d{4}", "", s)  # e-mail, telefone
    return re.sub(r"\s+", " ", s).strip(" -/,;")

def participantes(detalhe):
    """Lista [{nome, cargo, entidade, tipo}] a partir do HTML `detalhe` de um compromisso."""
    out, sec = [], None
    for chunk in re.split(r"<br\s*/?>|</?p>", (detalhe or "").replace("&nbsp;", " ")):
        c = chunk.strip()
        if not c: continue
        if "Agentes públicos participantes" in c: sec = "publico"; continue
        if "Agentes privados participantes" in c: sec = "privado"; continue
        if not c.startswith("- ") or sec is None: continue
        line = c[2:]
        if "representando" in line:
            esq, ent = re.split(r"<strong>\s*representando\s*</strong>|\brepresentando\b", line, maxsplit=1)
            partes = [limpa(x) for x in esq.split(" / ")]
            out.append({"nome": partes[0], "cargo": partes[1] if len(partes) > 1 else None, "entidade": limpa(ent) or None, "tipo": "privado"})
        else:
            partes = [limpa(x) for x in line.split(" / ")]
            out.append({"nome": titulo_nome(partes[0]), "cargo": partes[1] if len(partes) > 2 else None,
                        "entidade": partes[-1] if len(partes) > 1 else None, "tipo": sec})
    return [p for p in out if p["nome"]]

def eventos(pert, orgao_id):
    """Compromissos do agente (lista de dicts do FullCalendar), com cache do JSON já extraído."""
    pj = CACHE / f"eventos-{pert}.json"
    if fresh(pj, 20): return json.loads(pj.read_text(encoding="utf-8"))
    raw = get(f"/?filtro_servidor={pert}&filtro_orgao={orgao_id}&tipo_filtro=ap", f"pagina-{pert}.html", max_age_h=0)
    if raw is None: return None
    m = re.search(r'ng-init="events=(.*?)"\s*>', raw.decode("utf-8", "replace"), re.S)
    ev = json.loads(html.unescape(m.group(1))) if m else []
    pj.write_text(json.dumps(ev, ensure_ascii=False), encoding="utf-8"); (CACHE / f"pagina-{pert}.html").unlink(missing_ok=True)
    return ev

def lev1(a, b):
    """Distância de edição ≤ 1 (Moraes/Morais, Antonio/Antônio já normalizados)."""
    if a == b: return True
    if abs(len(a) - len(b)) > 1 or len(a) < 5: return False
    if len(a) == len(b): return sum(x != y for x, y in zip(a, b)) == 1
    s, l = (a, b) if len(a) < len(b) else (b, a)
    for i in range(len(l)):
        if l[:i] + l[i + 1:] == s: return True
    return False
def alinha(g, a):
    """Quantas palavras de `g` aparecem, na ordem, em `a` (igual ou com 1 erro de grafia)."""
    i = 0
    for w in a:
        if i < len(g) and (g[i] == w or lev1(g[i], w)): i += 1
    return i
def sim_orgao(nome_grafo, ag):
    A = set(norm(nome_grafo).split()) - STOP; B = set(norm(f"{ag.get('sigla') or ''} {ag.get('orgao') or ''}").split()) - STOP
    return len(A & B) / len(A | B) if A and B else 0.0

def casar(nome, orgao_nome, cargo_nome, exato, por_token):
    """Devolve (agente, modo) para o nome do grafo, ou (None, None).
    exato: nome completo normalizado igual; subsequencia: todas as palavras do nome do grafo aparecem, na ordem, no nome do
    e-Agendas (nomes curtos, patentes militares) ou vice-versa (e-Agendas omite o último sobrenome); fuzzy: ≥3 palavras em
    ordem com até 1 erro de grafia, faltando no máximo uma, e o órgão do grafo parecido com o do e-Agendas."""
    n = norm(nome); toks = [t for t in n.split() if t not in CONECT]
    cands = [(a, "exato") for a in exato.get(n, [])]
    if not cands and len(toks) >= 2:
        vistos = set()
        for a in por_token.get(toks[0], []) + por_token.get(toks[-1], []):
            if a["pertenencia_id"] in vistos: continue
            vistos.add(a["pertenencia_id"])
            at = [t for t in norm(a["nome"]).split() if t not in CONECT]
            if at[0] != toks[0] and toks[0] not in at: continue
            m = alinha(toks, at)
            if m == len(toks): cands.append((a, "subsequencia"))
            elif m >= 3 and alinha(at, toks) == len(at): cands.append((a, "subsequencia"))
            elif m >= 3 and m >= min(len(toks), len(at)) - 1 and sim_orgao(orgao_nome, a) >= 0.3: cands.append((a, "fuzzy"))
    if not cands: return None, None
    dirigente = any(k in norm(cargo_nome) for k in ("ministro", "presidente", "dirigente", "diretor geral", "comandante", "superintendente", "secretario"))
    def score(c):
        a = c[0]; cc = a.get("cargo_confianca") or {}
        return (sim_orgao(orgao_nome, a), a.get("fecha_termino") is None, bool(cc.get("autoridade_maxima_orgao")) if dirigente else 0,
                a.get("tipo_exercicio") == "Titular", a.get("fecha_inicio") or "")
    cands.sort(key=score, reverse=True)
    a, modo = cands[0]
    if len({c[0]["nome"] for c in cands}) > 1 and sim_orgao(orgao_nome, a) == 0: return None, None  # homônimos sem órgão que desempate
    return a, modo

JUNK = {"interesse proprio", "interesse pessoal", "particular", "nao se aplica", "nao informado", "nao ha", "proprio", "pessoa fisica",
        "cidadao", "cidada", "sem vinculo", "autonomo", "autonoma", "na", "n a", "nenhuma", "nenhum"}
def entidade_externa(ent, org_nome, sigla):
    """Entidade digitada livremente no e-Agendas; descarta o próprio órgão da pessoa (em qualquer grafia) e rótulos vazios."""
    n = norm(ent)
    if not n or n in JUNK: return None
    toks = set(n.split())
    if norm(sigla) and norm(sigla) in toks: return None
    A = toks - STOP; B = set(norm(org_nome).split()) - STOP
    if A and B and len(A & B) / len(A | B) >= 0.6: return None
    # chave de agregação: a sigla, quando escrita como "SIGLA - Nome" ou "Nome - SIGLA" (grafias variam a cada registro)
    m = re.match(r"^\s*([A-Za-z0-9./]{2,12})\s*[-–]\s+\S", ent) or re.search(r"\S\s+[-–]\s*([A-Za-z]{2,12})\s*$", ent)
    if m and norm(m.group(1)) and norm(m.group(1)) not in STOP: return norm(m.group(1))
    return n

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--amostra", type=int, default=0); ap.add_argument("--janela", type=int, default=90)
    ap.add_argument("--sem-cache", action="store_true"); args = ap.parse_args()
    if args.sem_cache:
        for f in CACHE.glob("*"): f.unlink()
    janela = args.janela; ini = TODAY - datetime.timedelta(days=janela); ini_ano = datetime.date(TODAY.year, 1, 1)
    g = json.load(open(ROOT / "build" / "graph.br.json", encoding="utf-8")); N = g["nodes"]
    # 1) órgãos e agentes obrigados
    orgaos = json.loads(get("/pesquisa/orgaos/ativo/true", "orgaos.json"))
    agentes = []
    for o in orgaos:
        d = get(f"/pesquisa/agentes-publicos-obrigados-por-orgao/orgao/{o['id']}/ativo/null", f"agentes-{o['id']}.json")
        for a in (json.loads(d) if d else []):
            a["orgao"] = a.get("orgao") or o["nome"]; a["sigla"] = a.get("sigla") or o["sigla"]; agentes.append(a)
    exato = collections.defaultdict(list); por_token = collections.defaultdict(list)
    for a in agentes:
        n = norm(a["nome"]); exato[n].append(a)
        for t in set(n.split()): por_token[t].append(a)
    print(f"e-Agendas: {len(orgaos)} órgãos ativos, {len(agentes)} vínculos de agentes obrigados", file=sys.stderr)
    # 2) pessoas do grafo
    pessoas = {}  # pessoa_id → {nome, nos:[(no_id, head_of)]}
    for n in N.values():
        if n.get("type") != "dept_head" or n.get("sector") != "executivo": continue
        for p in n.get("people") or []:
            if not (p.get("id") and p.get("name")): continue
            e = pessoas.setdefault(p["id"], {"nome": p.get("full_name") or p["name"], "nos": []})
            e["nos"].append((n["id"], n.get("head_of"), n.get("name")))
    casados, nao_casados, modos = {}, [], collections.Counter()
    for pid, e in pessoas.items():
        no_id, head_of, cargo_nome = e["nos"][0]
        a, modo = casar(e["nome"], (N.get(head_of) or {}).get("name") or "", cargo_nome, exato, por_token)
        if a: casados[pid] = a; modos[modo] += 1
        else: nao_casados.append(e["nome"])
    print(f"grafo: {len(pessoas)} pessoas em cargos do Executivo; casadas {len(casados)} ({dict(modos)}); não casadas {len(nao_casados)}", file=sys.stderr)
    if args.amostra: casados = dict(list(casados.items())[:args.amostra])
    # 3) compromissos
    people = {}
    por_orgao = collections.defaultdict(lambda: {"compromissos_90d": 0, "pessoas": set(), "ent": collections.Counter(), "grafia": collections.defaultdict(collections.Counter)})
    sem_agenda = []
    for k, (pid, a) in enumerate(casados.items(), 1):
        pert, org_id, org_nome = a["pertenencia_id"], a["orgao_id"], a["orgao"]
        print(f"[{k}/{len(casados)}] {a['nome']} ({a['sigla']})", file=sys.stderr)
        ev = eventos(pert, org_id)
        if ev is None: print("  falhou", file=sys.stderr); continue
        vistos, comps = set(), []
        for x in ev:
            cal = x.get("calendar") or x.get("slug_tipo_evento") or ""
            if cal in IGNORAR: continue
            key = x.get("compromisso_id") or ("v", x.get("viagem_id")) or x.get("title")
            if key in vistos: continue
            vistos.add(key)
            try: d = datetime.date.fromisoformat((x.get("start") or "")[:10])
            except ValueError: continue
            if d > TODAY: continue
            comps.append((d, x, TIPOS.get(cal, "outros")))
        comps.sort(key=lambda t: (t[0], t[1].get("start") or ""), reverse=True)
        jan = [c for c in comps if c[0] >= ini]; ano = [c for c in comps if c[0] >= ini_ano]
        por_tipo = collections.Counter(t for _, _, t in jan)
        ent = collections.Counter(); grafia = collections.defaultdict(collections.Counter); recentes = []
        for d, x, t in jan:
            parts = participantes(x.get("detalhe"))
            ext = set()
            for p in parts:
                k = entidade_externa(p["entidade"], org_nome, a.get("sigla")) if p["entidade"] else None
                if k: ext.add(k); grafia[k][p["entidade"]] += 1
            for en in ext: ent[en] += 1
            if t in ("reuniao", "audiencia") and len(recentes) < 8:
                lista = [{"nome": p["nome"], "entidade": None if norm(p["entidade"]) in JUNK else p["entidade"]}
                         for p in parts if norm(p["nome"]) != norm(a["nome"])][:20]
                titulo = re.sub(r"^(Reunião|Audiência pública|Audiência|Evento|Viagem)\s*-\s*", "", x.get("title") or "").strip()
                recentes.append({"data": d.isoformat(), "hora": (x.get("start") or "")[11:16] or None, "titulo": titulo, "tipo": t,
                                 "local": x.get("local") or None, "participantes": lista})
        people[pid] = {"agente": titulo_nome(a["nome"]), "cargo_eagendas": a.get("cargo"), "orgao": org_nome, "sigla": a.get("sigla"),
                       "pertenencia_id": pert, "url": f"{BASE}/?filtro_servidor={pert}&filtro_orgao={org_id}&tipo_filtro=ap",
                       "desde": a.get("fecha_inicio"), "compromissos_90d": len(jan), "compromissos_ano": len(ano), "compromissos_total": len(comps),
                       "ultimo": comps[0][0].isoformat() if comps else None,
                       "por_tipo": {t: por_tipo[t] for t in ("reuniao", "audiencia", "evento", "viagem", "outros") if por_tipo[t]},
                       "entidades_top": [{"nome": grafia[n_].most_common(1)[0][0], "n": c} for n_, c in ent.most_common(10)], "recentes": recentes}
        if not comps: sem_agenda.append(titulo_nome(a["nome"]))
        for no_id, head_of, _ in pessoas[pid]["nos"]:
            if not head_of or pid in por_orgao[head_of]["pessoas"]: continue
            po = por_orgao[head_of]; po["pessoas"].add(pid); po["compromissos_90d"] += len(jan); po["ent"].update(ent)
            for k, g_ in grafia.items(): po["grafia"][k].update(g_)
    orgs = {oid: {"nome": (N.get(oid) or {}).get("name"), "pessoas": len(v["pessoas"]), "compromissos_90d": v["compromissos_90d"],
                  "entidades_top": [{"nome": v["grafia"][n_].most_common(1)[0][0], "n": c} for n_, c in v["ent"].most_common(10)]}
            for oid, v in sorted(por_orgao.items(), key=lambda kv: -kv[1]["compromissos_90d"])}
    out = {"generated_at": TODAY.isoformat(), "fonte": f"{BASE} (rotas públicas /pesquisa/orgaos, /pesquisa/agentes-publicos-obrigados-por-orgao e /?filtro_servidor=...)",
           "janela_dias": janela, "janela_inicio": ini.isoformat(), "pessoas_casadas": len(people), "pessoas_nao_casadas": len(nao_casados),
           "people": people, "orgaos": orgs, "sem_agenda_publicada": sem_agenda, "nao_casados": nao_casados}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("# GERADO por etl/agendas.py. Não edite à mão.\n" + yaml.dump(out, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    tot = sum(p["compromissos_90d"] for p in people.values())
    print(f"agendas: {len(people)} pessoas, {tot} compromissos nos últimos {janela} dias, {len(orgs)} órgãos; sem agenda {len(sem_agenda)}; não casados {len(nao_casados)}")
    for pid, v in sorted(people.items(), key=lambda kv: -kv[1]["compromissos_90d"])[:5]:
        print("  ", pid, v["compromissos_90d"], v["por_tipo"], "|", ", ".join(e["nome"] for e in v["entidades_top"][:3]))
    if nao_casados: print("  não casados:", "; ".join(nao_casados))

if __name__ == "__main__": main()
