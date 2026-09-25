#!/usr/bin/env python3
"""Feeds RSS → data/generated/noticias.json (acumula entre execuções) com entidades e pessoas linkadas.

Mesmo mecanismo do CivLab: cada resumo recebe marcações <gov_entities='id'>texto</gov_entities>; o power map
conta menções por pessoa nos últimos 90 dias. Sem chave.

Porteiro de relevância: cerca de 45% do que chega pelos feeds não é sobre o governo federal (esporte,
receita, consumo, política estadual). Com EIKOS_KEY no ambiente ou no .env, cada artigo NOVO recebe três
campos — `gov` (bool), `gov_p` (probabilidade de ser do governo federal, 3 casas) e `gov_conf` (confiança,
3 casas). O veredito nunca é recalculado: o custo é por artigo e a resposta não muda. Sem chave, ou se o
Eikos falhar, o artigo simplesmente fica sem os campos e o resto do conector segue igual.

Uso:
  .venv/bin/python etl/noticias.py                     # busca os feeds e classifica os novos
  .venv/bin/python etl/noticias.py --relink            # refaz as ligações de entidade/pessoa
  .venv/bin/python etl/noticias.py --porteiro-acervo   # classifica os antigos que ainda não têm veredito
"""
import json, os, re, sys, pathlib, hashlib, datetime, html, unicodedata, urllib.request, email.utils
import xml.etree.ElementTree as ET
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import eikos
ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "generated" / "noticias.json"
# passada completa do porteiro já paga (mapa id -> {gov, p, conf, tok}); serve de carga inicial em --porteiro-acervo
SEED_PORTEIRO = pathlib.Path(os.environ.get("PORTEIRO_SEED",
    "/private/tmp/claude-501/-Users-culto-govnew/cbdbacff-6e4d-44b6-b805-449b42969f6f/scratchpad/eikos/relevancia.json"))
FEEDS = [
    ("Agência Brasil", "https://agenciabrasil.ebc.com.br/rss/politica/feed.xml"),
    ("Agência Senado", "https://www12.senado.leg.br/noticias/rss"),
    ("g1 Política", "https://g1.globo.com/rss/g1/politica/"),
    ("Poder360", "https://www.poder360.com.br/feed/"),
    ("Congresso em Foco", "https://congressoemfoco.uol.com.br/feed/"),
    ("JOTA", "https://www.jota.info/feed"),
    # o feed geral do Estadão trazia receita, futebol e oferta de celular: 376 artigos, 14% com alguma ligação.
    ("Estadão", "https://www.estadao.com.br/arc/outboundfeeds/feeds/rss/sections/politica/?outputType=xml"),
    ("Planalto", "https://www.gov.br/planalto/pt-br/acompanhe-o-planalto/noticias/RSS"),
]
UA = {"User-Agent": "Mozilla/5.0 atlas-da-republica/0.1"}
STOP_ALIASES = {"pr", "ms", "mt", "md", "mf", "sg", "cc", "bb", "ec", "cd", "sf", "mp", "pf", "sri", "ana", "ans", "cmb", "cns", "cne", "ebc", "mir", "mpa", "mps", "mte", "mda", "mds", "cgu"}  # siglas curtas/ambíguas exigem contexto

def norm(s): return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
def strip_html(t): return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t or ""))).strip()

def fetch(url):
    try:
        r = urllib.request.Request(url, headers=UA)
        return urllib.request.urlopen(r, timeout=40).read()
    except Exception as e:
        print("feed falhou:", url, e, file=sys.stderr); return b""

def parse(xml_bytes):
    items = []
    try: root = ET.fromstring(xml_bytes)
    except ET.ParseError: return items
    ns = {"atom": "http://www.w3.org/2005/Atom", "content": "http://purl.org/rss/1.0/modules/content/", "dc": "http://purl.org/dc/elements/1.1/"}
    for it in root.iter("item"):
        g = lambda tag: (it.findtext(tag) or "").strip()
        date = g("pubDate") or g("dc:date", ) or (it.find("dc:date", ns).text if it.find("dc:date", ns) is not None else "")
        try: dt = email.utils.parsedate_to_datetime(date).date().isoformat() if date and "," in date else (date[:10] if date else None)
        except Exception: dt = date[:10] if date else None
        items.append({"title": strip_html(g("title")), "url": g("link") or (it.find("guid").text if it.find("guid") is not None else ""),
                      "summary": strip_html(g("description"))[:600], "date": dt})
    for e in root.iter("{http://www.w3.org/2005/Atom}entry"):
        t = e.find("atom:title", ns); l = e.find("atom:link", ns); s = e.find("atom:summary", ns) or e.find("atom:content", ns); d = e.find("atom:published", ns) or e.find("atom:updated", ns)
        items.append({"title": strip_html(t.text if t is not None else ""), "url": (l.get("href") if l is not None else ""), "summary": strip_html(s.text if s is not None else "")[:600], "date": (d.text[:10] if d is not None and d.text else None)})
    return [i for i in items if i["title"] and i["url"]]

