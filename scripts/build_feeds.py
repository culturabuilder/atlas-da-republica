#!/usr/bin/env python3
"""Feeds RSS 2.0 do Atlas da República: mudanças, prazos, temas e notícias.

Chamado por scripts/build_site.py: build(site_dir, prefix, base, G) -> lista de URLs geradas.
Também roda sozinho para teste: .venv/bin/python scripts/build_feeds.py
"""
import json, pathlib, hashlib, datetime, email.utils
from xml.sax.saxutils import escape

ROOT = pathlib.Path(__file__).resolve().parent.parent
TZ = datetime.timezone(datetime.timedelta(hours=-3))  # Brasília
KIND = {"sabatina": "sabatina aprovada", "posse": "posse", "nomeacao": "nomeação", "exoneracao": "exoneração", "designacao": "designação", "entrada": "entrada", "saida": "saída", "vacancia": "vacância"}
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
STATE = {"parado": "parado", "prazo_vencido": "prazo vencido", "encerrado": "encerrado", "andando": "em andamento", "silencio": "silêncio", "ativo": "ativo"}


def rfc822(d, hour=12):
    """YYYY-MM-DD (ou ISO com hora) -> data RFC 822 em horário de Brasília. Datas inválidas viram agora."""
    try:
        if isinstance(d, str) and len(d) >= 10:
            dt = datetime.datetime.fromisoformat(d[:19]) if len(d) > 10 else datetime.datetime.fromisoformat(d[:10]).replace(hour=hour)
        elif isinstance(d, datetime.datetime): dt = d
        else: raise ValueError
    except ValueError:
        dt = datetime.datetime.now()
    if dt.tzinfo is None: dt = dt.replace(tzinfo=TZ)
    return email.utils.format_datetime(dt)


def fmt_date(d):
    try:
        y, m, dd = d[:10].split("-"); return f"{int(dd)} {MESES[int(m) - 1]} {y}"
    except Exception: return d or ""


def brl(v):
    try: v = float(v)
    except (TypeError, ValueError): return ""
    if v >= 1e9: return f"R$ {v / 1e9:.1f} bi".replace(".", ",")
    if v >= 1e6: return f"R$ {v / 1e6:.1f} mi".replace(".", ",")
    return "R$ " + f"{v:,.0f}".replace(",", ".")


def guid(*parts):
    return "tag:atlasdarepublica.org,2026:" + hashlib.sha1("|".join(str(p or "") for p in parts).encode("utf-8")).hexdigest()[:20]


def item(title, link, gid, date, desc, extra=""):
    return (f"<item>\n<title>{escape(title)}</title>\n<link>{escape(link)}</link>\n<guid isPermaLink=\"false\">{escape(gid)}</guid>\n"
            f"<pubDate>{rfc822(date)}</pubDate>\n<description>{escape(desc)}</description>\n{extra}</item>\n")


def channel(title, self_url, site_link, desc, items, build_date):
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n<channel>\n'
            f"<title>{escape(title)}</title>\n<link>{escape(site_link)}</link>\n<description>{escape(desc)}</description>\n<language>pt-BR</language>\n"
            f'<atom:link href="{escape(self_url)}" rel="self" type="application/rss+xml"/>\n'
            f"<lastBuildDate>{rfc822(build_date)}</lastBuildDate>\n<generator>Atlas da República</generator>\n<ttl>360</ttl>\n"
            + "".join(items) + "</channel>\n</rss>\n")


def feed_mudancas(G, base):
    items = []
    changes = sorted(G.get("changes") or [], key=lambda c: c.get("date") or "", reverse=True)[:100]
    for c in changes:
        kind = KIND.get(c.get("kind"), c.get("kind") or "mudança")
        who = c.get("personName") or "(vago)"; pos = c.get("positionName") or c.get("positionId") or ""
        title = f"{who} · {kind} · {pos}" + (" (interino)" if c.get("acting") else "")
        desc = f"{who}: {kind} em {pos}, {fmt_date(c.get('date'))}."
        if c.get("votes") and c["votes"][0] is not None: desc += f" Votação: {c['votes'][0]} a {c['votes'][1]}."
        if c.get("sourceUrl"): desc += f" Fonte: {c['sourceUrl']}"
        link = f"{base}/#{c.get('positionId') or ''}"
        extra = f'<source url="{escape(c["sourceUrl"])}">Fonte oficial</source>\n' if c.get("sourceUrl") else ""
        items.append(item(title, link, guid("mudanca", c.get("kind"), c.get("date"), c.get("positionId"), c.get("personName")), c.get("date"), desc, extra))
    return items


