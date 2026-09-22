#!/usr/bin/env python3
"""Data de posse dos ocupantes atuais → data/generated/posses.yaml

Problema: 331 dos 478 ocupantes de cargos de nomeação do grafo não têm `started_at`, porque a página oficial do
órgão publica o nome mas não a data. A data existe sempre no Diário Oficial: o ato que nomeou ou designou a pessoa.

Estratégia (barata): em vez de varrer o DOU inteiro (ver etl/dou.py --backfill: ~350 páginas de listagem POR MÊS),
busca-se o NOME de cada ocupante entre aspas na busca pública do in.gov.br, em TODAS as seções (o ato de nomeação
de ministro sai em edição extra, DO2ESP, que a busca com s=do2 não devolve), de 1º/1/2023 até hoje. São ~1 a 6
consultas por pessoa. Para cada resultado cujo trecho cite NOMEAR/DESIGNAR/EXONERAR/DISPENSAR baixa-se o texto
integral e extrai-se, ancorado no nome, o verbo que o governa e o cargo que vem logo depois
("NOMEAR FULANO DE TAL, para exercer o cargo de Secretário Nacional de X do Ministério Y, código CCE 1.17").

Casamento: o cargo extraído é comparado, por tokens (sem acento, minúsculas, radical simples), com o nome do cargo
no grafo e com o nome/siglas do órgão. Confiança alta = nome exato + cargo casado; média = nome exato, papel igual
(secretário com secretário) e apenas o órgão casado. Se houver EXONERAR/DISPENSAR posterior para a mesma pessoa e
cargo, o ato não é usado: vira `conflitos` (a pessoa não deveria estar no cargo, ou o grafo está desatualizado).
Sem ato, a pessoa entra em `nao_encontrados` — nada é inventado.

O QUE A DATA SIGNIFICA: `data` é o dia em que o ato foi PUBLICADO no DOU. Para cargos do Executivo isso coincide
com o início do exercício. Para tribunais e Banco Central a posse é dias depois: conferindo 22 ocupantes que já
tinham `started_at` no grafo, 2 bateram na hora, 4 diferiram de 1 a 12 dias (Teodoro Silva Santos: ato publicado
em 10/11/2023, posse no STJ em 22/11/2023) e 16 não foram achados — quase todos com posse anterior a 2023, fora
da janela. Ou seja: a data é a do ato de nomeação, não a do juramento.

Uso: .venv/bin/python etl/posses.py                       (todos os ocupantes sem data)
     .venv/bin/python etl/posses.py --todos                (inclui quem já tem data, para conferência)
     .venv/bin/python etl/posses.py --limite 20            (amostra)
     .venv/bin/python etl/posses.py --so-cache             (não vai à rede; usa só build/cache-posses/)
Cache: build/cache-posses/busca/<nome>.json (resultados) e build/cache-posses/textos/<ato>.txt (texto do ato);
apagar o cache força nova consulta. A gravação é parcial: posses.yaml é reescrito a cada 10 pessoas.
"""
import json, re, sys, html, time, pathlib, datetime, argparse, unicodedata, urllib.request, urllib.error, urllib.parse
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "generated" / "posses.yaml"
CACHE = ROOT / "build" / "cache-posses"
CACHE_DOU = ROOT / "build" / "cache-dou" / "textos"      # textos já baixados pelo etl/dou.py --backfill
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
      "Accept": "text/html,*/*;q=0.8", "Accept-Language": "pt-BR,pt;q=0.9"}
PAUSE = {"s": 0.6}
BLOCKED = {"n": 0}
VERBOS = {"nomear": "nomeacao", "designar": "designacao", "exonerar": "exoneracao", "dispensar": "dispensa"}
VERB_RX = re.compile(r"\b(nomear|designar|exonerar|dispensar)\b")
STOP = {"de", "da", "do", "das", "dos", "e", "em", "a", "o", "as", "os", "no", "na", "nos", "nas", "para", "com", "ao", "the"}
ACENTOS = str.maketrans("áàâãäéèêëíìîïóòôõöúùûüçñÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇÑºª",
                        "aaaaaeeeeiiiiooooouuuucnAAAAAEEEEIIIIOOOOOUUUUCNoa")

