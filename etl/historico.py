#!/usr/bin/env python3
"""Wikidata (API de ações, sem SPARQL) → data/generated/historico.yaml (+ data/generated/historico-qids.yaml)

Histórico de ocupantes de cada cargo de cúpula desde 1985.

Etapa 1 — de onde vem o item do cargo:
  - data/wikidata-overrides.yaml (curado) > data/generated/historico-qids.yaml (descobertos/corrigidos aqui) >
    data/generated/wikidata-map.yaml (etl/wikidata.py). Todo QID é validado: precisa ser um cargo (P31 em
    posto/cargo público ou subclasse) — listas da Wikipédia e itens errados são descartados e vão para a descoberta.
  - Descoberta (rota `busca`): wbsearchentities com o nome do cargo e variantes ("Ministro da X do Brasil"…),
    aceitando só cargos brasileiros (P17 = Q155 ou "Brasil" no rótulo) com ≥ 3 pessoas em haswbstatement:P39=QID.
  - Sem cargo no Wikidata (rota `org_item`): lê no item do órgão (org_item do mapa, ou busca pelo nome do órgão)
    as declarações P488/P169/P1037/P6/P35 (presidente, CEO, diretor…) com P580/P582 — só cargos de 1 vaga.
  Os QIDs descobertos ficam em data/generated/historico-qids.yaml (cargo_id → {qid, rota, label}) para reuso.

Etapa 2 — histórico: pessoas com P39 = cargo (busca CirrusSearch `haswbstatement:P39=QID`), lidas em lotes com
  wbgetentities; qualificadores P580 (início; P585 quando só há data pontual), P582 (fim), P1365/P1366
  (substituiu/substituído por), P2868 (papel, ex.: interino); P569/P570 (nascimento/morte). Ordena por início e
  calcula ocupantes, mediana de duração dos mandatos encerrados e, no Executivo, a contagem por presidente em cujo
  governo cada mandato começou (data/presidentes.yaml). Compara o ocupante atual do grafo (build/graph.br.json)
  com o mandato mais recente do Wikidata.

Uso: .venv/bin/python etl/historico.py [--amostra N] [--only id1,id2] [--limit N]
"""
import json, sys, time, pathlib, argparse, re, statistics, datetime, urllib.request, urllib.parse, unicodedata
import yaml
ROOT = pathlib.Path(__file__).resolve().parent.parent
API = "https://www.wikidata.org/w/api.php"
UA = {"User-Agent": "atlas-da-republica/0.1 (https://github.com/atlas-da-republica; etl)"}
CACHE = ROOT / "build" / "cache-historico.json"
QIDS_PATH = ROOT / "data" / "generated" / "historico-qids.yaml"
cache = json.load(open(CACHE)) if CACHE.exists() else {}
DESDE = "1985"
BRASIL = "Q155"
AMOSTRA_FIXA = ("br-supremo-tribunal-federal-ministro", "br-ministro-de-estado-da-fazenda", "br-presidente-do-banco-central")
INTERINO_QIDS = {"Q4164871"}  # "acting/interim position holder" como papel (P2868); complementado por rótulo
CLASSES_CARGO = {"Q4164871", "Q294414", "Q83307", "Q2285706"}  # posto, cargo público, ministro, chefe de governo (ou subclasse direta)
PROPS_DIRIGENTE = ("P488", "P169", "P1037", "P6", "P35")  # presidente, CEO, diretor, chefe de governo, chefe de Estado
MIN_HITS = 3
_last_call = 0.0

def call(params):
    global _last_call
    key = json.dumps(params, sort_keys=True)
    if key in cache: return cache[key]
    params = dict(params, format="json")  # sem maxlag: só leitura (o lag do WDQS chega a minutos e bloquearia tudo)
    for attempt in range(5):
        wait = 0.5 - (time.time() - _last_call)
        if wait > 0: time.sleep(wait)  # throttle: ~2 chamadas/s
        try:
            r = urllib.request.Request(API + "?" + urllib.parse.urlencode(params), headers=UA)
            _last_call = time.time()
            data = json.load(urllib.request.urlopen(r, timeout=90))
            if "error" in data and data["error"].get("code") == "maxlag": time.sleep(3 + attempt * 5); continue
            if "error" in data: print("wikidata:", data["error"].get("info"), file=sys.stderr); return {}
            cache[key] = data; return data
        except Exception:
            time.sleep(2 + attempt * 3)
    return {}

