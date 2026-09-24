#!/usr/bin/env python3
"""Dirigentes dos órgãos sem chefia no grafo → data/generated/dirigentes.yaml

Problema: 221 nós `type: department` do build/graph.br.json não têm nenhum `dept_head` apontando para eles
("caixas vazias"). Este ETL cria o cargo de chefia de três blocos:

  tribunais  — 6 TRFs, 24 TRTs, TJDFT e os TREs presentes no grafo. Presidente eleito pelos próprios membros
               (CF art. 96, I, "a"; LC 35/1979 art. 102), mandato de dois anos.
  estatais   — empresas públicas, sociedades de economia mista, autarquias e fundações sem cargo de chefia.
               Presidente/Diretor-Presidente/Superintendente conforme a lei de criação e a Lei 13.303/2016.
  ensino     — as 113 instituições `subtype: instituicao_de_ensino` (reitor de universidade federal pela
               Lei 5.540/1968 art. 16 c/c Lei 9.192/1995; reitor de instituto federal pela Lei 11.892/2008
               art. 12; reitor do Colégio Pedro II pela Lei 12.677/2012; diretor-geral de CEFET pelo
               Decreto 5.224/2004 art. 9º).

Ficam de fora, por não haver presidência definida em lei: as 17 seções judiciárias / varas federais de
primeiro grau (dirigidas por juiz federal diretor do foro, Lei 5.010/1966 art. 12) e os nós guarda-chuva
"Tribunais Regionais do Trabalho" e "Tribunais Regionais Eleitorais", que não são um tribunal único.

Ocupantes: só com fonte oficial verificável. Para cada órgão o script varre o site oficial (home + links de
"Presidência"/"Reitoria"/"Composição"/"Quem é quem"/"Diretoria" + caminhos prováveis), extrai o nome que
aparece junto ao cargo e grava source_url + a linha da página em `note`. Sem casamento, o cargo fica sem
`people` — nunca se inventa nome.

Uso:
  .venv/bin/python etl/dirigentes.py --amostra 5    # 5 órgãos por bloco
  .venv/bin/python etl/dirigentes.py                # completo (~200 páginas, use nohup)
  .venv/bin/python etl/dirigentes.py --no-web       # só os cargos, sem ocupantes
  .venv/bin/python etl/dirigentes.py --refresh      # ignora build/cache-dirigentes/
  .venv/bin/python etl/dirigentes.py --bloco ensino # um bloco só
"""
import sys, os, re, json, time, html, ssl, pathlib, hashlib, argparse, datetime, unicodedata
import urllib.request, urllib.error, urllib.parse
from collections import OrderedDict
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
GRAPH = ROOT / "build" / "graph.br.json"
CACHE = ROOT / "build" / "cache-dirigentes"
OUT = ROOT / "data" / "generated" / "dirigentes.yaml"
TODAY = datetime.date.today().isoformat()
THROTTLE = 0.4
TIMEOUT = 15
MAX_PAGES = 10         # orçamento de páginas por órgão (inclui a home)
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36",
      "Accept-Language": "pt-BR,pt;q=0.9", "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"}

PLANALTO = "https://www.planalto.gov.br/ccivil_03"
CF = "https://www.planalto.gov.br/ccivil_03/constituicao/constituicao.htm"

# ------------------------------------------------------------------ texto
PARTICLES = {"da", "de", "do", "das", "dos", "e", "del", "della", "di", "du", "la", "le", "van", "von", "y", "dalla"}

def strip_acc(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()

def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", strip_acc(s).lower()).strip("-")

def norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", strip_acc(s).lower())).strip()

def titlecase(s):
    out = []
    for i, tok in enumerate(s.split()):
        parts = tok.split("-")
        parts = [p.lower() if (p.lower() in PARTICLES and i) else (p[:1].upper() + p[1:].lower()) for p in parts]
        out.append("-".join(parts))
    return " ".join(out)

def clip(t, n=430):
    t = re.sub(r"\s+", " ", t or "").strip()
    if len(t) <= n:
        return t
    cut = t[:n]
    i = max(cut.rfind(". "), cut.rfind("; "))
    return (cut[:i + 1] if i > 140 else cut).rstrip(" ;,-") + ("" if cut.rstrip().endswith(".") else "…")

# ------------------------------------------------------------------ HTTP com cache
_stats = {"fetch": 0, "hit": 0, "erro": 0}

def fetch(url, refresh=False):
    """(html, final_url) ou (None, motivo). Cache por URL em build/cache-dirigentes/."""
    CACHE.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(url.encode()).hexdigest()[:16]
    f = CACHE / f"{slug(re.sub(r'^https?://', '', url))[:70]}-{key}.json"
    if f.exists() and not refresh:
        d = json.load(open(f, encoding="utf-8"))
        _stats["hit"] += 1
        return d.get("html"), d.get("final") or d.get("error")
    d = None
    for ctx in (None, ssl._create_unverified_context()):
        try:
            req = urllib.request.Request(url, headers=UA)
            kw = {"timeout": TIMEOUT}
            if ctx is not None:
                kw["context"] = ctx
            with urllib.request.urlopen(req, **kw) as r:
                raw = r.read(3_500_000)
                enc = "utf-8"
                ct = (r.headers.get("Content-Type") or "").lower()
                if "iso-8859" in ct or "latin" in ct:
                    enc = "latin-1"
                body = raw.decode(enc, "ignore")
                if enc == "utf-8" and body.count("Ã") > 40 and body.count("ç") < 5:
                    body = raw.decode("latin-1", "ignore")
                d = {"html": body, "final": r.geturl()}
            break
        except urllib.error.HTTPError as e:
            d = {"html": None, "error": f"http {e.code}"}
            break
        except ssl.SSLError:
            d = {"html": None, "error": "ssl"}
            continue
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", "")
            if isinstance(reason, ssl.SSLError) or "CERTIFICATE" in str(reason).upper():
                d = {"html": None, "error": "ssl"}
                continue
            d = {"html": None, "error": f"rede ({str(reason)[:40]})"}
            break
        except Exception as e:
            d = {"html": None, "error": f"erro {type(e).__name__}"}
            break
    d = d or {"html": None, "error": "erro"}
    transitorio = (not d.get("html")) and re.match(r"rede|erro Timeout|ssl", str(d.get("error") or ""))
    if not transitorio:
        json.dump(d, open(f, "w", encoding="utf-8"), ensure_ascii=False)
    _stats["fetch"] += 1
    if not d.get("html"):
        _stats["erro"] += 1
    time.sleep(THROTTLE)
    return d.get("html"), d.get("final") or d.get("error")

# ------------------------------------------------------------------ HTML → linhas / links
BLOCK_RX = re.compile(r"(?i)</?(p|div|li|ul|ol|h[1-6]|tr|td|th|table|dl|dt|dd|section|article|header|footer|"
                      r"nav|br|hr|blockquote|figure|figcaption|main|span|strong|b|em|i|a)(\s[^>]*)?>")

def to_lines(h):
    body = re.sub(r"(?is)<(script|style|noscript|svg|head|select|form).*?</\1>", " ", h or "")
    body = BLOCK_RX.sub("\n", body)
    body = re.sub(r"<[^>]+>", " ", body)
    body = unicodedata.normalize("NFC", html.unescape(body))
    body = body.replace("\xa0", " ").replace("​", " ").replace("ㅤ", " ")
    body = re.sub(r"[‐-―−]", "-", body)
    out = []
    for l in body.split("\n"):
        l = re.sub(r"\s+", " ", l).strip(" \t|·•*")
        if l:
            out.append(l)
    return out

def page_links(h, base):
    out = []
    for m in re.finditer(r'(?is)<a\b[^>]*href=["\']([^"\'#][^"\']*)["\'][^>]*>(.*?)</a>', h or ""):
        href, txt = m.group(1), re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(2))).strip()
        if not txt or href.lower().startswith(("javascript:", "mailto:", "tel:")):
            continue
        try:
            full = urllib.parse.urljoin(base, href)
        except Exception:
            continue
        if not full.startswith("http"):
            continue
        if re.search(r"\.(pdf|jpe?g|png|gif|zip|docx?|xlsx?|pptx?|mp4|mp3)(\?|$)", full, re.I):
            continue
        out.append((full, txt))
    return out

