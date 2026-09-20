#!/usr/bin/env python3
"""Segundo escalão dos ministérios → data/generated/segundo-escalao.yaml

Estrutura: SIORG (estrutura completa do Executivo, build/siorg-full-1.json). Para cada ministério e órgão da
Presidência do grafo (subtype ministerio/orgao_presidencia, com siorg_code), seleciona as unidades administrativas de
primeiro nível cujo nome começa com "Secretaria" (Secretaria-Executiva, Secretaria Nacional/Especial/Extraordinária de…).
Ocupantes: páginas "Quem é quem"/"Composição" de cada órgão no gov.br (fonte oficial, precedência) e atos do DOU já
coletados em data/generated/dou.json (nomeação mais recente sem exoneração posterior).

Uso:
  .venv/bin/python etl/segundo_escalao.py                 # completo
  .venv/bin/python etl/segundo_escalao.py --amostra 3     # Fazenda, Saúde, Justiça
  .venv/bin/python etl/segundo_escalao.py --no-web        # só SIORG + DOU
  .venv/bin/python etl/segundo_escalao.py --refresh       # ignora o cache de HTML em build/cache-segundo-escalao/
"""
import sys, json, re, pathlib, unicodedata, urllib.request, urllib.error, urllib.parse, argparse, datetime, time, html, hashlib, statistics
from collections import Counter, defaultdict
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
OUT = ROOT / "data" / "generated" / "segundo-escalao.yaml"
SIORG_FULL_URL = "https://estruturaorganizacional.dados.gov.br/doc/estrutura-organizacional/completa?codigoPoder=1&codigoEsfera=1"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept-Language": "pt-BR,pt;q=0.9", "Accept": "text/html,*/*;q=0.8"}
TODAY = datetime.date.today().isoformat()
AMOSTRA = ["br-ministerio-da-fazenda", "br-ministerio-da-saude", "br-ministerio-da-justica-e-seguranca-publica"]
# caminhos candidatos das páginas de composição, na ordem de preferência
PATHS = ["composicao/quem-e-quem", "acesso-a-informacao/institucional/quem-e-quem", "composicao", "institucional/quem-e-quem",
         "acesso-a-informacao/institucional/quem-e-quem/quem-e-quem", "composicao/quem-e-quem/quem-e-quem"]
ALT_SITES = {"br-secretaria-de-relacoes-institucionais": "https://www.gov.br/sri/"}  # official_url do grafo aponta para site antigo

# ---------------------------------------------------------------- utilidades de texto
def slug(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")

def norm(s):
    """minúsculas, sem acento, sem pontuação; secretário/a → secretaria, executivo/a → executiva (para casar cargo com unidade)."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\((a|o)\)", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    s = re.sub(r"\bsecretari[oa]\b", "secretaria", s)
    s = re.sub(r"\bexecutiv[oa]\b", "executiva", s)
    s = re.sub(r"\bextraordinari[oa]\b", "extraordinaria", s)
    s = re.sub(r"\badjunt[oa]\b", "adjunta", s)
    return re.sub(r"\s+", " ", s)

def code(url): return (url or "").rstrip("/").split("/")[-1]

def clean(t, n=420):
    if not t: return ""
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"^(À|Ao|A|O)\s+.{3,90}?\s+compete[,:]?\s*", "", t)
    if len(t) > n:
        cut = t[:n]; i = max(cut.rfind(". "), cut.rfind("; ")); t = (cut[:i + 1] if i > 120 else cut).rstrip(" ;,") + ("" if cut.endswith(".") else "…")
    return t

def ato_cite(a):
    if not a: return None
    tipo = a.get("tipoAto") or ""; num = a.get("numero") or ""; data = (a.get("dataAssinatura") or a.get("dataPublicacao") or "")
    ano = data[:4] if data else ""
    if not tipo and not num: return None
    return f"{tipo} {num}{('/' + ano) if ano and ano not in num else ''}".strip()

PARTICLES = {"da", "de", "do", "das", "dos", "e", "di", "du", "del", "della", "von", "van", "y", "la", "le"}
def titlecase(s):
    out = []
    for i, t in enumerate(s.split()):
        parts = t.split("-")
        parts = [p.lower() if (p.lower() in PARTICLES and i) else (p[:1].upper() + p[1:].lower()) for p in parts]
        out.append("-".join(parts))
    return " ".join(out)

FEM_EXC = {"luca", "nicola", "josafa", "juca", "jonata", "isaias", "elias", "jeremias", "matias", "tobias", "zacarias", "ezequias", "josias", "messias", "nikita", "sasha", "cuca"}
def is_female(name, cargo_text=""):
    # feminino explícito na página decide; a forma masculina é o padrão genérico das páginas e não decide (prenome decide)
    if re.match(r"^SECRETARIA\b", cargo_text or "") and cargo_text == cargo_text.upper(): return True
    if re.match(r"(?i)^secret[áa]ria\b", cargo_text or ""): return True
    first = norm(name).split()[0] if norm(name) else ""
    return first.endswith("a") and first not in FEM_EXC

# ---------------------------------------------------------------- HTTP com cache em disco
def fetch(url, cache_dir, refresh=False, timeout=60):
    """Devolve (html, url_final) ou (None, motivo). Cache por URL em build/cache-segundo-escalao/."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(url.encode()).hexdigest()[:16]
    f = cache_dir / f"{slug(url.split('gov.br/')[-1])[:80]}-{key}.json"
    if f.exists() and not refresh:
        d = json.load(open(f, encoding="utf-8")); return d.get("html"), d.get("final") or d.get("error")
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
            final = r.geturl(); body = r.read().decode("utf-8", "ignore")
        if "require_login" in final or "credentials_cookie_auth" in final: d = {"html": None, "error": "login"}
        else: d = {"html": body, "final": final}
    except urllib.error.HTTPError as e: d = {"html": None, "error": f"http {e.code}"}
    except Exception as e: d = {"html": None, "error": f"erro {type(e).__name__}"}
    json.dump(d, open(f, "w", encoding="utf-8"), ensure_ascii=False)
    time.sleep(0.4)
    return d.get("html"), d.get("final") or d.get("error")

# ---------------------------------------------------------------- HTML → linhas de texto e links
BLOCK_RX = re.compile(r"(?i)</?(p|div|li|ul|ol|h[1-6]|tr|td|th|table|dl|dt|dd|section|article|header|footer|nav|br|hr|blockquote|figure|figcaption|main)(\s[^>]*)?>")
def content_region(h):
    m = re.search(r'<div id="content-core">(.*?)(<footer|<div id="footer|<div class="footer-wrapper)', h, re.S) or re.search(r'<div id="content-core">(.*)', h, re.S)
    if m: return m.group(1)
    m = re.search(r"<main[^>]*>(.*?)</main>", h, re.S) or re.search(r'<div id="content"[^>]*>(.*?)(<footer|<div id="footer)', h, re.S)
    return m.group(1) if m else h

def to_lines(h):
    body = content_region(h)
    body = re.sub(r"(?is)<(script|style|noscript|svg).*?</\1>", "", body)
    body = BLOCK_RX.sub("\n", body)
    body = re.sub(r"<[^>]+>", " ", body)
    body = unicodedata.normalize("NFC", html.unescape(body)).replace("\xa0", " ").replace("ㅤ", " ").replace("​", " ")
    lines = [re.sub(r"\s+", " ", l).strip(" \t:|·-–—") for l in body.split("\n")]
    return [l for l in lines if l]

def links(h, base):
    """(href, texto) dos links do conteúdo, no mesmo site; inclui abas carregadas por AJAX (data-url/data-id)."""
    out = []; region = content_region(h)
    found = [(m.group(1), m.group(2)) for m in re.finditer(r'<a\s[^>]*href="([^"#]+)"[^>]*>(.*?)</a>', region, re.S | re.I)]
    found += [(m.group(2), m.group(1)) for m in re.finditer(r'data-id="([^"]+)"\s+data-url="([^"]+)"', region)]
    for href, text in found:
        href = html.unescape(href).strip(); text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text))).strip()
        href = urllib.parse.urljoin(base, href)
        if href.startswith(base.split("/pt-br")[0]) and not re.search(r"@@|\.(pdf|jpg|png|doc|xlsx?)(/view)?$|/RSS|/sitemap|mailto:|resolveuid", href, re.I): out.append((href, text))
    return out

# ---------------------------------------------------------------- reconhecimento de nomes e cargos
BAD_NAME = re.compile(r"\b(Secretari|Secret[áa]ri|Minist[ée]ri|Ministr|Departamento|Gabinete|Assessor|Coordena|Diretor|Subsecret|Telefone|E-?mail|Endere[çc]o|Curr[íi]culo|Agenda|CEP|Bloco|Esplanada|Diretoria|Ouvidor|Corregedor|Consultor|Comiss[ãa]o|Conselho|Programa|Chefe|Superintend|Presid|Vago|Cargo|Localiza|Compartilhe|[ÓO]rg[ãa]o|Unidade|Contato|Sala|Andar|Bras[íi]lia|Acesso|Informa[çc]|Composi[çc]|Institucional|Ramal|Adjunt|Substitut|Interin|Servi[çc]o|Setor|Quadra|Edif[íi]cio|Pol[íi]tica|Nacional|Federal|Sistema|Gest[ãa]o|Apoio|Equipe|Organograma|Estrutura|Governo|Rep[úu]blica|Junta|Assist|Escrit[óo]rio|Analista|T[ée]cnic|Gerente|Especial|Secretaria)", re.I)
VAGO_RX = re.compile(r"^\s*(cargo\s+)?vag[oa]\b|pessoa n[ãa]o encontrada|n[ãa]o (h[áa]|consta)|em (nomea[çc][ãa]o|processo)", re.I)
CARGO_RX = re.compile(r"^(secret[áa]ri[oa]s?\b|secretario\b|diretor|coordenador|chefe|assessor|ministr|subsecret|ouvidor|corregedor|consultor|superintendente|subchefe|gerente|analista)", re.I)
SEC_CARGO_RX = re.compile(r"^(secret[áâ]ri[oa]|secretario|SECRET[ÁA]RI[OA])(?![a-z])", re.I)  # "Secretaria" (sem acento, terminado em a) é cabeçalho, não cargo

def clean_name(s):
    s = unicodedata.normalize("NFC", s or "")
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"\b(Ver )?(Curr[íi]cul[oa]m?|Curriculum|Mini curr[íi]culo|CV|Agenda|e-Agendas|Lattes|Ato de nomea[çc][ãa]o|Biografia)\b.*$", "", s, flags=re.I)
    s = re.sub(r"^(Nome|Titular|Ocupante)\s*:\s*", "", s, flags=re.I)
    s = re.sub(r"^((Embaixador|Embaixadora|General|Brigadeiro|Coronel|Contra-Almirante|Vice-Almirante|Almirante|Tenente|Capit[ãa]o|Major|Maj|Brig|Int|Cel|Gen|Ten|Cap|Dr|Dra|Prof|Profa|Sr|Sra|Exmo|Exma)\.?\s+)+", "", s, flags=re.I)
    s = re.sub(r"\s*[-–—|/,(]\s*$", "", s.strip())
    s = re.sub(r"\s+", " ", s).strip(" -–—|/:,.(")
    return s

def is_name(s):
    s = clean_name(s)
    if not s or len(s) > 70 or re.search(r"\d|@|https?://|www\.", s) or BAD_NAME.search(s): return False
    toks = s.split()
    if not 2 <= len(toks) <= 8 or not all(re.fullmatch(r"[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'’`.\-]*", t) for t in toks): return False
    return sum(1 for t in toks if t[0].isupper()) >= 2

def person_name(s):
    s = clean_name(s)
    return titlecase(s) if sum(1 for c in s if c.isupper()) > 0.7 * sum(1 for c in s if c.isalpha()) else s

def is_sec_cargo(line):
    """Secretário/Secretária (com acento) ou "Secretario" = cargo; "Secretaria" (sem acento, terminado em a) = unidade."""
    return re.match(r"^secret[áâ]ri[oa](?![a-z])|^secretario(?![a-z])", line.lower()) is not None

STOP = {"de", "da", "do", "das", "dos", "e", "a", "o", "as", "os", "em", "no", "na", "para", "p", "ao", "aos", "com", "sobre", "secretaria"}
def tokens(s): return [t for t in norm(s).split() if t not in STOP]
def tok_in(t, bag): return any(t == b or (len(t) >= 3 and len(b) >= 3 and (b.startswith(t) or t.startswith(b))) for b in bag)  # "polit" ~ "politicas"

def strip_cargo(cargo):
    """Cargo sem sufixos: "- Código CCE 1.17", "- SPT", "do Ministério da X", "(SDR)", ponto final."""
    c = re.sub(r"\s*[-–—]\s*(c[óo]digo|cce|fce|das|dae|ne)\b.*$", "", cargo, flags=re.I)
    c = re.sub(r"(\s+[-–—]\s*[A-Z]{2,10}(/[A-Z]+)*|\s*\([A-Z]{2,10}\)|-[A-Z]{2,6}(/[A-Z]+)+)\s*$", "", c)  # sigla no fim: " - SPT", "(SDR)", "-SE/SRI/PR"
    c = re.sub(r"(?i)\s+d[aeo]s?\s+(minist[ée]rio|casa civil|secretaria[- ]geral|controladoria|gabinete de seguran[çc]a|secretaria de comunica[çc][ãa]o|secretaria de rela[çc][õo]es)\b.*$", "", c)
    return c.strip(" .;:")

def cargo_unit(cargo, units):
    """Casa um cargo ("Secretário Nacional de X do Ministério…") com uma das unidades; "adjunto" se for adjunto; None se genérico/não casado."""
    c = norm(strip_cargo(cargo))
    if re.search(r"\badjunta\b", c): return "adjunto"
    for u in units:  # exato / prefixo
        un = u["_norm"]
        if c == un or (c.startswith(un + " ") and re.match(r"^(substitut|interin)", c[len(un) + 1:])): return u
    ct = tokens(c)
    if len(ct) < 1: return None
    scored = []
    for u in units:  # tolerante: tokens do cargo contidos (por prefixo) nos da unidade, e vice-versa
        ut = tokens(u["name"])
        if not ut: continue
        a = sum(1 for t in ct if tok_in(t, ut)) / len(ct); b = sum(1 for t in ut if tok_in(t, ct)) / len(ut)
        scored.append((min(a, b), a, u))
    scored.sort(key=lambda x: (-x[0], -x[1]))
    if scored and scored[0][0] >= 0.75 and (len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.2): return scored[0][2]
    return None

def generic_sec(cargo):
    c = norm(strip_cargo(cargo))
    return re.match(r"^secretaria( nacional| especial| executiva| extraordinaria)?( substituta| interina| substituto| interino)?$", c) is not None

def heading_unit(line, units):
    if is_sec_cargo(line): return None
    n = norm(line)
    for u in units:
        un = u["_norm"]
        if n == un or (n.startswith(un) and len(n) - len(un) <= 32 and re.match(r"^\s*(\(|[a-z]{2,10}\s*$|d[aeo]s? |$)", n[len(un):])): return u
    return None

INLINE_RX = re.compile(r"^(.{3,110}?)\s*[-–—:|]\s+(.{3,110})$")
def split_inline(lines):
    """Separa "Cargo - Nome" e "Nome - Cargo" em duas linhas (cargo antes/depois conforme a ordem original)."""
    out = []
    for l in lines:
        m = INLINE_RX.match(l)
        if m and not (is_name(l)):
            a, b = m.group(1).strip(), m.group(2).strip()
            if CARGO_RX.match(a) and not is_name(a) and is_name(b): out += [a, b]; continue
            if CARGO_RX.match(b) and not is_name(b) and is_name(a): out += [a, b]; continue
        out.append(l)
    return out

def extract(lines, units, forced=None):
    """Percorre as linhas da página; devolve {unit_id: {name, cargo, acting}} (primeira pessoa encontrada por unidade)."""
    lines = split_inline(lines)
    # layout da página: nome antes ou depois do cargo (maioria entre todas as linhas de cargo)
    before = after = 0
    for i, l in enumerate(lines):
        if CARGO_RX.match(l) and not is_name(l):
            if i and is_name(lines[i - 1]): before += 1
            if i + 1 < len(lines) and is_name(lines[i + 1]): after += 1
    name_first = before >= after
    found, current, vacant = {}, forced, set()
    for i, l in enumerate(lines):
        # "SECRETARIA DE X" em caixa alta ao lado de um nome é o cargo feminino sem acento (Cultura), não um cabeçalho
        caps_fem = re.match(r"^SECRETARIA\b", l) and l == l.upper() and ((i and is_name(lines[i - 1])) or (i + 1 < len(lines) and is_name(lines[i + 1])))
        hu = None if caps_fem else heading_unit(l, units)
        if hu: current = hu; continue
        if re.match(r"(?i)^(gabinete|assessoria|consultoria|corregedoria|ouvidoria|entidades|[óo]rg[ãa]os|comiss[ãa]o|conselho|subsecretaria|departamento|diretoria)\b", l) and len(l) < 90 and not forced: current = None
        if not is_sec_cargo(l) and not caps_fem: continue
        u = cargo_unit(l, units)
        if u == "adjunto": continue
        if u is None and (generic_sec(l) or forced): u = forced or current  # em subpágina da unidade, o primeiro "Secretári…" sem outro dono é o titular
        if not u or u["id"] in found: continue
        acting = bool(re.search(r"(?i)substitut|interin", l))
        order = (i - 1, i + 1) if name_first else (i + 1, i - 1)
        cand = None
        for j in order:
            if 0 <= j < len(lines):
                if VAGO_RX.search(lines[j]): vacant.add(u["id"]); cand = None; break
                if is_name(lines[j]): cand = lines[j]; break
        if cand: found[u["id"]] = {"name": person_name(cand), "cargo": l, "acting": acting}
    return found

# ---------------------------------------------------------------- por órgão: descoberta das páginas e rastreamento
def site_base(org):
    u = ALT_SITES.get(org["id"]) or org.get("official_url") or ""
    if not u: return None
    if "/pt-br/" in u: return u.rstrip("/") + "/"
    return u.rstrip("/") + "/pt-br/"

HUB_RX = re.compile(r"(?i)quem [ée] quem|quem-e-quem|autoridades|dirigentes|estrutura organizacional|composi[çc][ãa]o|secretarias|organograma|[óo]rg[ãa]os espec[íi]ficos|singulares|assist[êe]ncia direta|principais cargos")

def volto_people(base, units, cache_dir, refresh):
    """Sites gov.br em Volto (Plone 6) renderizam o Quem é quem no cliente; a API plone.restapi lista os itens "Pessoa"
    com o campo cargo e o caminho da área. Devolve {unit_id: person} ou {} se o site não for Volto."""
    site = base.split("/pt-br")[0]; url0 = f"{site}/++api++/@search?portal_type=Pessoa&metadata_fields=cargo&metadata_fields=title&b_size=500"
    people, start = [], 0
    while True:
        h, final = fetch(url0 + (f"&b_start={start}" if start else ""), cache_dir, refresh)
        if not h or not h.lstrip().startswith("{"): break
        try: d = json.loads(h)
        except Exception: break
        items = d.get("items") or []; people += items
        if not items or len(people) >= (d.get("items_total") or 0): break
        start += len(items)
    out = {}
    for it in people:
        cargo = unicodedata.normalize("NFC", (it.get("cargo") or "").strip()); name = clean_name(it.get("title") or "")
        if not cargo or not is_name(name) or not is_sec_cargo(cargo): continue
        u = cargo_unit(cargo, units)
        if u == "adjunto": continue
        if u is None and generic_sec(cargo):  # cargo genérico: a pasta-mãe (área) diz a unidade
            folder = norm((it.get("@id") or "").rstrip("/").split("/")[-2].replace("-", " "))
            u = next((x for x in units if folder == x["_norm"] or folder == norm(x["name"].replace("-", " ")) or (x.get("sigla") and folder == norm(x["sigla"]))), None)
        if not u: continue
        acting = bool(re.search(r"(?i)substitut|interin", cargo))
        if u["id"] not in out or (out[u["id"]]["acting"] and not acting):
            out[u["id"]] = {"name": person_name(name), "cargo": cargo, "acting": acting, "source_url": it.get("@id") or url0}
    return out

def harvest(org, units, cache_dir, refresh, log):
    """Lê as páginas do órgão (hubs de composição e subpáginas por unidade); devolve ({unit_id: person}, [pages_used], erro)."""
    base = site_base(org)
    if not base: return {}, [], "sem official_url"
    todo = {u["id"] for u in units}; res = {}; pages = []; errors = []
    seen = set(); hubs = [base + p for p in PATHS] + [base]; nhub = 0
    for uid, per in volto_people(base, units, cache_dir, refresh).items():
        res[uid] = per; todo.discard(uid); pages.append(per["source_url"])
    while hubs and todo and nhub < 12:
        url = hubs.pop(0)
        if url in seen: continue
        seen.add(url); nhub += 1
        h, final = fetch(url, cache_dir, refresh)
        if not h:
            errors.append(f"{url.replace(base, '')}: {final}"); continue
        if final in seen and final != url: continue
        seen.add(final)
        got = extract(to_lines(h), units)
        for uid, per in got.items():
            if uid in todo: res[uid] = dict(per, source_url=final); todo.discard(uid)
        if got: pages.append(final)
        lk = links(h, final)
        # outros hubs ("Quem é quem", "Composição", "Estrutura organizacional") ligados desta página
        for href, text in lk:
            if HUB_RX.search(text) and href not in seen and href not in hubs and not re.search(r"(?i)agenda|superintend|regional", text): hubs.append(href)
        # subpáginas por unidade (hubs que só listam as unidades com link)
        for u in units:
            if u["id"] not in todo: continue
            un, us = u["_norm"], slug(u["name"])
            cands = []
            for href, text in lk:
                tn = norm(text); hs = href.rstrip("/").split("/")[-1]
                if tn == un or (tn.startswith(un) and len(tn) - len(un) <= 32) or hs == us or hs.startswith(us + "-") or hs == slug(u["name"].replace("-", " ")) \
                   or (u.get("sigla") and len(u["sigla"]) >= 3 and re.fullmatch(rf"(secretaria-)?{re.escape(slug(u['sigla']))}(-\d+)?", hs)):
                    if href not in seen and href != final and href not in cands: cands.append(href)
            for href in cands[:3]:
                if u["id"] not in todo: break
                sh, sfinal = fetch(href, cache_dir, refresh)
                seen.add(href)
                if not sh: continue
                seen.add(sfinal)
                sub = extract(to_lines(sh), units, forced=u)
                for uid, per in sub.items():
                    if uid in todo: res[uid] = dict(per, source_url=sfinal); todo.discard(uid); pages.append(sfinal)
                if u["id"] in todo:  # 2º nível: "Quem é quem", Gabinete, abas e páginas com o nome da unidade dentro da subpágina
                    deeper = [h2 for h2, t2 in links(sh, sfinal) if h2 not in seen and h2.startswith(sfinal.rstrip("/") + "/")
                              and (HUB_RX.search(t2) or re.search(r"(?i)gabinete|staff|titular|equipe|dirigente", t2) or norm(t2).startswith(un))]
                    for h2 in deeper[:4]:
                        if u["id"] not in todo: break
                        s2, f2 = fetch(h2, cache_dir, refresh); seen.add(h2)
                        if not s2: continue
                        seen.add(f2)
                        for uid, per in extract(to_lines(s2), units, forced=u).items():
                            if uid in todo: res[uid] = dict(per, source_url=f2); todo.discard(uid); pages.append(f2)
    err = None if pages or not errors else "; ".join(errors[:3])
    log(f"  {org['id']}: {len(res)}/{len(units)} ocupantes nas páginas oficiais" + (f" ({err})" if err else ""))
    return res, pages, err

# ---------------------------------------------------------------- DOU
def dou_occupants(orgs_units, dou_path):
    """{unit_id: person} a partir dos atos do DOU: nomeação/designação mais recente sem exoneração/dispensa posterior."""
    if not dou_path.exists(): return {}
    d = json.load(open(dou_path, encoding="utf-8"))
    recs = []
    for a in (d.get("acts") or {}).values():
        for r in a.get("records") or []:
            if r.get("cargo") and r.get("name"): recs.append(dict(r, date=a.get("date") or "", url=a.get("url"), hier=" ".join(a.get("hierarchy") or [])))
    recs.sort(key=lambda r: r["date"])
    out = {}
    for org, units in orgs_units:
        on = norm(org["name"]); aliases = [norm(a) for a in org.get("aliases") or [] if len(a) > 4]
        for r in recs:
            u = cargo_unit(r["cargo"], units)
            if not u or u == "adjunto": continue
            ctx = norm(r["cargo"]) + " " + norm(r.get("org_text") or "") + " " + norm(r["hier"])
            if on not in ctx and not any(a in ctx for a in aliases): continue
            if r["verb"] in ("NOMEAR", "DESIGNAR"):
                out[u["id"]] = {"name": r["name"], "cargo": r["cargo"], "started_at": r["date"], "source_url": r["url"], "acting": bool(re.search(r"(?i)substitut|interin", r["cargo"]))}
            elif r["verb"] in ("EXONERAR", "DISPENSAR") and u["id"] in out and norm(out[u["id"]]["name"]) == norm(r["name"]):
                del out[u["id"]]
    return out

# ---------------------------------------------------------------- nomes de cargo
def cargo_title(unit_name, female):
    t = unit_name.strip()
    t = re.sub(r"^Secretaria", "Secretária" if female else "Secretário", t)
    t = re.sub(r"^(Secretári[oa])-Executiva", r"\1-Executivo" if not female else r"\1-Executiva", t)
    t = re.sub(r"^(Secretári[oa]) Extraordinária", r"\1 Extraordinário" if not female else r"\1 Extraordinária", t)
    return t

def art(org_name):
    return "da" if re.match(r"^(Casa|Secretaria|Controladoria|Advocacia|Agência)", org_name) else "do"

# ---------------------------------------------------------------- principal
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--amostra", type=int, default=0, help="só os N primeiros órgãos da lista de amostra (Fazenda, Saúde, Justiça, …)")
    ap.add_argument("--cache", default=str(BUILD), help="diretório com siorg-full-1.json e siorg-oe-1.json")
    ap.add_argument("--no-web", action="store_true", help="não lê as páginas gov.br (só SIORG + DOU)")
    ap.add_argument("--refresh", action="store_true", help="ignora o cache de HTML")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    t0 = time.time()
    log = lambda *a: print(*a, file=sys.stderr, flush=True)

    graph = json.load(open(BUILD / "graph.br.json", encoding="utf-8"))
    nodes = graph["nodes"]
    orgs = [n for n in nodes.values() if n.get("subtype") in ("ministerio", "orgao_presidencia") and n.get("siorg_code")]
    orgs.sort(key=lambda n: (n["subtype"] != "ministerio", n["id"]))
    if args.amostra:
        pri = [nodes[i] for i in AMOSTRA if i in nodes] + [n for n in orgs if n["id"] not in AMOSTRA]
        orgs = pri[:args.amostra]

    cache = pathlib.Path(args.cache)
    full_p = cache / "siorg-full-1.json"
    if not full_p.exists():
        log("baixando estrutura completa do SIORG (227 MB)…")
        with urllib.request.urlopen(urllib.request.Request(SIORG_FULL_URL, headers=UA), timeout=1800) as r: full_p.write_bytes(r.read())
    full = json.load(open(full_p, encoding="utf-8"))
    by_parent = defaultdict(list)
    for u in full.get("unidades") or []: by_parent[code(u.get("codigoUnidadePai"))].append(u)
    generated_at = (full.get("servico") or {}).get("data")

    # unidades de primeiro nível "Secretaria…" por órgão
    orgs_units = []
    for o in orgs:
        us = []
        for u in by_parent.get(str(o["siorg_code"]), []):
            nm = re.sub(r"\s+", " ", u["nome"]).strip()
            if code(u["codigoTipoUnidade"]) != "unidade-administrativa" or not nm.startswith("Secretaria"): continue
            if re.match(r"^Secretaria-Executiva\s+d[aeo]", nm): continue  # secretarias-executivas de conselhos/comissões
            us.append({"id": None, "name": nm, "sigla": (u.get("sigla") or "").strip() or None, "code": int(code(u["codigoUnidade"])), "_norm": norm(nm), "raw": u})
        us.sort(key=lambda x: (not x["name"].startswith("Secretaria-Executiva"), x["name"]))
        orgs_units.append((o, us))

    # ids: br-<slug do nome>; nomes repetidos entre órgãos (Secretaria-Executiva) ganham o apelido curto do órgão;
    # colisão com nó já existente no grafo ganha "-sec" (e fica listada em resumo.ja_no_grafo)
    existing = set(nodes)
    name_count = Counter(slug(u["name"]) for _, us in orgs_units for u in us)
    used = set(); ja_no_grafo = []
    for o, us in orgs_units:
        short = slug((o.get("aliases") or [o["name"]])[-1] if len(o.get("aliases") or []) > 1 else (o.get("aliases") or [o["name"]])[0])
        for u in us:
            i = "br-" + slug(u["name"])
            if name_count[slug(u["name"])] > 1: i += "-" + short
            if i in existing:
                ex = nodes[i]
                if ex.get("parent") == o["id"]: ja_no_grafo.append({"unidade": u["name"], "orgao": o["id"], "no_existente": i})
                i += "-sec"
            elif u["sigla"]:
                dup = next((n for n in nodes.values() if n.get("parent") == o["id"] and u["sigla"] in (n.get("aliases") or [])), None)
                if dup: ja_no_grafo.append({"unidade": u["name"], "orgao": o["id"], "no_existente": dup["id"]})
            if i in used: i = f"{i}-{u['code']}"
            used.add(i); u["id"] = i

    # ocupantes
    dou = dou_occupants(orgs_units, ROOT / "data" / "generated" / "dou.json")
    web = {}; pages_by_org = {}; unreadable = []
    if not args.no_web:
        cdir = BUILD / "cache-segundo-escalao"
        for o, us in orgs_units:
            if not us: continue
            res, pages, err = harvest(o, us, cdir, args.refresh, log)
            web.update(res); pages_by_org[o["id"]] = pages
            if not pages: unreadable.append({"orgao": o["id"], "motivo": err or "páginas lidas, mas sem nomes reconhecíveis"})

    out_nodes, out_pos = [], []
    stats = Counter(); per_org = {}
    for o, us in orgs_units:
        per_org[o["id"]] = len(us)
        for u in us:
            raw = u["raw"]; c = u["code"]
            desc = clean(raw.get("competencia") or raw.get("finalidade") or "")
            if len(desc) < 40: desc = f"{u['name']} do {o['name']}: unidade de primeiro nível da estrutura do órgão, subordinada diretamente ao ministro. Competência não detalhada no SIORG."
            n = {"id": u["id"], "type": "department", "sector": "executivo", "ring": 3, "parent": o["id"], "cluster": "secretaria", "source": "siorg",
                 "siorg_code": c, "name": u["name"], "aliases": [u["sigla"]] if u["sigla"] else [], "description": desc,
                 "cite": ato_cite(raw.get("atoNormativo")) or "Lei 14.600/2023; decreto de estrutura do ministério",
                 "cite_url": f"https://estruturaorganizacional.dados.gov.br/id/unidade-organizacional/{c}",
                 "official_url": (web.get(u["id"]) or {}).get("source_url") or (pages_by_org.get(o["id"]) or [o.get("official_url")])[0], "verified": False}
            out_nodes.append(n)
            per = web.get(u["id"]); src = "oficial" if per else ("dou" if u["id"] in dou else None)
            if not per and src == "dou": per = dou[u["id"]]
            female = is_female(per["name"], per.get("cargo", "")) if per else False
            title = f"{cargo_title(u['name'], female)} {art(o['name'])} {o['name']}"
            people = []
            if per:
                people.append({"id": "br-p-" + slug(per["name"]), "name": per["name"], "started_at": per.get("started_at"), "entry_mode": "nomeado", "acting": bool(per.get("acting")),
                               "source": src, "source_url": per.get("source_url"), "checked_at": TODAY, "verified": False,
                               "note": ("substituto(a)/interino(a) segundo a página oficial; " if per.get("acting") else "") + (f"página Quem é quem do órgão; cargo na página: {per.get('cargo')}" if src == "oficial" else f"ato de nomeação no DOU em {per.get('started_at')}")})
                stats[src] += 1
            else: stats["sem"] += 1
            out_pos.append({"id": f"{u['id']}-secretario", "type": "dept_head", "head_of": u["id"], "name": title, "nomeado_por": "br-presidente-da-republica", "seats": 1,
                            "cite": "Lei 14.600/2023; Decreto 9.727/2019 (critérios para cargos em comissão)",
                            "cite_url": "https://www.planalto.gov.br/ccivil_03/_ato2019-2022/2019/decreto/D9727.htm",
                            "description": f"Dirige a {u['name']} do {o['name']}, unidade de primeiro nível abaixo do ministro. Cargo comissionado de livre nomeação e exoneração, provido pelo Presidente da República por indicação do ministro.",
                            "people": people})

    counts = [v for v in per_org.values() if v]
    resumo = {"ministerios_cobertos": sum(1 for v in per_org.values() if v), "orgaos_sem_secretaria": [k for k, v in per_org.items() if not v], "secretarias": len(out_nodes),
              "com_ocupante": {"oficial": stats["oficial"], "dou": stats["dou"]}, "sem_ocupante": stats["sem"],
              "mediana_secretarias_por_ministerio": statistics.median(counts) if counts else 0, "por_ministerio": per_org,
              "paginas_nao_lidas": unreadable, "ja_no_grafo": ja_no_grafo, "duracao_s": round(time.time() - t0)}
    out = {"generated_from": "SIORG estrutura completa + páginas Quem é quem (gov.br) + DOU (data/generated/dou.json)", "generated_at": TODAY, "siorg_versao": generated_at,
           "resumo": resumo, "nodes": out_nodes, "positions": out_pos}
    pathlib.Path(args.out).write_text("# GERADO por etl/segundo_escalao.py. Não edite à mão.\n" + yaml.dump(out, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    print(f"órgãos: {resumo['ministerios_cobertos']}  secretarias: {len(out_nodes)}  ocupantes oficial: {stats['oficial']}  dou: {stats['dou']}  sem: {stats['sem']}  "
          f"mediana/órgão: {resumo['mediana_secretarias_por_ministerio']}  páginas não lidas: {len(unreadable)}  {resumo['duracao_s']}s")

if __name__ == "__main__": main()