def fold(s):
    """Minúsculas sem acento MANTENDO pontuação e comprimento (índices servem no texto original)."""
    return (s or "").translate(ACENTOS).lower()

def toks(s):
    """Tokens significativos com radical grosseiro (gênero/plural), aplicado igual dos dois lados da comparação."""
    out = []
    for t in re.split(r"[^a-z0-9]+", fold(s)):
        if not t or t in STOP or len(t) < 2: continue
        out.append(re.sub(r"(coes|oes|as|os|es|a|o|s)$", "", t) if len(t) > 4 else t)
    return out

PAPEIS = ["diretor president", "diretor ger", "vice president", "secretari execut", "secretari nacion", "secretari especi",
          "procurador", "defensor", "advogad", "comandant", "superintendent", "corregedor", "ouvidor", "controlador",
          "ministr", "president", "diretor", "secretari", "subsecretari", "chefe", "conselheir", "coordenador", "reitor",
          "governador", "prefeit", "membr", "assessor", "gerent", "auditor", "delegad", "inspetor", "curador"]
def papel(s):
    """Papel que ENCABEÇA o cargo. Tem de casar no começo: "membro titular da Secretaria de Política Econômica"
    é um assento de conselho, não a Secretaria — se "secretari" valesse em qualquer posição, viraria o cargo."""
    f = " ".join(toks(s)[:3])
    for p in PAPEIS:
        if re.match(p, f): return p
    return None

def get(url):
    time.sleep(max(0.5, PAUSE["s"]))
    for i in range(4):
        try:
            h = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90).read().decode("utf-8", "ignore")
            if h: BLOCKED["n"] = 0; return h
            espera = 5 * (i + 1)
        except urllib.error.HTTPError as e:
            espera = min(180, 15 * (2 ** i)) if (e.code == 429 or e.code >= 500) else 5 * (i + 1)
            print(f"    HTTP {e.code}; aguardando {espera}s", file=sys.stderr, flush=True)
        except Exception:
            espera = 5 * (i + 1)
        time.sleep(espera)
    BLOCKED["n"] += 1
    if BLOCKED["n"] >= 5: sys.exit("in.gov.br sem resposta em 5 consultas seguidas: provável bloqueio; retome depois (o cache é reaproveitado)")
    return ""

def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", fold(s)).strip("-")[:110]

def _pagina(nome, de, ate, cursor):
    """Uma página de resultados: (lista, total_de_paginas)."""
    base = {"q": '"%s"' % nome, "s": "", "exactDate": "personalizado", "publishFrom": de.strftime("%d/%m/%Y"),
            "publishTo": ate.strftime("%d/%m/%Y"), "sortType": "0", "delta": "20"}
    h = get("https://www.in.gov.br/consulta/-/buscar/dou?" + urllib.parse.urlencode(dict(base, **cursor)))
    m = re.search(r'<script[^>]*id="_br_com_seatecnologia_in_buscadou_BuscaDouPortlet_params"[^>]*>(.*?)</script>', h, re.S)
    try: pag = json.loads(m.group(1)).get("jsonArray", []) if m else []
    except Exception: pag = []
    tp = re.search(r"totalPages\s*:\s*(\d+)", h)
    return pag, (int(tp.group(1)) if tp else 1)

def _buscar_rec(nome, de, ate, max_pages, prof=0):
    """Busca na janela; se houver mais páginas que o limite (nome muito citado), divide a janela ao meio.

    A busca devolve os resultados do mais recente para o mais antigo: sem a divisão, o ato de nomeação de 2023 de um
    ministro que assina centenas de portarias ficaria fora do alcance de --max-pages.
    """
    pag, total = _pagina(nome, de, ate, {})
    if total > max_pages and (ate - de).days > 40 and prof < 1:   # no máximo 2 sub-janelas por ano
        meio = de + (ate - de) / 2
        return _buscar_rec(nome, de, meio, max_pages, prof + 1) + _buscar_rec(nome, meio + datetime.timedelta(days=1), ate, max_pages, prof + 1)
    vistos, hits, pagina = set(), [], 1
    while True:
        novos = [x for x in pag if x.get("urlTitle") not in vistos]
        if not novos: break
        for x in novos: vistos.add(x["urlTitle"]); hits.append(x)
        if pagina >= min(total, max_pages): break
        u = pag[-1]
        pag, total = _pagina(nome, de, ate, {"currentPage": pagina, "newPage": pagina + 1, "score": u.get("score", 0),
                                             "id": u.get("classPK"), "displayDate": u.get("displayDateSortable")})
        pagina += 1
    return hits