# ------------------------------------------------------------------ reconhecimento de nome de pessoa
HONOR = (r"(?:Exm[oa]s?\.?|Excelent[íi]ssim[oa]|Des(?:\.|embargador(?:a)?)?|Ju[íi]z(?:a)?|Ministr[oa]|"
         r"Desembargador(?:a)?|Professor(?:a)?|Prof(?:\.|ª|a\.|\.ª)?|Dr(?:\.|ª|a\.|\.ª)?|Sr(?:\.|a\.)?|"
         r"Eng\.?|Adm\.?|Cel\.?|Gen\.?|Alte\.?|Almirante|General|Coronel|Brigadeiro|Vice-Almirante|"
         r"Contra-Almirante|Capit[ãa]o|Magn[íi]fic[oa]|Reverend[oa]|Sua Excel[êe]ncia)")
HONOR_RX = re.compile(r"(?i)^\s*(?:%s)\s+(?:Federal\s+|do\s+Trabalho\s+|Eleitoral\s+|Titular\s+|Dr\.?\s+|"
                      r"Dra\.?\s+|Doutor(?:a)?\s+)*" % HONOR)
TOKEN_RX = re.compile(r"^(?:[A-ZÁÀÂÃÉÊÍÓÔÕÚÜÇ][a-zàáâãéêíóôõúüçñ'’]{1,}|[A-ZÁÀÂÃÉÊÍÓÔÕÚÜÇ]{2,}|"
                      r"[A-ZÁÀÂÃÉÊÍÓÔÕÚÜÇ][a-zàáâãéêíóôõúüç]*[A-ZÁÀÂÃÉÊÍÓÔÕÚÜÇ][a-zàáâãéêíóôõúüç]*)$")
BAN = set("""tribunal tribunais regional regionais trabalho federal federais justica universidade universidades
instituto institutos fundacao presidencia presidente reitoria reitor diretoria diretor gabinete secretaria
conselho ministerio ministro campus campi portal acesso informacao noticias noticia servicos servico contato
transparencia ouvidoria corregedoria escola judiciario judiciaria cargo biografia curriculo gestao mandato
sessao sessoes plenario comissao coordenacao departamento centro nacional brasil brasileira brasileiro
empresa companhia banco caixa agencia superintendencia autoridade hospital colegio grupo leia saiba veja ver
todos todas aqui clique link home inicio inicial mapa site agenda eventos evento publicacoes processo
consulta pauta acervo edital editais concurso licitacao licitacoes lei leis decreto portaria resolucao
telefone endereco email fale conosco menu busca buscar pesquisa pesquisar voltar topo seguinte anterior
pagina paginas ano anos mes dia hora horas janeiro fevereiro marco abril maio junho julho agosto setembro
outubro novembro dezembro segunda terca quarta quinta sexta sabado domingo institucional sobre quem somos
historia missao visao valores estrutura organograma equipe membros membro composicao titular titulares
suplente eleito eleita posse eleicao eleicoes biênio bienio periodo gestora unidade unidades regiao regioes
estado estados distrito territorios municipio nucleo assessoria auditoria controladoria procuradoria
defensoria vice adjunto adjunta substituto substituta geral gerais executiva executivo administracao
administrativo financeiro recursos humanos tecnologia informacao comunicacao social imprensa cidadao
cidadania servidor servidores estudante estudantes docente docentes discente discentes graduacao
pos extensao pesquisa ensino cultura esporte saude educacao ciencia tecnologia inovacao
presidentes presidenta reitores reitora diretores diretora ministros galeria magistrado magistrados juiz
juizes juiza desembargador desembargadores desembargadora corregedor corregedores ouvidor procurador
conselheiro conselheiros gabinete fale conosco saiba leia acesse baixe download whatsapp facebook instagram
youtube twitter linkedin email telefone fax cep rua avenida bairro andar sala bloco edificio anexo
lista triplice previa parcial resultado apuracao votacao eleito eleita empossado empossada nomeacao exoneracao
para pela pelo sobre entre apos antes durante ainda tambem apenas somente contra desde onde quando quem qual
nota noticia artigo materia entrevista discurso palestra evento seminario congresso encontro reuniao visita""".split())
# linhas que nunca trazem o titular atual (o prefixo "vice/pró/sub/ex" colado ao cargo é tratado em VICE_PREFIX)
STOP_LINE = re.compile(r"(?i)\b(ex[- ]presidente|ex[- ]reitor|ex[- ]diretor|candidat|antig[oa]s?|anterior(es)?|"
                       r"substitut[oa]s?|galeria|mem[óo]ria|hist[óo]ric|in memoriam|falecid|"
                       r"presidentes?\s+d[ao]\s+(rep[úu]blica|conselho|comiss|associa|sindic|ordem|senado|"
                       r"c[âa]mara|stf|stj|tst|tse|cnj|oab))")

def person(raw):
    """Devolve o nome em caixa de título se `raw` parecer um nome de pessoa; senão None."""
    if not raw:
        return None
    s = re.sub(r"\s+", " ", raw).strip(" \t:;,.-–—|()[]•")
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"(?i)\b(em exerc[íi]cio|interin[oa]|pro tempore|substitut[oa]|respondendo)\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" \t:;,.-–—|")
    prev = None
    while prev != s:
        prev = s
        s = HONOR_RX.sub("", s).strip()
    s = s.strip(" \t:;,.-–—|")
    if not s or len(s) < 6 or len(s) > 72 or any(c.isdigit() for c in s):
        return None
    toks = s.split()
    if not (2 <= len(toks) <= 8):
        return None
    real = 0
    for t in toks:
        tl = strip_acc(t).lower().strip(".")
        if tl in PARTICLES:
            continue
        if not TOKEN_RX.match(t.strip(".")):
            return None
        if tl in BAN:
            return None
        if len(tl) < 2:
            return None
        real += 1
    if real < 2:
        return None
    tl = [strip_acc(t).lower().strip(".") for t in toks]
    if "e" in tl[1:-1] or tl[-1] in PARTICLES or tl[0] in PARTICLES or len(tl[0]) < 3:
        return None   # "Mônica X e Vallisney Y", "Jones Dari Goettert e da"
    if s.isupper() or s.islower():
        s = titlecase(s.lower())
    return s