def save_cache(): json.dump(cache, open(CACHE, "w"), ensure_ascii=False)

def norm(s): return re.sub(r"[^a-z0-9 ]", "", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()).strip()

def search_holders(qid):
    """Itens com alguma declaração P39 = qid (índice CirrusSearch; não precisa de SPARQL)."""
    ids, offset = [], None
    while True:
        p = {"action": "query", "list": "search", "srsearch": f"haswbstatement:P39={qid}", "srnamespace": 0, "srlimit": 500}
        if offset: p["sroffset"] = offset
        d = call(p)
        ids += [s["title"] for s in d.get("query", {}).get("search", []) if s["title"].startswith("Q")]
        offset = d.get("continue", {}).get("sroffset")
        if not offset or len(ids) > 5000: break
    return list(dict.fromkeys(ids))

def count_holders(qid):
    d = call({"action": "query", "list": "search", "srsearch": f"haswbstatement:P39={qid}", "srnamespace": 0, "srlimit": 1})
    return d.get("query", {}).get("searchinfo", {}).get("totalhits", 0)

def wbsearch(text):
    return call({"action": "wbsearchentities", "search": text, "language": "pt", "uselang": "pt", "type": "item", "limit": 10}).get("search", [])

def entities(qids, props="claims|labels"):
    out = {}
    qids = list(dict.fromkeys(qids))
    for i in range(0, len(qids), 50):
        d = call({"action": "wbgetentities", "ids": "|".join(qids[i:i+50]), "props": props, "languages": "pt|en"})
        out.update(d.get("entities", {}))
    return out

def label(ent): return (ent.get("labels", {}).get("pt") or ent.get("labels", {}).get("en") or {}).get("value")

def tval(snak):
    """Data ISO com a precisão disponível: 9 = ano, 10 = mês, 11 = dia."""
    try: v = snak["datavalue"]["value"]; t = v["time"]; prec = v.get("precision", 11)
    except Exception: return None
    m = re.match(r"^[+-](\d{4})-(\d{2})-(\d{2})", t)
    if not m: return None
    y, mo, d = m.groups()
    if prec <= 9 or mo == "00": return y
    if prec == 10 or d == "00": return f"{y}-{mo}"
    return f"{y}-{mo}-{d}"

def qval(snak):
    try: return snak["datavalue"]["value"]["id"]
    except Exception: return None

def ids_of(claims, prop): return [q for q in (qval(c.get("mainsnak", {})) for c in claims.get(prop, []) if c.get("rank") != "deprecated") if q]

def first_val(claims, prop, fn):
    for c in claims.get(prop, []):
        if c.get("rank") == "deprecated": continue
        v = fn(c.get("mainsnak", {}))
        if v: return v
    return None

def to_date(iso):
    """Preenche datas parciais com o primeiro dia do período."""
    if not iso: return None
    parts = iso.split("-") + ["01", "01"]
    try: return datetime.date(int(parts[0]), int(parts[1]), int(parts[2]))
    except Exception: return None

def q_date(q, prop): return tval(q[prop][0]) if q.get(prop) else None

def mandato_de(qid, ent, q):
    """Registro de mandato a partir dos qualificadores `q` de uma declaração (P39 da pessoa ou P488 do órgão)."""
    claims = ent.get("claims", {})
    inicio, fim = q_date(q, "P580"), q_date(q, "P582")
    pontual = None
    if not inicio and not fim and q.get("P585"): inicio = pontual = q_date(q, "P585")  # só data pontual: vale como início aproximado
    return {"qid": qid, "nome": label(ent), "inicio": inicio, "fim": fim, "interino": False, "papel_qids": [x for x in (qval(s) for s in q.get("P2868", [])) if x],
            "substituiu": qval(q["P1365"][0]) if q.get("P1365") else None, "substituido_por": qval(q["P1366"][0]) if q.get("P1366") else None,
            "data_pontual": pontual, "nascimento": first_val(claims, "P569", tval), "morte": first_val(claims, "P570", tval)}

