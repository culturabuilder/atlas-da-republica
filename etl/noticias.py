#!/usr/bin/env python3
"""Feeds RSS → data/generated/noticias.json (acumula entre execuções) com entidades e pessoas linkadas.

Mesmo mecanismo do CivLab: cada resumo recebe marcações <gov_entities='id'>texto</gov_entities>; o power map
conta menções por pessoa nos últimos 90 dias. Sem chave.
Uso: .venv/bin/python etl/noticias.py
"""
import json, re, sys, pathlib, hashlib, datetime, html, unicodedata, urllib.request, email.utils
import xml.etree.ElementTree as ET
ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "generated" / "noticias.json"
FEEDS = [
    ("Agência Brasil", "https://agenciabrasil.ebc.com.br/rss/politica/feed.xml"),
    ("Agência Senado", "https://www12.senado.leg.br/noticias/rss"),
    ("g1 Política", "https://g1.globo.com/rss/g1/politica/"),
    ("Poder360", "https://www.poder360.com.br/feed/"),
    ("Congresso em Foco", "https://congressoemfoco.uol.com.br/feed/"),
    ("JOTA", "https://www.jota.info/feed"),
    ("Estadão", "https://www.estadao.com.br/arc/outboundfeeds/rss/?outputType=xml"),
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

def build_matchers(graph):
    """Lista de (regex, id, tipo) por nome/alias de órgão e por nome de pessoa."""
    ms = []
    for n in graph["nodes"].values():
        if n["type"] == "dept_head":
            for p in n.get("people") or []:
                nm = p.get("name") or ""
                if len(nm.split()) >= 2: ms.append((re.compile(r"\b" + re.escape(norm(nm)) + r"\b"), p["id"], "person", n["id"], nm))
            continue
        names = [n["name"]] + list(n.get("aliases") or [])
        for a in names:
            a2 = norm(a)
            if len(a2) < 3 or a2 in STOP_ALIASES: continue
            is_sigla = a.isupper() and len(a2) <= 8
            multiword = len(a2.split()) >= 2 and len(a2) >= 12
            if not (is_sigla or multiword): continue  # "Presidente", "Justiça", "Fazenda" sozinhos são genéricos demais
            ms.append((re.compile(r"\b" + re.escape(a2) + r"\b"), n["id"], "entity", None, a))
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

def main():
    graph = json.load(open(ROOT / "build" / "graph.br.json", encoding="utf-8"))
    matchers = build_matchers(graph)
    store = json.load(open(OUT, encoding="utf-8")) if OUT.exists() else {"articles": {}}
    new = 0
    for pub, url in FEEDS:
        for it in parse(fetch(url)):
            aid = hashlib.sha1(it["url"].encode()).hexdigest()[:16]
            if aid in store["articles"]: continue
            ents, people = link(it["title"] + " " + it["summary"], matchers)
            store["articles"][aid] = {"id": aid, "publication": pub, "title": it["title"], "url": it["url"], "summary": it["summary"],
                                      "date": it["date"] or datetime.date.today().isoformat(), "fetched_at": datetime.date.today().isoformat(),
                                      "entities": ents, "people": people}
            new += 1
    # retém 180 dias
    cutoff = (datetime.date.today() - datetime.timedelta(days=180)).isoformat()
    store["articles"] = {k: v for k, v in store["articles"].items() if (v.get("date") or "") >= cutoff}
    store["updated_at"] = datetime.date.today().isoformat(); store["feeds"] = [p for p, _ in FEEDS]
    json.dump(store, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    arts = store["articles"].values()
    linked = sum(1 for a in arts if a["entities"] or a["people"])
    print(f"novos={new} total={len(store['articles'])} com entidade/pessoa={linked}")
    from collections import Counter
    print("entidades mais citadas:", Counter(e for a in arts for e in a["entities"]).most_common(8))
    print("pessoas mais citadas:", Counter(p["name"] for a in arts for p in a["people"]).most_common(8))

if __name__ == "__main__": main()