# ------------------------------------------------------------------ casamento cargo × nome
CARGO_RX = {
    "presidente": re.compile(r"(?i)(?<![\w-])presiden(?:te|ta)(?![\w-])"),
    "diretor_presidente": re.compile(r"(?i)(?<![\w-])diretor(?:a)?[-\s]presiden(?:te|ta)(?![\w-])"),
    "reitor": re.compile(r"(?i)(?<![\w-])reitor(?:a)?(?![\w-])"),
    "diretor_geral": re.compile(r"(?i)(?<![\w-])diretor(?:a)?[-\s]geral(?![\w-])"),
    "superintendente": re.compile(r"(?i)(?<![\w-])superintendente(?![\w-])"),
    "diretor": re.compile(r"(?i)(?<![\w-])diretor(?:a)?(?![\w-])"),
}
DATE_RX = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")
DATE_CTX = re.compile(r"(?i)\b(posse|empossad|desde|assumiu|tomou posse|em exerc[íi]cio|nomead[oa] em|"
                      r"eleit[oa] em|a partir de)\b")

def started(lines, i):
    for j in range(max(0, i - 2), min(len(lines), i + 3)):
        l = lines[j]
        if DATE_CTX.search(l):
            m = DATE_RX.search(l)
            if m:
                d, mo, y = m.groups()
                if 1990 <= int(y) <= int(TODAY[:4]) and 1 <= int(mo) <= 12 and 1 <= int(d) <= 31:
                    return f"{y}-{mo}-{d}"
    return None

RESIDUO_OK = {"de", "do", "da", "dos", "das", "e", "o", "a", "os", "as", "em", "no", "na", "interino",
              "interina", "titular", "atual", "em exercicio", "geral", "tribunal", "instituto", "universidade"}

def so_rotulo(line, m, org_words):
    """True se a linha é essencialmente só o rótulo do cargo (+ o nome do próprio órgão)."""
    residuo = (line[:m.start()] + " " + line[m.end():])
    toks = [t for t in norm(residuo).split() if t and not t.isdigit()]
    return all(t in RESIDUO_OK or t in org_words for t in toks)

VICE_PREFIX = re.compile(r"(?i)(vice|pr[óo]|sub|ex|antig[oa]|futur[oa])[\s-]*$")

def tail_name(txt):
    """Maior nome de pessoa formado pelos últimos tokens de `txt` (ex.: "…professores José Daniel Diniz Melo")."""
    toks = txt.split()
    melhor = None
    for k in range(2, min(9, len(toks)) + 1):
        p = person(" ".join(toks[-k:]))
        if p:
            melhor = p
        elif melhor:
            break
    return melhor

def head_name(txt):
    """Maior nome de pessoa formado pelos primeiros tokens de `txt`."""
    toks = txt.split()
    melhor = None
    for k in range(2, min(9, len(toks)) + 1):
        p = person(" ".join(toks[:k]))
        if p:
            melhor = p
        elif melhor:
            break
    return melhor

def match_cargo(lines, kinds, org_words=frozenset(), proibidos=frozenset()):
    """Procura (nome, linha, cargo_visto, started_at). Prioridade: rótulo→nome, nome→rótulo, vizinhança, colagem."""
    cands = []
    for i, line in enumerate(lines):
        if len(line) > 520 or STOP_LINE.search(line):
            continue
        achou = False
        for k in kinds:
            for m in CARGO_RX[k].finditer(line):
                if VICE_PREFIX.search(line[:m.start()]):
                    continue                      # "Vice Presidente", "Pró-Reitor", "ex Presidente"
                seen, head, tail = line[m.start():m.end()], line[:m.start()], line[m.end():]
                # A) "Presidente: Fulano de Tal" / "Reitora — Fulana"
                mt = re.match(r"^[^:|–—\-]{0,70}?\s*[:|–—]\s*(.+)$", tail) or re.match(r"^\s*[:|–—]\s*(.+)$", tail)
                if mt:
                    p = person(mt.group(1))
                    if p:
                        cands.append((0, i, p, line, seen)); achou = True; break
                # B) "Fulano de Tal - Presidente"
                mh = re.search(r"(.+?)\s*[-–—|,:]\s*$", head)
                if mh:
                    p = person(mh.group(1))
                    if p:
                        cands.append((1, i, p, line, seen)); achou = True; break
                # C) rótulo isolado: nome na linha vizinha
                if len(line) <= 90 and so_rotulo(line, m, org_words):
                    for pri, j in ((2, i + 1), (3, i - 1), (4, i + 2)):
                        if 0 <= j < len(lines) and not STOP_LINE.search(lines[j]):
                            p = person(lines[j])
                            if p:
                                cands.append((pri, i, p, f"{line} | {lines[j]}", seen)); achou = True; break
                    if achou:
                        break
                # D) a linha inteira é "cargo + nome"
                p = person((head + " " + tail).strip())
                if p:
                    cands.append((5, i, p, line, seen)); achou = True; break
                # E) nome grudado no rótulo no meio da linha: "…professores Fulano (Reitor)" / "Presidente Fulano"
                p = tail_name(head) or head_name(tail)
                if p:
                    cands.append((6 if len(line) <= 160 else 7, i, p, line, seen)); achou = True; break
            if achou:
                break
    if not cands:
        return None
    cands.sort(key=lambda c: (c[0], c[1]))
    for pri, i, p, line, seen in cands:
        if set(norm(p).split()) & proibidos:
            continue                      # "… Soares UFV": a sigla do órgão grudou no nome
        return {"name": p, "linha": clip(line, 180), "cargo_visto": seen,
                "started_at": started(lines, i), "pri": pri}
    return None

# ------------------------------------------------------------------ escolha das páginas a visitar
LINK_KEYS = [
    (0, r"presid[êe]ncia|gabinete da presid|presidente do tribunal|reitoria|reitor|gabinete do reitor|"
        r"diretor(?:ia)?[- ]presid|diretoria executiva|direc[ãa]o[- ]geral|diretor[- ]geral"),
    (1, r"composi[çc][ãa]o|quem [ée] quem|administra[çc][ãa]o superior|alta administra|dirigentes|"
        r"gest[ãa]o \d{4}|corpo diretivo|diretoria|governan[çc]a corporativa|superintend[êe]ncia"),
    (2, r"institucional|sobre (o|a)|a (empresa|universidade|institui|companhia)|conhe[çc]a|estrutura|"
        r"o tribunal|organiza[çc][ãa]o"),
]
PATHS = {
    "tribunais": ["institucional/presidencia", "presidencia", "institucional/composicao", "composicao",
                  "institucional/gestao", "sobre-o-tribunal/presidencia", "o-trt/presidencia",
                  "institucional/presidencia/gabinete-da-presidencia", "conheca-o-tribunal/presidencia"],
    "estatais": ["acesso-a-informacao/institucional/quem-e-quem", "composicao/quem-e-quem",
                 "institucional/quem-e-quem", "pt-br/acesso-a-informacao/institucional/quem-e-quem",
                 "institucional/diretoria", "a-empresa/diretoria", "sobre/diretoria", "quem-somos/diretoria",
                 "governanca/diretoria-executiva", "institucional/governanca/diretoria"],
    "ensino": ["reitoria", "reitoria/reitor", "sobre/reitoria", "institucional/reitoria", "a-universidade/reitoria",
               "administracao/reitoria", "gabinete-do-reitor", "pt-br/acesso-a-informacao/institucional/quem-e-quem",
               "acesso-a-informacao/institucional/quem-e-quem", "institucional/gestao", "o-ifce/reitoria"],
}

VICE_RX = re.compile(r"(?i)vice[- ]?(presid|reitor|diret)")