def feed_prazos(G, base):
    om = G.get("omissao") or {}; items = []
    for m in om.get("mpvs") or []:
        dl = m.get("days_left")
        if dl is None or dl > 30: continue
        falta = f"faltam {dl} dias" if dl > 1 else ("falta 1 dia" if dl == 1 else ("vence hoje" if dl == 0 else f"vencida há {-dl} dias"))
        title = f"{m.get('title')} · {falta}"
        desc = f"{(m.get('summary') or '').rstrip('.')}. Prazo: {fmt_date(m.get('deadline'))} ({falta}). Situação: {m.get('status') or ''}."
        if m.get("value"): desc += f" Valor: {brl(m['value'])}."
        if m.get("responsible_name"): desc += f" Responsável: {m['responsible_name']}" + (f" ({m['responsible_person']})" if m.get("responsible_person") else "") + "."
        if m.get("url"): desc += f" Fonte: {m['url']}"
        link = f"{base}/#{m.get('responsible_position') or ''}" if m.get("responsible_position") else f"{base}/"
        items.append(item(title, link, guid("prazo", m.get("id")), m.get("date"), desc, f'<category>MP</category>\n' + (f'<source url="{escape(m["url"])}">Congresso Nacional</source>\n' if m.get("url") else "")))
    vetos = [v for v in om.get("vetos") or [] if v.get("overdue")]
    vetos.sort(key=lambda v: -(v.get("days") or 0))
    for v in vetos:
        d = v.get("days") or 0
        title = f"{v.get('title')} · há {d} dias sem votação"
        desc = f"{(v.get('summary') or '').rstrip('.')}. Recebido em {fmt_date(v.get('date'))}; prazo constitucional de {v.get('deadline_days') or 30} dias (CF art. 66 §4º) vencido há {d - (v.get('deadline_days') or 30)} dias."
        if v.get("norma"): desc += f" Norma: {v['norma']}."
        if v.get("responsible_name"): desc += f" Responsável: {v['responsible_name']}" + (f" ({v['responsible_person']})" if v.get("responsible_person") else "") + "."
        if v.get("url"): desc += f" Fonte: {v['url']}"
        link = f"{base}/#{v.get('responsible_position') or ''}" if v.get("responsible_position") else f"{base}/"
        items.append(item(title, link, guid("prazo", v.get("id")), v.get("date"), desc, '<category>Veto</category>\n' + (f'<source url="{escape(v["url"])}">Congresso Nacional</source>\n' if v.get("url") else "")))
    return items


def feed_temas(G, base):
    items = []
    for t in (G.get("temas") or {}).get("temas") or []:
        st = STATE.get(t.get("state"), t.get("state") or ""); sd = t.get("stalled_days")
        title = f"{t.get('name')} · {st}" + (f" · {sd} dias parado" if sd else "")
        parts = [t.get("question") or ""]
        for p in t.get("processes") or []:
            parts.append(f"{p.get('id')} ({p.get('casa')}): {p.get('situation') or ''}" + (f", último movimento {fmt_date(p['last_move'])}" if p.get("last_move") else "") + (f" · {p['url']}" if p.get("url") else ""))
        if t.get("news_hits"): parts.append(f"{t['news_hits']} notícias nos últimos 90 dias.")
        if t.get("silent_and_stalled"): parts.append("Silêncio com prazo vencido: a cobertura caiu e o processo não anda.")
        last = max([p.get("last_move") or "" for p in t.get("processes") or []] + [(t.get("news_recent") or [{}])[0].get("date") or ""]) or (G.get("temas") or {}).get("generated_at")
        items.append(item(title, f"{base}/", guid("tema", t.get("id")), last, " ".join(x for x in parts if x), f"<category>{escape(st)}</category>\n"))
    return items


def feed_noticias(G, base):
    items = []
    for n in sorted(G.get("news") or [], key=lambda x: x.get("date") or "", reverse=True)[:60]:
        who = ", ".join(p.get("name") for p in (n.get("people") or []) if p.get("name"))
        desc = (n.get("summary") or "") + (f" Pessoas: {who}." if who else "") + f" Via {n.get('publication') or ''}."
        extra = f'<source url="{escape(n["url"])}">{escape(n.get("publication") or "")}</source>\n' if n.get("url") else ""
        items.append(item(n.get("title") or "", n.get("url") or f"{base}/#news:{n.get('id')}", guid("news", n.get("id")), n.get("date"), desc.strip(), extra))
    return items


def build(site_dir, prefix, base, G):
    site = pathlib.Path(site_dir); base = base.rstrip("/"); prefix = (prefix or "").rstrip("/")
    d = site / "feeds"; d.mkdir(parents=True, exist_ok=True)
    today = (G.get("stats") or {}).get("generated_at") or datetime.date.today().isoformat()
    specs = [
        ("mudancas.xml", "Atlas da República · Mudanças", "Posses, sabatinas, nomeações e saídas nos cargos do governo federal.", feed_mudancas),
        ("prazos.xml", "Atlas da República · Prazos", "Medidas provisórias a vencer em 30 dias e vetos com prazo constitucional vencido.", feed_prazos),
        ("temas.xml", "Atlas da República · Temas", "Temas acompanhados: estado do processo e dias parado.", feed_temas),
        ("noticias.xml", "Atlas da República · Notícias", "Notícias sobre órgãos e ocupantes, com link para a fonte original.", feed_noticias),
    ]
    urls = []
    for fn, title, desc, fn_items in specs:
        url = f"{base}{prefix}/feeds/{fn}"
        xml = channel(title, url, f"{base}{prefix}/", desc, fn_items(G, f"{base}{prefix}"), today)
        (d / fn).write_text(xml, encoding="utf-8"); urls.append(url)
    return urls


if __name__ == "__main__":
    import xml.etree.ElementTree as ET
    G = json.load(open(ROOT / "build" / "graph.br.json", encoding="utf-8"))
    urls = build(ROOT / "site", "", "http://localhost:8765", G)
    for u in urls:
        p = ROOT / "site" / "feeds" / u.rsplit("/", 1)[1]
        root = ET.parse(p).getroot(); n = len(root.findall("./channel/item"))
        print(f"{u}: {n} itens, {p.stat().st_size} bytes")
