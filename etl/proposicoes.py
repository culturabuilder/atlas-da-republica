#!/usr/bin/env python3
"""Produção legislativa de deputados e senadores → data/generated/proposicoes.yaml (proposições apresentadas, relatorias, normas).

Janela: o ano legislativo corrente (desde 2 de fevereiro, CF art. 57). Pessoas: build/graph.br.json → people
(deputados br-p-cd-<idCamara>, senadores br-p-sf-<codigoSenado>).

Fontes:
  Câmara — arquivos em lote (uma leitura em vez de milhares de chamadas à API; conferido: a lista por autor bate com
    /api/v2/proposicoes?idDeputadoAutor):
    https://dadosabertos.camara.leg.br/arquivos/proposicoes/csv/proposicoes-{ano}.csv          (ementa, tipo, último status/situação)
    https://dadosabertos.camara.leg.br/arquivos/proposicoesAutores/csv/proposicoesAutores-{ano}.csv (autores; idDeputadoAutor)
    https://dadosabertos.camara.leg.br/arquivos/proposicoesTemas/csv/proposicoesTemas-{ano}.csv      (temas)
    https://dadosabertos.camara.leg.br/arquivos/proposicoesTramitacoes/csv/proposicoesTramitacoes-{ano}.csv
        (eventos "Designação de Relator(a)" no ano → relatorias, casadas por nome parlamentar)
    O servidor encerra a conexão no meio dos arquivos grandes: o download é retomado com Range até completar.
  Senado — /dadosabertos/processo?codigoParlamentarAutor=&dataInicioApresentacao=  (processos por autor; normaGerada)
           /dadosabertos/processo/relatoria?codigoParlamentar=&dataInicio=          (relatorias designadas no ano)
Uso: .venv/bin/python etl/proposicoes.py [--amostra N[,M]] [--out ARQ]   (N deputados e M senadores; padrão M=N)
"""
import csv, json, sys, re, pathlib, datetime, urllib.request, urllib.error, collections, time, argparse, statistics, unicodedata
import yaml
ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / "build" / "cache-proposicoes"; CACHE.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (Macintosh) atlas-da-republica/0.1", "Accept": "application/json"}
TODAY = datetime.date.today(); SINCE = datetime.date(TODAY.year, 2, 2)  # início do ano legislativo (CF art. 57)
THROTTLE = 0.3
csv.field_size_limit(10**9)

# classificação das siglas (Câmara e Senado); conferida contra descricaoTipo do arquivo de proposições
PROJETOS = {"PL", "PLP", "PEC", "PDL", "PDC", "PDS", "PDN", "PRC", "PRS", "PRN", "MPV", "PLV", "PLN", "SUG", "PFC", "PLC", "PLS"}
REQ_PREFIX = ("REQ", "RIC", "RCP", "RPD", "RQS", "RQN", "RQC", "R.S", "RQI", "RQE", "RQF", "RQJ")  # RPD/RPDR = requerimentos de pauta (plenário)
EMENDA_PREFIX = ("EM", "ESB", "SBE", "EPP", "EPV", "SSP")
PARECERES = {"PRL", "PRLP", "PRLE", "PAR", "PARF", "PPP", "PEP", "PES", "PSS", "PPR", "PRV", "RDF", "SBT", "SBT-A", "SBR", "EMR", "EMC-A", "SBE-A", "ERD", "CVO", "RRL", "REL", "REL-A", "RLP"}  # produtos de relatoria/comissão
EXPEDIENTE = {"DOC", "ATA", "MSC", "OF", "SIT", "CAC", "PROC", "INA", "SOR", "TVR", "MCN", "OBJ"}  # ofícios, atas, mensagens: não contam como apresentadas
def classe(sigla):
    s = (sigla or "").upper()
    if s in PROJETOS: return "projetos"
    if s in PARECERES: return "pareceres"
    if s in EXPEDIENTE: return "expediente"
    if s.startswith(REQ_PREFIX): return "requerimentos"
    if s.startswith(EMENDA_PREFIX): return "emendas"
    return "outros"  # INC, DTQ, VTS, REC, REP…
def norm(s): return re.sub(r"\s+", " ", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()).strip()
def curta(s, n=160):
    s = re.sub(r"\s+", " ", s or "").strip(); return s if len(s) <= n else s[:n - 1].rstrip() + "…"
def mediana(xs): return round(statistics.median(xs), 1) if xs else None
def dkey(s): return int(re.sub(r"\D", "", (s or "")[:19]) or 0)  # "2026-03-05T14:20:00" → 20260305142000 (ordenável)