def ordered_links(h, base, limit=6):
    got, seen = [], set()
    links = page_links(h, base)
    # truque: se o site expõe "Vice-Presidência"/"Vice-Reitoria", a página do titular costuma ser a mesma
    # URL sem o "vice" — é o caminho mais confiável em portais de tribunal.
    for url, txt in links:
        if VICE_RX.search(txt) or VICE_RX.search(url):
            alvo = re.sub(r"(?i)vice[-_]?", "", url)
            if alvo != url and alvo not in seen:
                seen.add(alvo)
                got.append((-1, alvo, f"(derivado de) {txt}"))
    for rank, rx in LINK_KEYS:
        rxc = re.compile(rx, re.I)
        for url, txt in links:
            if len(txt) > 70 or url in seen or VICE_RX.search(txt):
                continue
            if rxc.search(strip_acc(txt)) or rxc.search(txt):
                seen.add(url)
                got.append((rank, url, txt))
    got.sort(key=lambda g: g[0])
    return got[:limit]

def sane(url):
    if not url or not isinstance(url, str):
        return None
    url = url.strip().rstrip(".").strip()
    url = re.sub(r"\s+", "", url)
    if url.count("http") > 1:
        url = "http" + url.split("http")[-1]
    if not url.startswith("http"):
        return None
    if re.search(r"facebook\.com|instagram\.com|twitter\.com|x\.com|youtube\.com", url):
        return None
    return url.rstrip("/")

# uma página só vale como fonte do titular se o caminho for de cargo/composição (segmento exato) — assim
# notícias ("/reitoria-atua-para-…"), galerias de ex-dirigentes e home pages não viram fonte de nome.
PAG_CARGO = {"presidencia", "presidente", "presidenta", "reitoria", "reitor", "reitora", "composicao",
             "quem-e-quem", "quem-somos", "direcao", "direcao-geral", "diretoria", "diretoria-executiva",
             "direx", "dirigentes", "gestao", "gabinete", "gabinete-do-reitor", "institucional",
             "administracao", "administracao-superior", "estrutura-administrativa", "alta-administracao",
             "composicao-do-tribunal", "composicao-do-trt", "conselho-superior", "reitoria-1", "reitoria-2"}
PAG_VETO = re.compile(r"(?i)/(noticia|noticias|news|blog|node|galeria|ex-reitor|ex-presidente|memoria|"
                      r"historico|arquivo|agenda|imprensa|evento|artigo)")

def pagina_confiavel(url, pri):
    if PAG_VETO.search(url):
        return False
    segs = [s for s in urllib.parse.urlparse(url).path.split("/") if s]
    return bool(set(segs) & PAG_CARGO) or pri <= 1

def hunt(org, refresh=False):
    """Varre o site do órgão e devolve (achado, paginas_tentadas, erros)."""
    kinds, ow = org["kinds"], org["org_words"]
    proib = set(norm(org.get("sigla") or "").split())
    tried, erros, budget = [], [], MAX_PAGES

    def ler(url):
        """(pagina, achado, erro) — pagina = (html, url_final)."""
        nonlocal budget
        if url in tried or budget <= 0:
            return None, None, None
        h, f = fetch(url, refresh)
        budget -= 1
        tried.append(url)
        if not h:
            return None, None, f
        final = f if str(f).startswith("http") else url
        got = match_cargo(to_lines(h), kinds, ow, proib)
        if got and not pagina_confiavel(final, got["pri"]):
            got = None            # casamento fraco em página que não é de cargo: descarta
        if got:
            got["source_url"] = final
        return (h, final), got, None

    for base in org["sites"]:
        if budget <= 0:
            break
        r, got, err = ler(base)
        if got:
            return got, tried, erros
        if r is None:
            if err:
                erros.append(f"{base}: {err}")
            continue
        h, final = r
        lk = ordered_links(h, final)
        # portais de tribunal repetem a sigla no caminho (trf2.jus.br/trf2/institucional/presidencia)
        labels = [x for x in urllib.parse.urlparse(base).netloc.split(".") if x not in ("www", "ww2", "portal", "novo")]
        sig = labels[0] if labels else ""
        pref = [f"{base}/{sig}/{p}" for p in ("institucional/presidencia", "institucional/composicao")] \
            if sig and org["bloco"] == "tribunais" else []
        cand = ([u for rk, u, _ in lk if rk <= 1] + pref + [f"{base}/{p}" for p in PATHS[org["bloco"]]] +
                [u for rk, u, _ in lk if rk > 1])
        deep = []
        for url in cand:
            if budget <= 0:
                break
            r2, got, _e = ler(url)
            if got:
                return got, tried, erros
            if r2 and len(deep) < 4:
                deep += [u for _, u, _ in ordered_links(r2[0], r2[1], 3)]
        for url in deep:
            if budget <= 0:
                break
            _r, got, _e = ler(url)
            if got:
                return got, tried, erros
    return None, tried, erros

# ------------------------------------------------------------------ dados estáticos
UF = {"acre": "AC", "alagoas": "AL", "amapa": "AP", "amazonas": "AM", "bahia": "BA", "ceara": "CE",
      "distrito-federal": "DF", "espirito-santo": "ES", "goias": "GO", "maranhao": "MA", "mato-grosso": "MT",
      "mato-grosso-do-sul": "MS", "minas-gerais": "MG", "para": "PA", "paraiba": "PB", "parana": "PR",
      "pernambuco": "PE", "piaui": "PI", "rio-de-janeiro": "RJ", "rio-grande-do-norte": "RN",
      "rio-grande-do-sul": "RS", "rondonia": "RO", "roraima": "RR", "santa-catarina": "SC", "sao-paulo": "SP",
      "sergipe": "SE", "tocantins": "TO"}
TRF_UFS = {1: "AC, AM, AP, BA, DF, GO, MA, MT, PA, PI, RO, RR e TO", 2: "Rio de Janeiro e Espírito Santo",
           3: "São Paulo e Mato Grosso do Sul", 4: "Rio Grande do Sul, Santa Catarina e Paraná",
           5: "AL, CE, PB, PE, RN e SE", 6: "Minas Gerais"}