def buscar_frase(nome, q, chave, desde, ate, so_cache=False, max_pages=3):
    """Uma consulta de FRASE exata (a busca do in.gov.br trata q inteiro como frase), cacheada em <nome>--<chave>.json."""
    f = CACHE / "busca" / f"{slug(nome)}--{chave}.json"
    if f.exists():
        try: return json.load(open(f, encoding="utf-8"))
        except Exception: pass
    if so_cache: return []
    hits, vistos, pagina, cursor = [], set(), 1, {}
    while pagina <= max_pages:
        pag, total = _pagina(q, desde, ate, cursor)
        novos = [x for x in pag if x.get("urlTitle") not in vistos]
        if not novos: break
        for x in novos: vistos.add(x["urlTitle"]); hits.append(x)
        if pagina >= total: break
        u = pag[-1]; cursor = {"currentPage": pagina, "newPage": pagina + 1, "score": u.get("score", 0),
                               "id": u.get("classPK"), "displayDate": u.get("displayDateSortable")}
        pagina += 1
    f.parent.mkdir(parents=True, exist_ok=True)
    json.dump(hits, open(f, "w", encoding="utf-8"), ensure_ascii=False)
    return hits

def buscar_verbo(nome, verbo, desde, ate, so_cache=False, max_pages=3, tag=""):
    """Atalho principal: "NOMEAR FULANO DE TAL" devolve exatamente os atos que nomeiam a pessoa — uma consulta
    cobre todo o período. A busca só pelo nome (centenas de páginas para quem assina portarias) fica de reserva."""
    return buscar_frase(nome, f"{verbo} {nome}", f"{verbo}{tag}", desde, ate, so_cache, max_pages)

def buscar_cargo(nome, desde, ate, so_cache=False, tag=""):
    """Reserva barata: "FULANO DE TAL para exercer o cargo" pega o ato quando o verbo não vem colado ao nome
    ("NOMEAR, a pedido, FULANO", "Nomear FULANO, matrícula ..., para exercer o cargo de ...")."""
    return buscar_frase(nome, f"{nome} para exercer o cargo", f"cargo{tag}", desde, ate, so_cache, 2)

def buscar(nome, desde, ate, max_pages, so_cache=False):
    """Resultados da busca pela frase exata do nome, em todas as seções. Cache por pessoa e ano."""
    hits = {}
    for ano in range(desde.year, ate.year + 1):
        de, a2 = max(desde, datetime.date(ano, 1, 1)), min(ate, datetime.date(ano, 12, 31))
        f = CACHE / "busca" / f"{slug(nome)}-{ano}.json"
        if f.exists():
            try: lst = json.load(open(f, encoding="utf-8"))
            except Exception: lst = []
        elif so_cache: lst = []
        else:
            lst = _buscar_rec(nome, de, a2, max_pages)
            f.parent.mkdir(parents=True, exist_ok=True)
            json.dump(lst, open(f, "w", encoding="utf-8"), ensure_ascii=False)
        for x in lst: hits[x.get("urlTitle")] = x
    return list(hits.values())

def texto_ato(url_title, so_cache=False):
    f = CACHE / "textos" / (url_title[:150] + ".txt")
    if f.exists(): return f.read_text(encoding="utf-8")
    g = CACHE_DOU / (url_title[:150] + ".txt")
    if g.exists(): return g.read_text(encoding="utf-8")
    if so_cache: return ""
    h = get("https://www.in.gov.br/web/dou/-/" + url_title)
    m = re.search(r'<div[^>]*class="texto-dou"[^>]*>(.*?)<div class="rodape', h, re.S) or re.search(r'<p class="identifica">(.*?)<p class="assina">', h, re.S)
    t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", m.group(1) if m else h))).strip()
    if t: f.parent.mkdir(parents=True, exist_ok=True); f.write_text(t, encoding="utf-8")
    return t