COMMON = set("silva santos oliveira souza sousa lima pereira costa rodrigues almeida nascimento ferreira araujo carvalho gomes martins rocha ribeiro alves monteiro mendes barros freitas barbosa pinto moura cavalcanti dias castro campos cardoso correia cunha teixeira nunes moreira lopes vieira fernandes andrade ramos machado batista medeiros melo marques reis duarte farias nogueira borges rezende xavier guimaraes jesus torres sales azevedo neto filho junior gomes lacerda amaral leal pires ferraz gonçalves goncalves maciel".split())
def person_forms(nm, apelidos):
    """Formas pelas quais um nome pode aparecer: nome completo, primeiro+último, apelidos curados e sobrenome raro."""
    forms = set()
    w = [x for x in nm.split() if x.lower() not in ("de", "da", "do", "das", "dos", "e")]
    if len(w) >= 2:
        forms.add(nm); forms.add(w[0] + " " + w[-1])
        if len(w) >= 3: forms.add(w[0] + " " + w[1]); forms.add(w[-2] + " " + w[-1])
        # sobrenome sozinho só via apelidos curados: "Federal", "Flávio" e afins geram falsos positivos
    for a in apelidos.get(nm, []) or []: forms.add(a)
    return [f for f in forms if len(norm(f)) >= 4]

def build_matchers(graph):
    """Lista de (regex, id, tipo) por nome/alias de órgão e por nome de pessoa."""
    import yaml
    ap_path = ROOT / "data" / "apelidos.yaml"
    apelidos = yaml.safe_load(open(ap_path, encoding="utf-8")) if ap_path.exists() else {}
    ms = []
    seen_forms = {}
    for n in graph["nodes"].values():
        if n["type"] in ("dept_head", "elected"):
            for p in n.get("people") or []:
                nm = p.get("name") or ""
                if len(nm.split()) < 2: continue
                for f in person_forms(nm, apelidos):
                    key = norm(f)
                    if key in seen_forms and seen_forms[key] != p["id"]: seen_forms[key] = None; continue  # forma ambígua entre pessoas: descarta
                    seen_forms[key] = p["id"]
                    ms.append((re.compile(r"\b" + re.escape(key) + r"\b"), p["id"], "person", n["id"], nm, key))
            if n["type"] == "dept_head": continue
        names = [n["name"]] + list(n.get("aliases") or [])
        for a in names:
            a2 = norm(a)
            if len(a2) < 3 or a2 in STOP_ALIASES: continue
            is_sigla = a.isupper() and len(a2) <= 8
            multiword = len(a2.split()) >= 2 and len(a2) >= 12
            if not (is_sigla or multiword): continue  # "Presidente", "Justiça", "Fazenda" sozinhos são genéricos demais
            ms.append((re.compile(r"\b" + re.escape(a2) + r"\b"), n["id"], "entity", None, a))
    ms = [m for m in ms if len(m) < 6 or seen_forms.get(m[5]) == m[1]]
    ms = [m[:5] for m in ms]
    # nomes mais longos primeiro para evitar que "Senado" capture antes de "Senado Federal"
    ms.sort(key=lambda m: -len(m[4]))
    return ms

def link(text, matchers):
    t = norm(text); ents, people = [], []
    for rx, nid, kind, pos, label in matchers:
        if rx.search(t):
            if kind == "entity" and nid not in ents: ents.append(nid)
            if kind == "person" and nid not in [p["id"] for p in people]: people.append({"id": nid, "position": pos, "name": label})
    return ents[:8], people[:8]

# --- porteiro de relevância (Eikos) -----------------------------------------------------------
# Estado e pergunta medidos em 24/09/2026 sobre 60 notícias com gabarito: 97% de cobertura, 87% de precisão.
PORTEIRO_Q = {"governo": {"type": "boolean",
     "instructions": "Esta notícia trata do governo federal brasileiro: seus órgãos, cargos, quem os ocupa, suas decisões, seu orçamento ou as eleições federais?",
     "criteria": {"true": "trata do governo federal brasileiro, do Congresso Nacional, do Judiciário federal, de órgão ou autoridade federal, ou das eleições federais",
                  "false": "trata de outro assunto: esporte, entretenimento, receita, consumo, tecnologia, crime comum, governo estrangeiro, política estadual ou municipal"}}}

def porteiro_estado(a):
    return f"Fonte: {a['publication']}. Data: {a.get('date','')}.\nTítulo: {a.get('title','')}\nResumo: {(a.get('summary') or '').strip()}"[:900]