# sites oficiais corretos onde o official_url do grafo está vazio, errado ou aponta para o ministério
SITE_FIX = {
    "br-hospital-de-clinicas-de-porto-alegre": "https://www.hcpa.edu.br",
    "br-empresa-brasileira-de-hemoderivados-e-biotecnologia": "https://www.gov.br/hemobras/pt-br",
    "br-empresa-brasileira-de-participacoes-em-energia-nuclear-e-binacional-s-a": "https://www.gov.br/enbpar/pt-br",
    "br-eletronuclear-s-a": "https://www.gov.br/eletronuclear/pt-br",
    "br-fundacao-jorge-duprat-figueiredo-de-seguranca-e-medicina-do-trabalho": "https://www.gov.br/fundacentro/pt-br",
    "br-empresa-de-trens-urbanos-de-porto-alegre-s-a": "https://www.trensurb.gov.br",
    "br-empresa-gerencial-de-projetos-navais": "https://www.emgepron.mar.mil.br",
    "br-amazonia-azul-tecnologias-de-defesa-s-a": "https://www.amazul.gov.br",
    "br-nav-brasil-servicos-de-navegacao-aerea-s-a": "https://www.navbrasil.gov.br",
    "br-industria-de-material-belico-do-brasil": "https://www.gov.br/imbel/pt-br",
    "br-superintendencia-da-zona-franca-de-manaus": "https://www.gov.br/suframa/pt-br",
    "br-autoridade-nacional-de-seguranca-nuclear": "https://www.gov.br/ansn/pt-br",
    "br-caixa-de-construcoes-de-casas-para-o-pessoal-da-marinha": "https://www.marinha.mil.br/cccpm",
    "br-caixa-de-financiamento-imobiliario-da-aeronautica": "https://www.cfiae.fab.mil.br",
    "br-banco-do-nordeste-do-brasil-s-a": "https://www.bnb.gov.br",
    "br-instituto-brasileiro-de-museus": "https://www.gov.br/museus/pt-br",
    "br-instituto-de-pesquisas-jardim-botanico-do-rio-de-janeiro": "https://www.gov.br/jbrj/pt-br",
    "br-fundacao-de-previdencia-complementar-do-servidor-publico-federal-do-poder-executivo": "https://www.funpresp.com.br",
    "br-fundacao-joaquim-nabuco": "https://www.gov.br/fundaj/pt-br",
    "br-fundacao-casa-de-rui-barbosa": "https://www.gov.br/casaruibarbosa/pt-br",
    "br-fundacao-habitacional-do-exercito": "https://www.fhe.org.br",
    "br-grupo-hospitalar-conceicao-s-a": "https://www.ghc.com.br",
    "br-companhia-de-pesquisa-de-recursos-minerais": "https://www.sgb.gov.br",
    "br-autoridade-portuaria-de-santos-s-a": "https://www.portodesantos.com.br",
    "br-companhia-brasileira-de-trens-urbanos": "https://www.gov.br/cbtu/pt-br",
    "br-empresa-gestora-de-ativos": "https://www.emgea.gov.br",
    "br-agencia-brasileira-gestora-de-fundos-garantidores-e-garantias-s-a": "https://www.abgf.gov.br",
    "br-empresa-brasileira-de-administracao-de-petroleo-e-gas-natural-s-a-pre-sal-petroleo-s-a": "https://www.presalpetroleo.gov.br",
    "br-centro-nacional-de-tecnologia-eletronica-avancada-s-a": "https://www.ceitec-sa.com",
    "br-companhia-docas-do-rio-grande-do-norte": "https://codern.com.br",
    "br-centrais-de-abastecimento-de-minas-gerais-s-a": "http://www.ceasaminas.com.br",
    "br-companhia-de-entrepostos-e-armazens-gerais-de-sao-paulo": "https://www.ceagesp.gov.br",
    "br-industrias-nucleares-do-brasil-s-a": "https://www.gov.br/inb/pt-br",
    "br-nuclebras-equipamentos-pesados-s-a": "https://www.nuclep.gov.br",
    "br-colegio-pedro-ii": "https://www.cp2.g12.br",
    "br-fundacao-universidade-do-amazonas": "https://ufam.edu.br",
    "br-instituto-federal-de-educacao-ciencia-e-tecnologia-de-brasilia": "https://www.ifb.edu.br",
    "br-universidade-federal-de-campina-grande": "https://www.ufcg.edu.br",
}
# cargo canônico quando não é "Presidente" (estatais) nem "Reitor" (ensino)
CARGO_FIX = {
    "br-superintendencia-da-zona-franca-de-manaus": ("Superintendente", "superintendente"),
    "br-autoridade-nacional-de-seguranca-nuclear": ("Diretor-Presidente", "diretor-presidente"),
    "br-fundacao-de-previdencia-complementar-do-servidor-publico-federal-do-poder-executivo":
        ("Diretor-Presidente", "diretor-presidente"),
    "br-fundacao-habitacional-do-exercito": ("Diretor-Presidente", "diretor-presidente"),
    "br-caixa-de-construcoes-de-casas-para-o-pessoal-da-marinha": ("Diretor", "diretor"),
    "br-caixa-de-financiamento-imobiliario-da-aeronautica": ("Diretor", "diretor"),
    "br-fundacao-osorio": ("Diretor", "diretor"),
    "br-centro-federal-de-educacao-tecnologica-celso-suckow-da-fonseca": ("Diretor-Geral", "diretor-geral"),
    "br-centro-federal-de-educacao-tecnologica-de-minas-gerais": ("Diretor-Geral", "diretor-geral"),
}
SUBSIDIARIAS = {"br-caixa-economica-federal",
                "br-empresa-brasileira-de-participacoes-em-energia-nuclear-e-binacional-s-a"}
# lei de criação conferida no Planalto (só as que foram checadas; as demais ficam sem esta citação)
LEI_CRIACAO = {
    "br-instituto-brasileiro-de-museus": ("Lei 11.906/2009 (cria o Ibram)",
                                          f"{PLANALTO}/_ato2007-2010/2009/lei/l11906.htm"),
    "br-instituto-de-pesquisas-jardim-botanico-do-rio-de-janeiro":
        ("Lei 10.316/2001 (cria a autarquia federal JBRJ)", f"{PLANALTO}/leis/LEIS_2001/L10316.htm"),
    "br-superintendencia-da-zona-franca-de-manaus":
        ("Decreto-Lei 288/1967 (regula a Zona Franca de Manaus e cria a Suframa)",
         f"{PLANALTO}/decreto-lei/del0288.htm"),
    "br-fundacao-jorge-duprat-figueiredo-de-seguranca-e-medicina-do-trabalho":
        ("Lei 5.161/1966 (institui a Fundacentro)", f"{PLANALTO}/leis/l5161.htm"),
    "br-fundacao-de-previdencia-complementar-do-servidor-publico-federal-do-poder-executivo":
        ("Lei 12.618/2012 (regime de previdência complementar do servidor federal)",
         f"{PLANALTO}/_ato2011-2014/2012/lei/l12618.htm"),
    "br-fundacao-habitacional-do-exercito": ("Lei 6.855/1980 (cria a Fundação Habitacional do Exército)",
                                             f"{PLANALTO}/leis/1980-1988/L6855.htm"),
    "br-fundacao-casa-de-rui-barbosa": ("Lei 4.943/1966 (institui a Fundação Casa de Rui Barbosa)",
                                        f"{PLANALTO}/leis/1950-1969/L4943.htm"),
    "br-fundacao-joaquim-nabuco": ("Lei 6.687/1979 (institui a Fundação Joaquim Nabuco)",
                                   f"{PLANALTO}/leis/1970-1979/L6687.htm"),
}
ARTIGO = {"tribunal": "do", "tribunais": "dos", "universidade": "da", "instituto": "do", "fundacao": "da",
          "companhia": "da", "empresa": "da", "banco": "do", "centro": "do", "colegio": "do", "hospital": "do",
          "grupo": "do", "veiculo": "do", "caixa": "da", "agencia": "da", "superintendencia": "da",
          "autoridade": "da", "industria": "da", "industrias": "das", "centrais": "das", "amazonia": "da",
          "nav": "da", "eletronuclear": "da", "nuclebras": "da", "conselho": "do", "escola": "da",
          "imprensa": "da", "justica": "da", "secao": "da", "pre": "da"}

DEF = {"do": "o", "da": "a", "dos": "os", "das": "as"}
AO = {"do": "ao", "da": "à", "dos": "aos", "das": "às"}

def artigo(name):
    """'do'/'da'/'dos'/'das' — para compor "Presidente __ Órgão"."""
    return ARTIGO.get(norm(name).split()[0] if norm(name) else "", "do")

def art_def(name):
    """'o'/'a'/'os'/'as' — para compor "Dirige __ Órgão"."""
    return DEF[artigo(name)]