# O nome do cargo tem vírgulas ("Ministra de Estado da Ciência, Tecnologia e Inovação"), então não se corta na
# primeira vírgula: corta-se no fim da frase ou nas cláusulas que costumam seguir o cargo no DOU.
FIM = (r"(?=[.;]|, ?codigo|, ?cce|, ?das-|, ?fcpe|, ?ficando|, ?a partir|, ?em substitui|, ?na vaga|, ?em vaga|"
       r", ?na forma|, ?nos termos|, ?pelo prazo|, ?com mandato|, ?sem prejuizo|, ?do quadro|, ?no [0-9]|"
       r", ?para (?:o|um) (?:per|mandato)|, ?e ?$|$)")
CARGO_PAT = [r"para exercer,? (?:interinamente,? )?o cargo (?:em comiss[ãa]o )?de\s+(.{3,200}?)" + FIM,
             r"para exercer,? (?:interinamente,? )?a fun[çc][ãa]o (?:comissionada )?de\s+(.{3,200}?)" + FIM,
             r"para (?:o|ocupar o) cargo (?:em comiss[ãa]o )?de\s+(.{3,200}?)" + FIM,
             r"d[oa] cargo (?:em comiss[ãa]o )?de\s+(.{3,200}?)" + FIM,
             r"no cargo (?:em comiss[ãa]o )?de\s+(.{3,200}?)" + FIM,
             r"(?:para a|d[ae]) fun[çc][ãa]o de\s+(.{3,200}?)" + FIM,
             r"(?:para|como)\s+((?:membro|conselheir[oa]|diretor[a]?|president[ea]|secretari[oa])\b.{0,160}?)" + FIM,
             r"como\s+(.{3,160}?)(?=[.;]|, ?a partir|, ?ficando|$)"]
NOME_ANTES = re.compile(r"cargo (?:em comiss[ãa]o )?de\s+([^;\.]{3,200})[,;] ?$")

def extrair(texto, nome):
    """Ancorado no nome: devolve [(verbo, cargo, trecho, entre)] para cada ocorrência da pessoa no ato."""
    t = re.sub(r"\s+", " ", texto or ""); ft = fold(t); fn = fold(nome)
    saida = []
    for m in re.finditer(r"(?<![a-z])" + re.escape(fn) + r"(?![a-z])", ft):
        antes = ft[max(0, m.start() - 700):m.start()]
        vs = list(VERB_RX.finditer(antes))
        if not vs: continue
        verbo = vs[-1].group(1)
        cauda_f, cauda_o = ft[m.end():m.end() + 400], t[m.end():m.end() + 400]
        cargo, entre = None, cauda_o[:120]
        for p in CARGO_PAT:
            c = re.search(p, cauda_f)
            if c: cargo, entre = cauda_o[c.start(1):c.end(1)].strip(" ,;."), cauda_o[:c.start(1)]; break
        if not cargo:                                   # "...o cargo de X, para o qual fica nomeado FULANO"
            c = NOME_ANTES.search(antes)
            if c: cargo, entre = t[max(0, m.start() - 700):m.start()][c.start(1):c.end(1)].strip(" ,;."), ""
        # `entre` é o que separa o nome do cargo ("..., do encargo de substituto eventual do cargo de X"):
        # é ali que aparece a marca de substituição, e só ali — o resto do ato é de outras pessoas.
        saida.append((verbo, cargo, t[max(0, m.start() - 150):m.end() + 220], entre))
    return saida

def alvos(graph, todos=False):
    """Ocupantes atuais de cargos de nomeação (nós dept_head), sem data de posse (ou todos)."""
    nodes = graph["nodes"]; out = []
    for n in nodes.values():
        if n.get("type") != "dept_head": continue
        org = nodes.get(n.get("head_of") or "", {})
        for p in n.get("people") or []:
            if p.get("entry_mode") == "eleito": continue
            if p.get("started_at") and not todos: continue
            out.append({"cargo_id": n["id"], "cargo_nome": n["name"], "org_nome": org.get("name") or "",
                        "org_aliases": org.get("aliases") or [], "pessoa_id": p["id"], "pessoa_nome": p["name"],
                        "tinha_data": bool(p.get("started_at")), "seats": len(n.get("people") or [])})
    return out