# ---------------------------------------------------------------- rede
def fetch_file(url, name, max_age_h=20):
    """Baixa um arquivo grande retomando com Range até o tamanho anunciado (o servidor da Câmara corta a conexão)."""
    p = CACHE / name
    if p.exists() and (datetime.datetime.now() - datetime.datetime.fromtimestamp(p.stat().st_mtime)).total_seconds() < max_age_h * 3600: return p
    part = CACHE / (name + ".part"); have = part.stat().st_size if part.exists() else 0; total = None
    print("GET", url, file=sys.stderr)
    for tentativa in range(60):
        req = urllib.request.Request(url, headers={**UA, "Accept": "*/*", **({"Range": f"bytes={have}-"} if have else {})})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                cr = r.headers.get("Content-Range"); cl = r.headers.get("Content-Length")
                if r.status == 206 and cr: total = int(cr.split("/")[-1])
                elif r.status == 200:
                    total = int(cl) if cl else None
                    if have: have = 0; part.unlink(missing_ok=True)  # servidor ignorou o Range: recomeça
                with open(part, "ab") as f:
                    while True:
                        chunk = r.read(1 << 20)
                        if not chunk: break
                        f.write(chunk); have += len(chunk)
        except urllib.error.HTTPError as e:
            if e.code == 416 and total and have >= total: break
            print(f"  {e} (tentativa {tentativa + 1}, {have} bytes)", file=sys.stderr); time.sleep(2 + tentativa)
        except Exception as e:
            print(f"  {type(e).__name__}: {e} (tentativa {tentativa + 1}, {have} bytes)", file=sys.stderr); time.sleep(2 + tentativa)
        if total is not None and have >= total: break
        if total is None and have: break  # sem tamanho anunciado: assume completo
    else: raise RuntimeError(f"download incompleto: {url} ({have}/{total})")
    part.replace(p); print(f"  ok {have} bytes", file=sys.stderr); return p

def get_json(url, name=None, max_age_h=20, retries=3):
    p = CACHE / name if name else None
    if p and p.exists() and (datetime.datetime.now() - datetime.datetime.fromtimestamp(p.stat().st_mtime)).total_seconds() < max_age_h * 3600:
        return json.load(open(p, encoding="utf-8"))
    for i in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r: data = json.load(r); break
        except Exception as e:
            if i == retries - 1: raise
            print(f"  retry {url}: {e}", file=sys.stderr); time.sleep(2 * (i + 1))
    time.sleep(THROTTLE)
    if p: json.dump(data, open(p, "w", encoding="utf-8"), ensure_ascii=False)
    return data

def rows(path): return csv.DictReader(open(path, encoding="utf-8-sig", newline=""), delimiter=";")
def g(r, k): return (r.get(k) or "").strip()

def resolver_tipos(pids):
    """id de proposição → siglaTipo, via /api/v2/proposicoes?id=a,b,c (100 por chamada); cache acumulado em cd-tipos.json."""
    p = CACHE / "cd-tipos.json"; tipos = json.load(open(p, encoding="utf-8")) if p.exists() else {}
    falta = sorted(x for x in pids if x not in tipos)
    if falta: print(f"câmara: resolvendo tipo de {len(falta)} proposições relatadas ({(len(falta) + 99) // 100} chamadas)", file=sys.stderr)
    for i in range(0, len(falta), 100):
        lote = falta[i:i + 100]
        try: d = get_json("https://dadosabertos.camara.leg.br/api/v2/proposicoes?id=" + ",".join(lote) + "&itens=100")["dados"]
        except Exception as e: print(f"  lote {i} falhou: {e}", file=sys.stderr); continue
        for x in d: tipos[str(x["id"])] = x.get("siglaTipo") or ""
        json.dump(tipos, open(p, "w", encoding="utf-8"))
    return tipos