def vinculada_a(parent_name):
    return f"{AO[artigo(parent_name)]} {parent_name}" if parent_name else ""

FINAL_RX = re.compile(r"(?i)^.{0,220}?\btem\s+(?:por|como|as\s+seguintes|os\s+seguintes)\s+"
                      r"(?:finalidade|objetivo|miss[ãa]o|compet[êe]ncia|atribui[çc][õo]e|atribui[çc][ãa]o)s?"
                      r"(?:\s+e\s+caracter[íi]sticas?)?\s*[:,]?\s*")

def finalidade(txt, n=190):
    t = re.sub(r"\s+", " ", txt or "").strip().replace("…", "")
    t = FINAL_RX.sub("", t)
    for _ in range(3):
        novo = re.sub(r"^\s*(I{1,3}|IV|V|[0-9]+)\s*[-–—)\.]\s*", "", t)
        novo = re.sub(r"^(A|O|As|Os|À|Ao)\s+(?=[A-ZÁÀÂÃÉÊÍÓÔÕÚÜÇ])", "", novo)
        if novo == t:
            break
        t = novo
    t = t.strip()
    m = re.split(r"(?<=[a-zç0-9])\.\s+|;\s+", t)
    t = m[0] if m and len(m[0]) > 45 else t
    t = clip(t, n).rstrip(" .;,-")
    return t[:1].lower() + t[1:] if t else ""