# Trechos que denunciam que o ato NÃO é sobre o cargo em si: substituição eventual, assento em colegiado.
RUIDO = re.compile(r"substitut|eventual|encargo de|suplente")
RUIDO_COLEGIADO = re.compile(r"\bmembr|conselho nacional|conselho de|comit[eê]|comiss[ãa]o|grupo de trabalho|representante|c[âa]mara t[ée]cnica")

def casar(cargo_txt, hierarquia, alvo, ctx=""):
    """(confianca, criterio, cobertura) do cargo do ato contra o cargo/órgão do grafo, ou (None, motivo, cob)."""
    if not cargo_txt: cargo_txt = ""
    f = fold(cargo_txt + " " + (ctx or ""))
    if RUIDO.search(f): return None, "ato de substituição/suplência, não de posse no cargo", 0.0
    if RUIDO_COLEGIADO.search(fold(cargo_txt)) and (papel(alvo["cargo_nome"]) or "") not in ("membr", "conselheir"):
        return None, "assento em colegiado, não o cargo do grafo", 0.0
    tc = set(toks(cargo_txt)); hier = " ".join(hierarquia or [])
    th = set(toks(hier))
    alvo_cargo = [x for x in toks(alvo["cargo_nome"])]
    alvo_org = [x for x in toks(alvo["org_nome"])]
    siglas = [fold(s) for s in alvo["org_aliases"] if 2 <= len(s) <= 8]
    cob = len(set(alvo_cargo) & tc) / max(1, len(set(alvo_cargo)))
    pc, pa = papel(cargo_txt), papel(alvo["cargo_nome"])
    sigla_ok = any(re.search(r"\b" + re.escape(s) + r"\b", fold(cargo_txt) + " " + fold(hier)) for s in siglas)
    org_cob = len(set(alvo_org) & (tc | th)) / max(1, len(set(alvo_org)))
    if cob >= 0.7 and (pc == pa or not pa): return "alta", f"cargo do ato casa {cob:.0%} dos termos do cargo no grafo", cob
    if cob >= 0.5 and pc == pa and (org_cob >= 0.5 or sigla_ok): return "alta", f"papel igual, cargo {cob:.0%} e órgão casados", cob
    if pc == pa and pa and (org_cob >= 0.6 or sigla_ok): return "media", "papel igual e órgão casado; cargo inferido pelo órgão", cob
    return None, f"cargo {cob:.0%}, órgão {org_cob:.0%}, papel {pc} vs {pa}", cob

def colher(h, nome, so_cache=False):
    """Atos de UM resultado da busca que governam ESTE nome (baixa o texto integral; usa cache)."""
    trecho = re.sub(r"<[^>]+>", " ", html.unescape(h.get("content") or "")) + " " + (h.get("title") or "")
    d = iso(h.get("pubDate"))
    if not d or not VERB_RX.search(fold(trecho)): return []
    txt = texto_ato(h["urlTitle"], so_cache)
    if not txt: return []
    return [{"data": d, "verbo": verbo, "cargo": cargo, "hier": h.get("hierarchyList") or [],
             "secao": h.get("pubName"), "url": "https://www.in.gov.br/web/dou/-/" + h["urlTitle"],
             "titulo": h.get("title"), "ctx": ctx, "entre": entre} for verbo, cargo, ctx, entre in extrair(txt, nome)]

def escolher(hits, alvo, so_cache=False, limite=40):
    """Do mais recente para o mais antigo, o primeiro ato de entrada cujo cargo case com o do grafo.

    O texto integral só é baixado até achar o ato certo — em geral o primeiro resultado resolve.
    """
    vistos, baixados = 0, 0
    recentes = lambda hs: sorted(hs, key=lambda x: iso(x.get("pubDate")) or "", reverse=True)
    # nomeações antes de designações: a nomeação é o ato de posse; designação costuma ser de colegiado
    for h in recentes([x for x in hits if x.get("_q") == "nomear"]) + recentes([x for x in hits if x.get("_q") != "nomear"]):
        baixados += 1
        if baixados > limite: break        # teto de atos baixados por pessoa (nomes muito citados no DOU)
        for x in colher(h, alvo["pessoa_nome"], so_cache):
            vistos += 1
            if x["verbo"] not in ("nomear", "designar"): continue
            c, cr, _ = casar(x["cargo"], x["hier"], alvo, x["entre"])
            if c: return x, c, cr, vistos
    return None, None, None, vistos