def mandatos_p39(pos_qid):
    """Rota P39: pessoas que declaram o cargo."""
    ids = search_holders(pos_qid)
    out = []
    for qid, ent in entities(ids).items():
        claims = ent.get("claims", {})
        inst = ids_of(claims, "P31")
        if inst and "Q5" not in inst: continue
        for st in claims.get("P39", []):
            if qval(st.get("mainsnak", {})) != pos_qid or st.get("rank") == "deprecated": continue
            out.append(mandato_de(qid, ent, st.get("qualifiers", {})))
    return out

def mandatos_org(org_qid):
    """Rota org_item: dirigentes declarados no item do órgão (P488/P169/P1037/P6/P35)."""
    org = entities([org_qid]).get(org_qid) or {}
    refs = []
    for prop in PROPS_DIRIGENTE:
        for c in org.get("claims", {}).get(prop, []):
            if c.get("rank") == "deprecated": continue
            p = qval(c.get("mainsnak", {}))
            if p: refs.append((p, c.get("qualifiers", {}), prop))
    people = entities([r[0] for r in refs]) if refs else {}
    out, seen = [], set()
    for p, q, prop in refs:
        ent = people.get(p)
        if not ent: continue
        m = mandato_de(p, ent, q); m["via"] = prop
        k = (p, m["inicio"], m["fim"])
        if k in seen: continue
        seen.add(k); out.append(m)
    return out

def desde_1985(m):
    if m["fim"] and m["fim"] < DESDE: return False
    if not m["fim"] and m["inicio"] and m["inicio"] < DESDE: return False  # sem fim e anterior a 1985: lacuna do Wikidata
    return bool(m["inicio"] or m["fim"])

def presidente_em(iso, presidentes):
    d = to_date(iso)
    if not d: return None
    for p in presidentes:
        if p["start"] <= d <= (p["end"] or datetime.date.today()): return p["short"]
    return None

def mesma_pessoa(a, b):
    na, nb = norm(a), norm(b)
    if not na or not nb: return False
    if na == nb: return True
    ta, tb = set(na.split()), set(nb.split())
    small, big = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    return len(small) >= 2 and small <= big

# ---------- descoberta de itens de cargo ----------
_classe_cache = {}
def eh_cargo(ent):
    """P31 é posto/cargo público (ou subclasse direta de um deles)."""
    inst = ids_of(ent.get("claims", {}), "P31")
    if not inst: return False
    if set(inst) & CLASSES_CARGO: return True
    faltam = [q for q in inst if q not in _classe_cache]
    for q, e in entities(faltam, "claims").items() if faltam else []: _classe_cache[q] = bool(set(ids_of(e.get("claims", {}), "P279")) & CLASSES_CARGO)
    return any(_classe_cache.get(q) for q in inst)

def brasileiro(ent):
    if BRASIL in ids_of(ent.get("claims", {}), "P17"): return True
    lab = (label(ent) or "") + " " + " ".join(v.get("value", "") for v in ent.get("descriptions", {}).values())
    return bool(re.search(r"bra[sz]il", lab, re.I))

def variantes(nome, org_nome):
    vs = [nome, nome + " do Brasil"]
    m = re.match(r"^Ministro de Estado Chefe d[aeo]s? (.+)$", nome)
    if m: vs += ["Ministro-Chefe da " + m.group(1), "ministro chefe da " + m.group(1) + " do Brasil"]
    m = re.match(r"^Ministro de Estado (d[aeo]s?) (.+)$", nome)
    if m: vs += [f"Ministro {m.group(1)} {m.group(2)} do Brasil", f"ministro {m.group(1)} {m.group(2)}"]
    m = re.match(r"^(Presidente|Comandante|Diretor-Geral|Diretor-Presidente|Superintendente|Procurador-Geral|Defensor Público-Geral)\b", nome)
    if m and org_nome: vs.append(f"{m.group(1)} do {org_nome}" if not re.match(r"^(Agência|Fundação|Empresa|Comissão|Companhia|Escola|Autoridade|Secretaria|Superintendência|Procuradoria|Defensoria|Marinha|Força|Polícia)", org_nome) else f"{m.group(1)} da {org_nome}")
    return list(dict.fromkeys(v for v in vs if v))