# ---------------------------------------------------------------- Câmara
def camara(dep_ids, graph_names):
    ano = TODAY.year; since = SINCE.isoformat()
    P = {}
    for r in rows(fetch_file(f"https://dadosabertos.camara.leg.br/arquivos/proposicoes/csv/proposicoes-{ano}.csv", f"proposicoes-{ano}.csv")):
        if g(r, "id") and g(r, "dataApresentacao") >= since: P[r["id"]] = r
    temas = collections.defaultdict(list)
    for r in rows(fetch_file(f"https://dadosabertos.camara.leg.br/arquivos/proposicoesTemas/csv/proposicoesTemas-{ano}.csv", f"proposicoesTemas-{ano}.csv")):
        pid = g(r, "uriProposicao").rsplit("/", 1)[-1]
        if pid in P and g(r, "tema"): temas[pid].append(r["tema"])
    autoria = collections.defaultdict(dict); nomes = {}  # id deputado → {idProposicao: ordemAssinatura}; nome normalizado → id
    for r in rows(fetch_file(f"https://dadosabertos.camara.leg.br/arquivos/proposicoesAutores/csv/proposicoesAutores-{ano}.csv", f"proposicoesAutores-{ano}.csv")):
        did = g(r, "idDeputadoAutor")
        if not did or g(r, "tipoAutor") != "Deputado(a)": continue
        nomes.setdefault(norm(r.get("nomeAutor")), did)
        pid = g(r, "idProposicao")
        if pid in P: autoria[did][pid] = g(r, "ordemAssinatura")
    for n, did in graph_names.items(): nomes.setdefault(n, did)
    # relatorias: designações no ano legislativo (arquivo de tramitações cobre proposições de qualquer ano)
    rx = re.compile(r"Designad[oa] Relator[a]?(?: d[oa] [A-Za-zçãõ ]+?)?,?\s*(?:o |a )?Dep(?:utad[oa])?\.?\s*([^()]+?)\s*\(", re.I)
    rel = collections.defaultdict(dict); n_desig = n_casadas = 0
    for r in rows(fetch_file(f"https://dadosabertos.camara.leg.br/arquivos/proposicoesTramitacoes/csv/proposicoesTramitacoes-{ano}.csv", f"proposicoesTramitacoes-{ano}.csv")):
        if not g(r, "descricaoTramitacao").startswith("Designação de Relator") or g(r, "dataHora")[:10] < since: continue
        n_desig += 1; m = rx.search(g(r, "despacho"))
        did = nomes.get(norm(m.group(1))) if m else None
        if not did: continue
        n_casadas += 1; pid = g(r, "uriProposicao").rsplit("/", 1)[-1]
        rel[did][pid] = g(r, "siglaOrgao")
    print(f"câmara: {len(P)} proposições apresentadas desde {since}; {n_desig} designações de relator, {n_casadas} casadas a deputados", file=sys.stderr)
    # o arquivo de tramitações não traz o tipo da proposição relatada (siglaTipo vazio); para as de anos anteriores, resolve via API em lotes de 100 ids
    tipos = resolver_tipos({pid for d in dep_ids for pid in rel.get(d, {}) if pid not in P})
    tipo = lambda pid: P[pid]["siglaTipo"] if pid in P else tipos.get(pid, "")
    out = {}; todas = set(); ids_norma = set()
    for did in dep_ids:
        props = autoria.get(did, {})
        por_tipo = collections.Counter(P[p]["siglaTipo"] for p in props); cls = collections.Counter(classe(P[p]["siglaTipo"]) for p in props)
        apres = [p for p in props if classe(P[p]["siglaTipo"]) not in ("pareceres", "expediente")]; todas |= set(apres)
        norma = [p for p in apres if "norma jur" in g(P[p], "ultimoStatus_descricaoSituacao").lower()]; ids_norma |= set(norma)
        ordem = sorted(apres, key=lambda p: (0 if classe(P[p]["siglaTipo"]) == "projetos" else 1, -dkey(g(P[p], "dataApresentacao"))))  # projetos primeiro, depois os mais recentes
        ultimas = [{"id": int(p), "sigla": P[p]["siglaTipo"], "numero": int(g(P[p], "numero") or 0), "ano": int(g(P[p], "ano") or 0), "ementa": curta(P[p].get("ementa")),
                    "situacao": g(P[p], "ultimoStatus_descricaoSituacao") or g(P[p], "ultimoStatus_descricaoTramitacao") or None,
                    "orgao": g(P[p], "ultimoStatus_siglaOrgao") or None, "data": (g(P[p], "ultimoStatus_dataHora") or g(P[p], "dataApresentacao"))[:10],
                    "apresentada": g(P[p], "dataApresentacao")[:10], "url": f"https://www.camara.leg.br/propostas-legislativas/{p}"} for p in ordem[:5]]
        tm = collections.Counter(t for p in apres if classe(P[p]["siglaTipo"]) == "projetos" for t in temas.get(p, []))
        rl = rel.get(did, {}); org = collections.Counter(o or "?" for o in rl.values())
        out[f"br-p-cd-{did}"] = {"house": "camara", "window": "ano", "apresentadas": len(apres), "como_primeiro_autor": sum(1 for p in apres if props[p] == "1"),
                                "projetos": cls["projetos"], "requerimentos": cls["requerimentos"], "emendas": cls["emendas"], "outros": cls["outros"], "pareceres_como_relator": cls["pareceres"],
                                "por_tipo": dict(sorted(por_tipo.items(), key=lambda kv: (-kv[1], kv[0]))), "temas": [t for t, _ in tm.most_common(3)],
                                "ultimas": ultimas, "relatorias": len(rl), "relatorias_projetos": sum(1 for p in rl if classe(tipo(p)) == "projetos"),
                                "relatorias_por_orgao": dict(org.most_common(4)), "virou_norma": len(norma)}
    resumo = {"pessoas": len(dep_ids), "com_proposicao": sum(1 for v in out.values() if v["apresentadas"]), "proposicoes_distintas": len(todas), "virou_norma": len(ids_norma),
              "designacoes_relator": n_desig, "designacoes_casadas": n_casadas,
              "mediana_apresentadas": mediana([v["apresentadas"] for v in out.values()]), "mediana_projetos": mediana([v["projetos"] for v in out.values()]),
              "mediana_requerimentos": mediana([v["requerimentos"] for v in out.values()]), "mediana_relatorias": mediana([v["relatorias"] for v in out.values()]),
              "fonte": f"arquivos em lote proposicoes/proposicoesAutores/proposicoesTemas/proposicoesTramitacoes-{ano}.csv (dadosabertos.camara.leg.br)",
              "relatorias_fonte": 'eventos "Designação de Relator(a)" nas tramitações do ano, casados por nome parlamentar (proposições de qualquer ano)'}
    return out, resumo