# ------------------------------------------------------------------ montagem dos cargos
def build_orgs(graph, blocos):
    nodes = graph["nodes"]
    headed = {n.get("head_of") for n in nodes.values() if n.get("type") == "dept_head"}
    # o grafo já traz os cargos que ESTE conector gerou ontem: se eles contarem como "órgão já chefiado",
    # a lista de faltantes fica vazia e o arquivo é reescrito com zero cargos, apagando o trabalho anterior.
    proprios = set()
    if OUT.exists():
        try:
            ant = yaml.safe_load(open(OUT, encoding="utf-8")) or {}
            proprios = {q.get("head_of") for q in (ant.get("positions") or []) if q.get("head_of")}
        except Exception:
            proprios = set()
    headed -= proprios
    missing = [n for i, n in nodes.items() if n.get("type") == "department" and i not in headed]
    orgs, fora = [], []

    for n in missing:
        nid, name, sub = n["id"], n["name"], n.get("subtype")
        sigla = (n.get("aliases") or [None])[0]
        parent = nodes.get(n.get("parent") or "", {})
        fin = finalidade(n.get("description"))
        site = sane(SITE_FIX.get(nid) or n.get("official_url"))
        alt = sane(n.get("official_url"))
        o = None

        # ---------------- tribunais
        if sub == "tribunal":
            if nid in ("br-tribunais-regionais-do-trabalho", "br-tribunais-regionais-eleitorais"):
                fora.append({"no": nid, "motivo": "nó guarda-chuva, não é um tribunal com presidência própria"})
                continue
            curto = re.sub(r"\s*\([^)]*\)\s*$", "", name)
            m = re.match(r"br-tribunal-regional-federal-da-(\d)a-regiao$", nid)
            if m:
                r = int(m.group(1))
                site = f"https://www.trf{r}.jus.br"
                desc = (f"Preside o {curto}, tribunal de segundo grau da Justiça Federal com jurisdição sobre "
                        f"{TRF_UFS[r]}. Dirige os serviços judiciários da Região, preside as sessões do Plenário e do "
                        f"Órgão Especial, distribui os feitos e responde pela gestão administrativa, orçamentária e "
                        f"correicional do tribunal.")
                cite = ('CF/88 art. 96, I, "a", e art. 107; LC 35/1979 (LOMAN) art. 102')
            elif re.match(r"br-tribunal-regional-do-trabalho-da-\d+a-regiao", nid):
                r = int(re.search(r"da-(\d+)a-regiao", nid).group(1))
                ufs = (re.search(r"\(([^)]*)\)", name).group(1) if "(" in name else "")
                site = f"https://www.trt{r}.jus.br"
                desc = (f"Preside o {curto}, segundo grau da Justiça do Trabalho em {ufs}. Convoca e dirige as sessões "
                        f"do Tribunal Pleno e do Órgão Especial, superintende as Varas do Trabalho da Região, assina "
                        f"os atos de gestão de pessoal e representa o tribunal perante o TST e o CSJT.")
                cite = ('CF/88 art. 96, I, "a", e art. 115; LC 35/1979 (LOMAN) art. 102')
            elif nid.startswith("br-tribunal-regional-eleitoral-"):
                uf_slug = re.sub(r"^br-tribunal-regional-eleitoral-d[aeo]s?-", "", nid)
                uf = UF.get(uf_slug, "")
                site = f"https://www.tre-{uf.lower()}.jus.br" if uf else site
                desc = (f"Preside o {curto}. O cargo é exercido por um dos dois desembargadores do Tribunal de Justiça "
                        f"que integram a Corte eleitoral: dirige as sessões do pleno, responde pela administração da "
                        f"Justiça Eleitoral em {uf}, pelo cadastro de eleitores e pela organização e apuração das "
                        f"eleições no estado.")
                cite = ("CF/88 art. 120, § 1º, I, e § 2º; Código Eleitoral (Lei 4.737/1965) art. 25")
            elif nid == "br-tribunal-de-justica-do-distrito-federal-e-dos-territorios":
                site = "https://www.tjdft.jus.br"
                desc = ("Preside o Tribunal de Justiça do Distrito Federal e dos Territórios, único tribunal de justiça "
                        "mantido pela União. Dirige o Conselho Especial, superintende a Justiça de primeiro grau do DF, "
                        "responde pela proposta orçamentária do tribunal e o representa perante o CNJ e o STJ.")
                cite = ('CF/88 art. 96, I, "a", e art. 21, XIII; Lei 11.697/2008 art. 8º')
            else:
                fora.append({"no": nid, "motivo": "tribunal sem regra de presidência mapeada"})
                continue
            o = dict(bloco="tribunais", cargo="Presidente", sufixo="presidente", mandato=2,
                     eleito_por=nid, nomeado_por=None, kinds=["presidente"],
                     cite=cite, cite_url=CF, desc=desc, entry_mode="eleito_pares",
                     nome_cargo=f"Presidente {artigo(curto)} {curto}")

        # ---------------- seções judiciárias: sem presidência em lei
        elif sub == "secao_judiciaria":
            fora.append({"no": nid, "motivo": "seção judiciária é dirigida por juiz federal diretor do foro "
                                              "(Lei 5.010/1966 art. 12), não há presidência definida em lei"})
            continue

        # ---------------- estatais, autarquias e fundações
        elif sub in ("empresa_publica", "sociedade_economia_mista", "autarquia", "fundacao"):
            cargo, sufixo = CARGO_FIX.get(nid, ("Presidente", "presidente"))
            estatal = sub in ("empresa_publica", "sociedade_economia_mista")
            sub_de = n.get("parent") in SUBSIDIARIAS
            tipo = {"empresa_publica": "empresa pública federal",
                    "sociedade_economia_mista": "sociedade de economia mista federal",
                    "autarquia": "autarquia federal", "fundacao": "fundação pública federal"}[sub]
            sig = f" ({sigla})" if sigla else ""
            vinc = f", vinculada {vinculada_a(parent.get('name'))}" if parent.get("name") else ""
            ad = art_def(name)
            if estatal and sub_de:
                cite = ("Lei 13.303/2016 arts. 13, III, e 17; Lei 6.404/1976 art. 143 (diretoria eleita pelo "
                        "conselho de administração da controladora)")
                cite_url = f"{PLANALTO}/_ato2015-2018/2016/lei/l13303.htm"
                nomeado, eleito, mand = n.get("parent"), None, 2
                desc = (f"Chefia a diretoria executiva {artigo(name)} {name}{sig}, {tipo} controlada por "
                        f"{parent.get('name')}. Eleito pelo conselho de administração da controladora, representa a "
                        f"sociedade e responde pelo plano de negócios da subsidiária. Objeto: {fin}.")
            elif estatal:
                cite = ("Lei 13.303/2016 art. 12 (transparência), art. 13, III (prazo de gestão unificado de até dois "
                        "anos) e art. 17 (requisitos de investidura dos administradores)")
                cite_url = f"{PLANALTO}/_ato2015-2018/2016/lei/l13303.htm"
                nomeado, eleito, mand = "br-presidente-da-republica", None, 2
                desc = (f"Preside {ad} {name}{sig}, {tipo}{vinc}. Chefia a diretoria executiva, representa a empresa "
                        f"em juízo e fora dele e responde pela execução do plano de negócios e da estratégia de longo "
                        f"prazo aprovados pelo conselho de administração. Objeto social: {fin}.")
            elif nid == "br-autoridade-nacional-de-seguranca-nuclear":
                cite = "Lei 14.222/2021 arts. 4º e 5º"
                cite_url = f"{PLANALTO}/_ato2019-2022/2021/lei/L14222.htm"
                nomeado, eleito, mand = "br-presidente-da-republica", None, 5
                desc = ("Dirige a Autoridade Nacional de Segurança Nuclear (ANSN), autarquia sob regime especial que "
                        "licencia, regula e fiscaliza as instalações nucleares e radiativas do país. Nomeado pelo "
                        "Presidente da República após aprovação do Senado Federal, com mandato de cinco anos, vedada "
                        "a recondução.")
            else:
                lei, lei_url = LEI_CRIACAO.get(nid, (None, None))
                cite = "; ".join(x for x in [lei, "Lei 8.112/1990 art. 9º, II",
                                             "Decreto 9.727/2019 (critérios para cargos comissionados de direção)"] if x)
                cite_url = lei_url or f"{PLANALTO}/_ato2019-2022/2019/decreto/D9727.htm"
                nomeado, eleito, mand = "br-presidente-da-republica", None, None
                desc = (f"Dirige {ad} {name}{sig}, {tipo}{vinc}. Cargo de direção superior de livre nomeação e "
                        f"exoneração, que representa {ad} {sigla or 'órgão'} e responde por sua finalidade legal: {fin}.")
            kinds = ["diretor_presidente", "presidente"] if sufixo in ("presidente", "diretor-presidente") else \
                    (["superintendente"] if sufixo == "superintendente" else
                     (["diretor_geral", "diretor_presidente", "presidente", "diretor"]))
            o = dict(bloco="estatais", cargo=cargo, sufixo=sufixo, mandato=mand, eleito_por=eleito,
                     nomeado_por=nomeado, kinds=kinds, cite=cite, cite_url=cite_url, desc=desc,
                     entry_mode="nomeado", nome_cargo=f"{cargo} {artigo(name)} {name}")

        # ---------------- instituições de ensino
        elif sub == "instituicao_de_ensino":
            sig = f" ({sigla})" if sigla else ""
            if nid in CARGO_FIX:                      # CEFETs
                cargo, sufixo = CARGO_FIX[nid]
                cite = "Decreto 5.224/2004 arts. 8º, VIII, e 9º (mandato de quatro anos, após consulta à comunidade)"
                cite_url = f"{PLANALTO}/_ato2004-2006/2004/decreto/d5224.htm"
                desc = (f"Dirige o {name}{sig}, autarquia federal de educação profissional e tecnológica. Chefia a "
                        f"Direção-Geral, executa a política homologada pelo Conselho Diretor e responde pela gestão "
                        f"acadêmica, orçamentária e de pessoal do centro. Finalidade: {fin}.")
                kinds = ["diretor_geral", "reitor"]
            elif nid == "br-colegio-pedro-ii":
                cargo, sufixo = "Reitor", "reitor"
                cite = ("Lei 12.677/2012 art. 8º (equiparação do Colégio Pedro II aos institutos federais); "
                        "Lei 11.892/2008 art. 12")
                cite_url = f"{PLANALTO}/_ato2011-2014/2012/lei/l12677.htm"
                desc = ("Dirige o Colégio Pedro II, instituição federal de educação básica equiparada aos institutos "
                        "federais. Preside o Conselho Superior, responde pelos campi do Rio de Janeiro e pela gestão "
                        "acadêmica, orçamentária e de pessoal da instituição, com mandato de quatro anos.")
                kinds = ["reitor", "diretor_geral"]
            elif norm(name).startswith("instituto federal"):
                cargo, sufixo = "Reitor", "reitor"
                cite = "Lei 11.892/2008 arts. 11 e 12 (reitor nomeado para mandato de quatro anos após consulta à comunidade escolar)"
                cite_url = f"{PLANALTO}/_ato2007-2010/2008/lei/l11892.htm"
                desc = (f"Dirige o {name}{sig}, autarquia federal de educação profissional e tecnológica com campi em "
                        f"vários municípios, que tem por finalidade {finalidade(n.get('description'), 130)}. Preside "
                        f"o Conselho Superior e o Colégio de Dirigentes, nomeia os pró-reitores e os diretores-gerais "
                        f"de campus e responde pelo orçamento do instituto.")
                kinds = ["reitor"]
            else:
                cargo, sufixo = "Reitor", "reitor"
                cite = ("Lei 5.540/1968 art. 16, com a redação da Lei 9.192/1995 (nomeação pelo Presidente da "
                        "República a partir de lista tríplice, mandato de quatro anos)")
                cite_url = f"{PLANALTO}/leis/L9192.htm"
                desc = (f"Dirige {art_def(name)} {name}{sig}, instituição federal de ensino superior cuja finalidade "
                        f"é {finalidade(n.get('description'), 140)}. Representa a universidade, preside o conselho "
                        f"universitário, provê os cargos do quadro e responde pela gestão acadêmica, orçamentária e "
                        f"de pessoal, escolhido em lista tríplice do colegiado máximo.")
                kinds = ["reitor"]
            art = artigo(name)
            o = dict(bloco="ensino", cargo=cargo, sufixo=sufixo, mandato=4, eleito_por=None,
                     nomeado_por="br-presidente-da-republica", kinds=kinds, cite=cite, cite_url=cite_url,
                     desc=desc, entry_mode="nomeado", nome_cargo=f"{cargo} {art} {name}")
        else:
            fora.append({"no": nid, "motivo": f"subtype {sub} fora do escopo dos três blocos"})
            continue

        ow = set(norm(name).split()) | set(norm(sigla or "").split()) | set(norm(parent.get("name") or "").split())
        ow |= {"regiao", "regional", "ª", "trf", "trt", "tre"}
        o.update(id=nid, node=n, name=name, sigla=sigla, site_oficial=site, org_words=ow,
                 sites=sites_for(nid, site, sigla, o["bloco"], alt))
        orgs.append(o)
    return orgs, fora