def descobrir_cargo(nome, org_nome):
    """(qid, label, hits) do item de cargo brasileiro com ≥ MIN_HITS pessoas, ou None."""
    cands = []
    for v in variantes(nome, org_nome):
        for s in wbsearch(v):
            desc = (s.get("description") or "").lower()
            if re.search(r"wikinot|wikinews|lista|list of|artigo|article|categoria", desc): continue
            if s["id"] not in [c[0] for c in cands]: cands.append((s["id"], s.get("label"), v))
    if not cands: return None
    ents = entities([c[0] for c in cands], "claims|labels|descriptions")
    for qid, lab, v in cands:
        e = ents.get(qid) or {}
        if not eh_cargo(e) or not brasileiro(e): continue
        hits = count_holders(qid)
        if hits >= MIN_HITS: return qid, label(e) or lab, hits
    return None

def descobrir_org(org_nome, aliases):
    """Item do órgão brasileiro (P17 = Q155) por nome/siglas, ou None."""
    for v in [org_nome] + [a for a in (aliases or []) if len(a) >= 3][:2]:
        cands = [s for s in wbsearch(v) if not re.search(r"wikinot|lista|artigo|human|humano|pessoa|cargo|position", (s.get("description") or "").lower())]
        ents = entities([s["id"] for s in cands], "claims|labels")
        for s in cands:
            e = ents.get(s["id"]) or {}
            if BRASIL in ids_of(e.get("claims", {}), "P17") and not eh_cargo(e) and "Q5" not in ids_of(e.get("claims", {}), "P31"):
                return s["id"], label(e)
    return None

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--amostra", type=int); ap.add_argument("--only"); ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    t0 = time.time()
    g = json.load(open(ROOT / "build" / "graph.br.json", encoding="utf-8"))["nodes"]
    mapa = yaml.safe_load(open(ROOT / "data" / "generated" / "wikidata-map.yaml", encoding="utf-8")) or {}
    ov_path = ROOT / "data" / "wikidata-overrides.yaml"
    overrides = (yaml.safe_load(open(ov_path, encoding="utf-8")) or {}) if ov_path.exists() else {}
    conhecidos = (yaml.safe_load(open(QIDS_PATH, encoding="utf-8")) or {}) if QIDS_PATH.exists() else {}
    presidentes = yaml.safe_load(open(ROOT / "data" / "presidentes.yaml", encoding="utf-8")) or []
    for p in presidentes:
        p["start"] = to_date(str(p["start"])); p["end"] = to_date(str(p["end"])) if p.get("end") else None
    presidentes.sort(key=lambda p: p["start"])

    # ---- etapa 1: item por cargo (override > historico-qids > mapa), validado por P31 ----
    todos = sorted(set(mapa) | set(overrides) | set(conhecidos))
    if a.only: todos = [c for c in todos if c in a.only.split(",")]
    if a.amostra:
        fixos = [c for c in AMOSTRA_FIXA if c in todos]
        todos = fixos + [c for c in todos if c not in fixos][:max(0, a.amostra - len(fixos))]
    if a.limit: todos = todos[:a.limit]
    fontes = {}  # cid -> (qid, rota)
    for cid in todos:
        ov = overrides.get(cid)
        if ov is False: continue
        k = conhecidos.get(cid) or {}
        if ov: fontes[cid] = (ov, "override")
        elif k.get("qid") and k.get("rota") != "org_item": fontes[cid] = (k["qid"], k.get("rota") or "historico-qids")
        elif (mapa.get(cid) or {}).get("qid"): fontes[cid] = (mapa[cid]["qid"], "mapa")
    valid = entities(sorted({q for q, _ in fontes.values()}), "claims|labels|descriptions")
    invalidos = {}
    for cid, (qid, rota) in list(fontes.items()):
        e = valid.get(qid) or {}
        if not eh_cargo(e):
            invalidos[cid] = (qid, label(e)); del fontes[cid]
            print(f"QID inválido para {cid}: {qid} ({label(e)!r}) não é um cargo — vai para a descoberta", file=sys.stderr)
    save_cache()

    # ---- descoberta: busca do cargo, depois dirigentes do órgão ----
    descobertos = dict(conhecidos)
    org_rota = {}  # cid -> org_qid
    for cid in todos:
        if cid in fontes or overrides.get(cid) is False: continue
        node = g.get(cid) or {}; org = g.get(node.get("head_of") or "") or {}
        k = conhecidos.get(cid) or {}
        if k.get("qid") and k.get("rota") == "org_item": org_rota[cid] = k["qid"]; continue
        nome = node.get("name") or cid
        f = descobrir_cargo(nome, org.get("name"))
        if f:
            qid, lab, hits = f
            rota = "corrigido" if cid in invalidos else "busca"
            fontes[cid] = (qid, rota)
            descobertos[cid] = {"qid": qid, "rota": rota, "label": lab, "hits": hits}
            if cid in invalidos: descobertos[cid]["nota"] = f"substitui {invalidos[cid][0]} ({invalidos[cid][1]}), que não é um cargo"
            print(f"descoberto {cid} -> {qid} {lab!r} ({hits} pessoas)", file=sys.stderr)
        elif (node.get("seats") or 1) == 1:
            org_qid = (mapa.get(cid) or {}).get("org_item"); org_lab = None
            if not org_qid and org.get("name"):
                fo = descobrir_org(org["name"], org.get("aliases"))
                if fo: org_qid, org_lab = fo
            if org_qid:
                oe = entities([org_qid], "claims|labels").get(org_qid) or {}
                if BRASIL in ids_of(oe.get("claims", {}), "P17") and any(oe.get("claims", {}).get(p) for p in PROPS_DIRIGENTE):
                    org_rota[cid] = org_qid
                    descobertos[cid] = {"qid": org_qid, "rota": "org_item", "label": label(oe) or org_lab}
                    print(f"órgão {cid} -> {org_qid} {label(oe)!r} (dirigentes no item do órgão)", file=sys.stderr)
        save_cache()
    sem_qid = [c for c in todos if c not in fontes and c not in org_rota and overrides.get(c) is not False]

    # ---- etapa 2: histórico ----
    targets = [(cid, fontes[cid][0], fontes[cid][1]) for cid in todos if cid in fontes] + [(cid, org_rota[cid], "org_item") for cid in todos if cid in org_rota]
    cargos, vazios, papel_qids, todas_duracoes, so_sem_data = {}, [], set(), [], {}
    for i, (cid, qid, rota) in enumerate(targets):
        node = g.get(cid) or {}
        todos_m = mandatos_org(qid) if rota == "org_item" else mandatos_p39(qid)
        ms = [m for m in todos_m if desde_1985(m)]
        sem_data = [{"qid": m["qid"], "nome": m["nome"]} for m in todos_m if not m["inicio"] and not m["fim"]]  # sem P580/P582/P585
        ms.sort(key=lambda m: (m["inicio"] or m["fim"] or "9999", m["fim"] or "9999"))
        if not ms:
            vazios.append(cid)
            if sem_data: so_sem_data[cid] = {"qid": qid, "rota": rota, "nome": node.get("name"), "sem_data": sem_data}
            print(f"[{i+1}/{len(targets)}] {cid} {qid} ({rota}): sem ocupantes datados no Wikidata ({len(sem_data)} sem data)", file=sys.stderr); save_cache(); continue
        duracoes = []
        for m in ms:
            di, df = to_date(m["inicio"]), to_date(m["fim"])
            m["dias"] = (df - di).days if di and df and df >= di else None
            if m["dias"] is not None: duracoes.append(m["dias"])
            papel_qids |= set(m["papel_qids"])
            if node.get("sector") == "executivo": m["presidente"] = presidente_em(m["inicio"], presidentes)
        todas_duracoes += duracoes
        por_presidente = {}
        if node.get("sector") == "executivo":
            for m in ms:
                if m.get("presidente"): por_presidente[m["presidente"]] = por_presidente.get(m["presidente"], 0) + 1
        atual = ((node.get("people") or [{}])[0]).get("name")
        abertos = [m for m in ms if not m["fim"]]
        recente = max(ms, key=lambda m: (m["inicio"] or "", not m["fim"]))
        atualizado = bool(atual) and (any(mesma_pessoa(atual, m["nome"]) for m in abertos) or mesma_pessoa(atual, recente["nome"]))
        no_wd = bool(atual) and (atualizado or any(mesma_pessoa(atual, m["nome"]) for m in todos_m))
        cargos[cid] = {"qid": qid, "rota": rota, "nome": node.get("name"), "ocupantes": len({m["qid"] for m in ms}), "mandatos_n": len(ms),
                       "mediana_dias": int(statistics.median(duracoes)) if duracoes else None, "mandatos": ms,
                       "por_presidente": por_presidente, "ocupante_atual": atual, "wikidata_mais_recente": recente["nome"],
                       "wikidata_atualizado": atualizado, "ocupante_atual_no_wikidata": no_wd, "sem_data_n": len(sem_data), "sem_data": sem_data}
        print(f"[{i+1}/{len(targets)}] {cid} {qid} ({rota}): {len(ms)} mandatos ({len(sem_data)} sem data), {len({m['qid'] for m in ms})} ocupantes, atual={atual!r} wd={recente['nome']!r} ok={atualizado}", file=sys.stderr)
        save_cache()

    # rótulos dos papéis (P2868) para marcar interinos
    papeis = {q: label(e) for q, e in entities(sorted(papel_qids), "labels").items()} if papel_qids else {}
    for c in cargos.values():
        for m in c["mandatos"]:
            m["interino"] = any(q in INTERINO_QIDS or re.search(r"interin|acting|substitut|provis|tempor", (papeis.get(q) or "").lower()) for q in m["papel_qids"])
            m["papel"] = ", ".join(papeis.get(q) or q for q in m["papel_qids"]) or None
            del m["papel_qids"]
            if not m.get("data_pontual"): m.pop("data_pontual", None)
    save_cache()

    class D(yaml.SafeDumper):
        def increase_indent(self, flow=False, indentless=False): return super().increase_indent(flow, False)
    if descobertos != conhecidos or not QIDS_PATH.exists():
        QIDS_PATH.write_text("# GERADO por etl/historico.py: itens do Wikidata descobertos para cargos sem QID no wikidata-map (rota busca / org_item)\n"
                             "# ou corrigidos (rota corrigido). Pode ser editado à mão: entradas existentes são reaproveitadas como cache.\n"
                             + yaml.dump(dict(sorted(descobertos.items())), Dumper=D, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    com_data = sum(1 for c in cargos.values() for m in c["mandatos"] if m["inicio"] and m["fim"])
    resumo = {"cargos_com_historico": len(cargos), "cargos_por_rota": {r: sum(1 for c in cargos.values() if c["rota"] == r) for r in sorted({c["rota"] for c in cargos.values()})},
              "cargos_sem_qid": len(sem_qid), "cargos_vazios_no_wikidata": len(vazios), "qids_invalidos": {c: q for c, (q, _) in invalidos.items()},
              "mandatos": sum(c["mandatos_n"] for c in cargos.values()), "mandatos_com_inicio_e_fim": com_data,
              "mandatos_sem_data": sum(c["sem_data_n"] for c in cargos.values()) + sum(len(c["sem_data"]) for c in so_sem_data.values()),
              "mediana_geral_dias": int(statistics.median(todas_duracoes)) if todas_duracoes else None,
              "atualizados": sum(1 for c in cargos.values() if c["wikidata_atualizado"]), "sem_qid": sem_qid, "vazios": vazios}
    out = {"generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "fonte": "wikidata.org — P39 (cargo ocupado) com qualificadores P580/P582/P585/P1365/P1366/P2868 via busca haswbstatement; "
                    "ou P488/P169/P1037 no item do órgão (rota org_item); desde 1985",
           "resumo": resumo, "cargos": cargos, "cargos_so_sem_data": so_sem_data}
    (ROOT / "data" / "generated" / "historico.yaml").write_text("# GERADO por etl/historico.py. Não edite à mão.\n" + yaml.dump(out, Dumper=D, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    print(f"cargos alvo={len(targets)} com histórico={len(cargos)} {resumo['cargos_por_rota']} vazios={len(vazios)} sem qid={len(sem_qid)} inválidos={len(invalidos)} "
          f"mandatos={resumo['mandatos']} com início e fim={com_data} sem data={resumo['mandatos_sem_data']} mediana={resumo['mediana_geral_dias']} tempo={time.time()-t0:.0f}s")

if __name__ == "__main__": main()