def saida_posterior(hits, alvo, desde_data, so_cache=False):
    """Exoneração/dispensa do mesmo cargo publicada depois da nomeação escolhida (conflito)."""
    for h in sorted(hits, key=lambda x: iso(x.get("pubDate")) or "", reverse=True):
        if (iso(h.get("pubDate")) or "") <= desde_data: continue
        for x in colher(h, alvo["pessoa_nome"], so_cache):
            if x["verbo"] in ("exonerar", "dispensar") and casar(x["cargo"], x["hier"], alvo, x["entre"])[0]: return x
    return None

def iso(pubdate):
    return f"{pubdate[6:10]}-{pubdate[3:5]}-{pubdate[0:2]}" if re.match(r"\d\d/\d\d/\d{4}", pubdate or "") else None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", default="2023-01-01"); ap.add_argument("--ate", default=None)
    ap.add_argument("--limite", type=int, default=0); ap.add_argument("--todos", action="store_true")
    ap.add_argument("--max-pages", type=int, default=8); ap.add_argument("--pause", type=float, default=0.6)
    ap.add_argument("--max-atos", type=int, default=40, help="teto de atos baixados por pessoa")
    ap.add_argument("--so-cache", action="store_true"); ap.add_argument("--so-nomes", default=None)
    ap.add_argument("--sem-reserva", action="store_true", help="não faz a busca só pelo nome quando a frase VERBO+NOME não acha nada")
    ap.add_argument("--desde-antigo", default=None, help="se nada for achado na janela, procura também a partir desta data (ex.: 2019-01-01, mandatos de agência)")
    a = ap.parse_args()
    PAUSE["s"] = a.pause
    desde = datetime.date.fromisoformat(a.desde); ate = datetime.date.fromisoformat(a.ate) if a.ate else datetime.date.today()
    antigo = datetime.date.fromisoformat(a.desde_antigo) if a.desde_antigo else None
    graph = json.load(open(ROOT / "build" / "graph.br.json", encoding="utf-8"))
    lista = alvos(graph, a.todos)
    sem_data_antes = len(alvos(graph))
    if a.so_nomes:
        alvo_nomes = {fold(x.strip()) for x in a.so_nomes.split(",")}
        lista = [x for x in lista if fold(x["pessoa_nome"]) in alvo_nomes]
    if a.limite: lista = lista[:a.limite]
    print(f"{len(lista)} ocupantes a resolver (janela {desde} a {ate})", file=sys.stderr, flush=True)

    posses, conflitos, nao_encontrados = {}, [], []
    t0 = time.time()
    for i, alvo in enumerate(lista, 1):
        nome = alvo["pessoa_nome"]
        entrada, saida = {}, {}
        for v in VERBOS:                       # caminho barato: uma consulta por verbo, frase "VERBO NOME"
            alvo_dict = entrada if v in ("nomear", "designar") else saida
            for h in buscar_verbo(nome, v, desde, ate, a.so_cache): h["_q"] = v; alvo_dict.setdefault(h.get("urlTitle"), h)
        if len(entrada) < 40:
            for h in buscar_cargo(nome, desde, ate, a.so_cache): h["_q"] = "nomear"; entrada.setdefault(h.get("urlTitle"), h)
        escolhido, conf, crit, vistos = escolher(entrada.values(), alvo, a.so_cache, a.max_atos)
        if not escolhido and not a.sem_reserva:  # reserva: busca só pelo nome, ano a ano (pega "NOMEAR, a pedido, F.")
            for h in buscar(nome, desde, ate, a.max_pages, a.so_cache):
                if h.get("urlTitle") not in entrada: entrada[h["urlTitle"]] = h
            escolhido, conf, crit, vistos = escolher(entrada.values(), alvo, a.so_cache, a.max_atos)
            saida.update(entrada)
        if not escolhido and antigo:
            # dirigentes de agência têm mandato de 4-5 anos: muitos foram nomeados antes de 2023
            for v in ("nomear", "designar"):
                for h in buscar_verbo(nome, v, antigo, desde - datetime.timedelta(days=1), a.so_cache, tag=f"-{antigo.year}"):
                    h["_q"] = v; entrada.setdefault(h.get("urlTitle"), h)
            for h in buscar_cargo(nome, antigo, desde - datetime.timedelta(days=1), a.so_cache, tag=f"-{antigo.year}"):
                h["_q"] = "nomear"; entrada.setdefault(h.get("urlTitle"), h)
            escolhido, conf, crit, vistos = escolher(entrada.values(), alvo, a.so_cache, a.max_atos)
            saida.update(entrada)
        n_hits = len(entrada) + len(saida)
        if not escolhido:
            nao_encontrados.append({"pessoa": alvo["pessoa_nome"], "cargo_id": alvo["cargo_id"],
                                    "atos_vistos": vistos, "resultados": n_hits})
        else:
            fim = saida_posterior(saida.values(), alvo, escolhido["data"], a.so_cache)
            if fim:
                conflitos.append({"pessoa": alvo["pessoa_nome"], "cargo_id": alvo["cargo_id"], "posse": escolhido["data"],
                                  "saida": fim["data"], "saida_verbo": VERBOS[fim["verbo"]],
                                  "saida_url": fim["url"], "nota": "ato de saída posterior à nomeação: data não usada"})
            else:
                chave = alvo["cargo_id"] if alvo["seats"] <= 1 else f"{alvo['cargo_id']}#{alvo['pessoa_id']}"
                posses[chave] = {"cargo_id": alvo["cargo_id"], "pessoa_nome": alvo["pessoa_nome"], "pessoa_id": alvo["pessoa_id"],
                                 "data": escolhido["data"], "tipo": VERBOS[escolhido["verbo"]], "dou_url": escolhido["url"],
                                 "secao": escolhido["secao"], "ato": escolhido["titulo"], "cargo_no_ato": escolhido["cargo"],
                                 "confianca": conf, "criterio": crit}
        if i % 10 == 0 or i == len(lista):
            print(f"  {i}/{len(lista)} — {len(posses)} posses, {len(conflitos)} conflitos, {len(nao_encontrados)} sem ato "
                  f"({(time.time()-t0)/i:.1f}s/pessoa)", file=sys.stderr, flush=True)
            gravar(posses, conflitos, nao_encontrados, desde, ate, sem_data_antes, antigo)
    gravar(posses, conflitos, nao_encontrados, desde, ate, sem_data_antes, antigo)
    print(f"posses={len(posses)} conflitos={len(conflitos)} sem ato={len(nao_encontrados)} → {OUT}")