def porteiro(a):
    """Pergunta ao Eikos e grava gov/gov_p/gov_conf no artigo. Sem chave ou com erro, não grava nada."""
    r = eikos.avaliar(porteiro_estado(a), PORTEIRO_Q)
    v = (r or {}).get("governo")
    if not v or v.get("value") is None: return False
    a["gov"] = bool(v.get("value"))
    a["gov_p"] = round(float(v.get("probability") or 0), 3)
    a["gov_conf"] = round(float(v.get("confidence") or 0), 3)
    return True

def carga_inicial(artigos):
    """Aproveita a passada completa já paga, se o arquivo existir. Devolve quantos vereditos entraram."""
    if not SEED_PORTEIRO.exists(): return 0
    try: seed = json.load(open(SEED_PORTEIRO, encoding="utf-8"))
    except Exception as e:
        print("carga inicial do porteiro falhou:", e, file=sys.stderr); return 0
    n = 0
    for aid, a in artigos.items():
        s = seed.get(aid)
        if not s or "gov" in a or s.get("gov") is None: continue
        a["gov"] = bool(s["gov"]); a["gov_p"] = round(float(s.get("p") or 0), 3); a["gov_conf"] = round(float(s.get("conf") or 0), 3)
        n += 1
    return n


def main():
    graph = json.load(open(ROOT / "build" / "graph.br.json", encoding="utf-8"))
    matchers = build_matchers(graph)
    store = json.load(open(OUT, encoding="utf-8")) if OUT.exists() else {"articles": {}}
    if "--relink" in sys.argv:
        for a in store["articles"].values():
            a["entities"], a["people"] = link(a["title"] + " " + a.get("summary", ""), matchers)
    new = 0; novos = []
    for pub, url in FEEDS:
        for it in parse(fetch(url)):
            aid = hashlib.sha1(it["url"].encode()).hexdigest()[:16]
            if aid in store["articles"]: continue
            ents, people = link(it["title"] + " " + it["summary"], matchers)
            store["articles"][aid] = {"id": aid, "publication": pub, "title": it["title"], "url": it["url"], "summary": it["summary"],
                                      "date": it["date"] or datetime.date.today().isoformat(), "fetched_at": datetime.date.today().isoformat(),
                                      "entities": ents, "people": people}
            new += 1; novos.append(aid)
    # retém 180 dias
    cutoff = (datetime.date.today() - datetime.timedelta(days=180)).isoformat()
    store["articles"] = {k: v for k, v in store["articles"].items() if (v.get("date") or "") >= cutoff}

    # porteiro: só os artigos sem veredito. O normal cobre os novos; --porteiro-acervo cobre o resto.
    acervo = "--porteiro-acervo" in sys.argv
    do_seed = carga_inicial(store["articles"]) if acervo else 0
    alvos = [k for k in (store["articles"] if acervo else novos) if k in store["articles"] and "gov" not in store["articles"][k]]
    feitos = falhas = 0
    if alvos and eikos.disponivel():
        for i, aid in enumerate(alvos, 1):
            if porteiro(store["articles"][aid]): feitos += 1
            else:
                falhas += 1
                if falhas >= 5 and feitos == 0: print("porteiro: 5 falhas seguidas, desistindo desta execução", file=sys.stderr); break
            if acervo and i % 50 == 0: print(f"  porteiro {i}/{len(alvos)}…", file=sys.stderr)
    elif alvos:
        print("porteiro: sem EIKOS_KEY, artigos seguem sem veredito de relevância", file=sys.stderr)

    store["updated_at"] = datetime.date.today().isoformat(); store["feeds"] = [p for p, _ in FEEDS]
    json.dump(store, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    arts = store["articles"].values()
    linked = sum(1 for a in arts if a["entities"] or a["people"])
    print(f"novos={new} total={len(store['articles'])} com entidade/pessoa={linked}")
    entraram = sum(1 for a in arts if a.get("gov") is True)
    barrados = sum(1 for a in arts if a.get("gov") is False)
    baixa = sum(1 for a in arts if a.get("gov") is not None and a.get("gov_conf", 0) < eikos.CORTE_CONFIANCA)
    g = eikos.gasto()
    print(f"porteiro: entraram={entraram} barrados={barrados} sem veredito={len(store['articles']) - entraram - barrados}"
          f" · classificados agora={feitos}" + (f" (+{do_seed} da carga inicial)" if do_seed else "")
          + (f" · falhas={falhas}" if falhas else "")
          + f" · abaixo do corte de {eikos.CORTE_CONFIANCA:.2f} (revisão humana)={baixa}")
    print(f"gasto Eikos: {g['chamadas']} chamadas, {g['tokens']} tokens de entrada, {g['erros']} erros")
    from collections import Counter
    print("entidades mais citadas:", Counter(e for a in arts for e in a["entities"]).most_common(8))
    print("pessoas mais citadas:", Counter(p["name"] for a in arts for p in a["people"]).most_common(8))

if __name__ == "__main__": main()