def sites_for(nid, site, sigla, bloco, alt=None):
    out = []
    for u in (site, alt):
        if u and u not in out:
            out.append(u)
    if bloco == "ensino" and sigla:
        s = strip_acc(sigla).lower()
        variants = {re.sub(r"[^a-z0-9]", "", s), re.sub(r"[^a-z0-9-]", "", s.replace(" ", "-")),
                    re.sub(r"[^a-z0-9]", "", s.split("-")[0])}
        for v in sorted(variants):
            if len(v) < 3 or not re.fullmatch(r"[a-z0-9][a-z0-9-]*[a-z0-9]", v):
                continue
            for host in (f"https://www.{v}.br", f"https://www.{v}.edu.br", f"https://{v}.edu.br"):
                if host not in out:
                    out.append(host)
    return out[:5]

# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--amostra", type=int, default=0, help="N órgãos por bloco")
    ap.add_argument("--bloco", choices=["tribunais", "estatais", "ensino"], help="um bloco só")
    ap.add_argument("--no-web", action="store_true", help="não busca ocupantes")
    ap.add_argument("--refresh", action="store_true", help="ignora o cache HTTP")
    ap.add_argument("--force-shrink", action="store_true", help="aceita gravar bem menos cargos que o arquivo atual")
    args = ap.parse_args()
    t0 = time.time()

    graph = json.load(open(GRAPH, encoding="utf-8"))
    blocos = [args.bloco] if args.bloco else ["tribunais", "estatais", "ensino"]
    orgs, fora = build_orgs(graph, blocos)
    ordem = {"tribunais": 0, "estatais": 1, "ensino": 2}
    orgs = sorted((o for o in orgs if o["bloco"] in blocos), key=lambda o: (ordem[o["bloco"]], o["id"]))
    if args.amostra:
        keep, cnt = [], {}
        for o in orgs:
            cnt[o["bloco"]] = cnt.get(o["bloco"], 0) + 1
            if cnt[o["bloco"]] <= args.amostra:
                keep.append(o)
        orgs = keep

    positions, falhas = [], []
    com_ocupante = {b: 0 for b in blocos}
    total = {b: 0 for b in blocos}
    for k, o in enumerate(orgs, 1):
        total[o["bloco"]] += 1
        people = []
        if not args.no_web:
            if not o["sites"]:
                falhas.append({"orgao": o["id"], "motivo": "sem site oficial conhecido"})
            else:
                got, tried, erros = hunt(o, args.refresh)
                if got:
                    com_ocupante[o["bloco"]] += 1
                    people = [OrderedDict([
                        ("id", f"br-p-{slug(got['name'])}"),
                        ("name", got["name"]),
                        ("started_at", got["started_at"]),
                        ("entry_mode", o["entry_mode"]),
                        ("source", "oficial"),
                        ("source_url", got["source_url"]),
                        ("checked_at", TODAY),
                        ("verified", False),
                        ("note", f"página oficial do órgão; cargo na página: \"{got['cargo_visto']}\"; "
                                 f"trecho: {got['linha']}"),
                    ])]
                else:
                    falhas.append({"orgao": o["id"],
                                   "motivo": clip("; ".join(erros) if erros else
                                                  f"{len(tried)} página(s) lida(s) sem casamento de cargo e nome", 180),
                                   "paginas": tried[:4]})
        p = OrderedDict()
        p["id"] = f"{o['id']}-{o['sufixo']}"
        p["type"] = "dept_head"
        p["head_of"] = o["id"]
        p["name"] = re.sub(r"\s+", " ", o["nome_cargo"]).strip()
        if o["eleito_por"]:
            p["eleito_por"] = o["eleito_por"]
        if o["nomeado_por"]:
            p["nomeado_por"] = o["nomeado_por"]
        p["seats"] = 1
        if o["mandato"]:
            p["mandato_anos"] = o["mandato"]
        p["cite"] = o["cite"]
        p["cite_url"] = o["cite_url"]
        p["description"] = clip(re.sub(r"…\s*\.", "…", o["desc"]), 560)
        url_of = o["site_oficial"]
        if people:
            pr = urllib.parse.urlparse(people[0]["source_url"])
            url_of = f"{pr.scheme}://{pr.netloc}"
        if url_of:
            p["official_url"] = url_of
        p["verified"] = False
        p["people"] = people
        positions.append(p)
        if k % 10 == 0 or k == len(orgs):
            print(f"  [{k}/{len(orgs)}] {o['id']} — ocupantes: "
                  f"{sum(com_ocupante.values())}/{k}", flush=True)

    dur = round(time.time() - t0)
    doc = OrderedDict()
    doc["generated_from"] = ("build/graph.br.json (nós department sem dept_head) + sites oficiais dos tribunais, "
                             "estatais e instituições federais de ensino")
    doc["generated_at"] = TODAY
    doc["resumo"] = OrderedDict([
        ("cargos_criados", OrderedDict((b, total[b]) for b in blocos)),
        ("cargos_criados_total", len(positions)),
        ("com_ocupante", OrderedDict((b, com_ocupante[b]) for b in blocos)),
        ("com_ocupante_total", sum(com_ocupante.values())),
        ("sem_ocupante", len(positions) - sum(com_ocupante.values())),
        ("orgaos_fora_do_escopo", fora),
        ("paginas_nao_lidas", falhas),
        ("requisicoes_http", _stats["fetch"]),
        ("cache_hits", _stats["hit"]),
        ("duracao_s", dur),
    ])
    doc["nodes"] = []
    doc["positions"] = positions

    OUT.parent.mkdir(parents=True, exist_ok=True)
    yaml.add_representer(OrderedDict, lambda d, x: d.represent_mapping("tag:yaml.org,2002:map", x.items()))
    # nunca encolher sem aviso: se o resultado tem menos da metade dos cargos do arquivo anterior,
    # é sinal de fonte fora do ar ou de colisão com o próprio dado — mantém o que já estava lá.
    if OUT.exists() and not args.force_shrink:
        try:
            ant = yaml.safe_load(open(OUT, encoding="utf-8")) or {}
            n_ant = len(ant.get("positions") or [])
        except Exception:
            n_ant = 0
        oc_ant = sum(1 for q in (ant.get("positions") or []) if q.get("people"))
        oc_novo = sum(1 for q in positions if q.get("people"))
        if n_ant and len(positions) < n_ant / 2:
            print(f"ABORTADO: sairiam {len(positions)} cargos contra {n_ant} do arquivo atual. "
                  f"Mantido o anterior; use --force-shrink se a queda for real.", file=sys.stderr)
            sys.exit(1)
        if oc_ant and oc_novo < oc_ant / 2:
            print(f"ABORTADO: sairiam {oc_novo} ocupantes contra {oc_ant} do arquivo atual "
                  f"(sites fora do ar, ou --no-web sem querer). Mantido o anterior; use --force-shrink se a queda for real.", file=sys.stderr)
            sys.exit(1)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("# GERADO por etl/dirigentes.py. Não edite à mão.\n")
        yaml.dump(doc, fh, allow_unicode=True, sort_keys=False, width=120)
    print(f"\n{OUT.relative_to(ROOT)}: {len(positions)} cargos, {sum(com_ocupante.values())} com ocupante, "
          f"{len(falhas)} falhas, {dur}s")
    for b in blocos:
        print(f"  {b}: {total[b]} cargos, {com_ocupante[b]} com ocupante")

if __name__ == "__main__":
    main()