# ---------------------------------------------------------------- Senado
def sf_sigla(ident): return (ident or "").split(" ")[0]
def senado(sen_ids, names):
    out = {}; todas = set(); ids_norma = set(); erros = 0
    for i, cod in enumerate(sen_ids):
        try:
            procs = get_json(f"https://legis.senado.leg.br/dadosabertos/processo?codigoParlamentarAutor={cod}&dataInicioApresentacao={SINCE}&dataFimApresentacao={TODAY}", f"sf-proc-{cod}.json") or []
            rels = get_json(f"https://legis.senado.leg.br/dadosabertos/processo/relatoria?codigoParlamentar={cod}&dataInicio={SINCE}&dataFim={TODAY}", f"sf-rel-{cod}.json") or []
        except Exception as e:
            print(f"senado {cod} falhou: {e}", file=sys.stderr); erros += 1; out[f"br-p-sf-{cod}"] = {"house": "senado", "window": "ano", "erro": str(e)[:120]}; continue
        procs = [p for p in procs if (p.get("dataApresentacao") or "") >= SINCE.isoformat()]
        todas |= {p["id"] for p in procs}
        nome = norm(names.get(cod, "")); nome_curto = nome.split(" ")[0] if nome else None
        primeiro = 0
        for p in procs:
            a = norm(re.sub(r"^(Senadora?|Deputad[oa])\s+", "", (p.get("autoria") or "").split(",")[0]))
            if nome and (a == nome or a.startswith(nome) or nome.startswith(a)): primeiro += 1
        por_tipo = collections.Counter(sf_sigla(p.get("identificacao")) for p in procs); cls = collections.Counter(classe(sf_sigla(p.get("identificacao"))) for p in procs)
        norma = [p for p in procs if p.get("normaGerada") or (p.get("situacaoAtual") or "").upper().startswith("TRANSFORMADA EM NORMA")]; ids_norma |= {p["id"] for p in norma}
        ordem = sorted(procs, key=lambda p: (0 if classe(sf_sigla(p.get("identificacao"))) == "projetos" else 1, -dkey(p.get("dataApresentacao"))))
        ultimas = []
        for p in ordem[:5]:
            ident = p.get("identificacao") or ""; m = re.match(r"(\S+)\s+(\d+)/(\d{4})", ident)
            sit = p.get("situacaoAtual") or p.get("siglaTipoDeliberacao") or ("Tramitando" if p.get("tramitando") == "Sim" else None)
            ultimas.append({"id": p.get("id"), "sigla": m.group(1) if m else sf_sigla(ident), "numero": int(m.group(2)) if m else None, "ano": int(m.group(3)) if m else None,
                            "ementa": curta(p.get("ementa")), "situacao": sit.capitalize() if sit and sit.isupper() else sit, "orgao": p.get("enteIdentificador") or None,
                            "data": (p.get("dataSituacaoAtual") or p.get("dataDeliberacao") or p.get("dataApresentacao") or "")[:10], "apresentada": (p.get("dataApresentacao") or "")[:10],
                            "norma": p.get("normaGerada") or None,
                            "url": f"https://www25.senado.leg.br/web/atividade/materias/-/materia/{p['codigoMateria']}" if p.get("codigoMateria") else p.get("urlDocumento")})
        rl = {r["idProcesso"]: r for r in rels if r.get("idProcesso")}
        col = collections.Counter(r.get("siglaColegiado") or "?" for r in rl.values())
        out[f"br-p-sf-{cod}"] = {"house": "senado", "window": "ano", "apresentadas": len(procs), "como_primeiro_autor": primeiro,
                                "projetos": cls["projetos"], "requerimentos": cls["requerimentos"], "emendas": 0, "outros": len(procs) - cls["projetos"] - cls["requerimentos"], "pareceres_como_relator": None,
                                "por_tipo": dict(sorted(por_tipo.items(), key=lambda kv: (-kv[1], kv[0]))), "temas": [],
                                "ultimas": ultimas, "relatorias": len(rl), "relatorias_projetos": sum(1 for r in rl.values() if classe(sf_sigla(r.get("identificacaoProcesso"))) == "projetos"),
                                "relatorias_por_colegiado": dict(col.most_common(4)), "virou_norma": len(norma)}
        if (i + 1) % 10 == 0: print(f"senado: {i + 1}/{len(sen_ids)}", file=sys.stderr)
    ok = [v for v in out.values() if "erro" not in v]
    resumo = {"pessoas": len(sen_ids), "erros": erros, "com_proposicao": sum(1 for v in ok if v["apresentadas"]), "proposicoes_distintas": len(todas), "virou_norma": len(ids_norma),
              "mediana_apresentadas": mediana([v["apresentadas"] for v in ok]), "mediana_projetos": mediana([v["projetos"] for v in ok]),
              "mediana_requerimentos": mediana([v["requerimentos"] for v in ok]), "mediana_relatorias": mediana([v["relatorias"] for v in ok]),
              "fonte": "legis.senado.leg.br/dadosabertos/processo (por autor) e /processo/relatoria (por relator)",
              "relatorias_fonte": "relatorias designadas no ano legislativo (inclui requerimentos relatados na Comissão Diretora)"}
    return out, resumo

# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--amostra", help="N[,M]: só N deputados e M senadores (padrão M=N)"); ap.add_argument("--out", help="arquivo de saída (padrão data/generated/proposicoes.yaml)")
    a = ap.parse_args(); t0 = time.time()
    people = json.load(open(ROOT / "build" / "graph.br.json", encoding="utf-8"))["people"]
    dep = [(k[len("br-p-cd-"):], v.get("name") or "") for k, v in people.items() if k.startswith("br-p-cd-")]
    sen = [(k[len("br-p-sf-"):], v.get("name") or "") for k, v in people.items() if k.startswith("br-p-sf-")]
    if a.amostra:
        n, _, m = a.amostra.partition(","); n = int(n); m = int(m) if m else n; dep, sen = dep[:n], sen[:m]
    cd, rcd = camara([d for d, _ in dep], {norm(n): d for d, n in dep if n})
    sf, rsf = senado([s for s, _ in sen], {s: n for s, n in sen})
    dur = round(time.time() - t0)
    out = {"generated_at": TODAY.isoformat(), "since": SINCE.isoformat(), "duracao_s": dur, "resumo": {"camara": rcd, "senado": rsf}, "people": {**cd, **sf}}
    dest = pathlib.Path(a.out) if a.out else ROOT / "data" / "generated" / "proposicoes.yaml"; dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("# GERADO por etl/proposicoes.py. Não edite à mão.\n" + yaml.dump(out, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    print(f"câmara: {rcd['pessoas']} deputados, {rcd['proposicoes_distintas']} proposições distintas desde {SINCE}, mediana {rcd['mediana_apresentadas']}/pessoa, {rcd['virou_norma']} viraram norma; "
          f"senado: {rsf['pessoas']} senadores ({rsf['erros']} erros), {rsf['proposicoes_distintas']} processos, mediana {rsf['mediana_apresentadas']}/pessoa, {rsf['virou_norma']} viraram norma; {dur}s → {dest}")
    for k, v in sorted(((k, v) for k, v in out["people"].items() if "erro" not in v), key=lambda kv: -kv[1]["projetos"])[:3]:
        print(f"  mais projetos: {k} {people[k]['name']}: {v['projetos']} projetos, {v['apresentadas']} apresentadas, {v['relatorias']} relatorias")
if __name__ == "__main__": main()