def gravar(posses, conflitos, nao_encontrados, desde, ate, sem_data_antes, antigo=None):
    por_conf = {"alta": sum(1 for p in posses.values() if p["confianca"] == "alta"),
                "media": sum(1 for p in posses.values() if p["confianca"] == "media")}
    doc = {"generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
           "fonte": "Diário Oficial da União — busca pública www.in.gov.br/consulta (todas as seções)",
           "nota": ("data = dia da publicação do ato de nomeação/designação no DOU. No Executivo equivale ao início do "
                    "exercício; em tribunais e no Banco Central a posse costuma ser de 1 a 12 dias depois."),
           "janela": dict({"de": desde.isoformat(), "ate": ate.isoformat()},
                          **({"de_na_segunda_tentativa": antigo.isoformat()} if antigo else {})),
           "posses": dict(sorted(posses.items())),
           "conflitos": conflitos,
           "nao_encontrados": [x["pessoa"] for x in nao_encontrados],
           "nao_encontrados_detalhe": nao_encontrados,
           "resumo": {"ocupantes_sem_data_antes": sem_data_antes, "resolvidos": len(posses),
                      "por_confianca": por_conf, "conflitos": len(conflitos), "sem_ato": len(nao_encontrados)}}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    yaml.safe_dump(doc, open(OUT, "w", encoding="utf-8"), allow_unicode=True, sort_keys=False, width=200)

if __name__ == "__main__": main()
