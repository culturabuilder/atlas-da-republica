#!/usr/bin/env python3
"""Gera o site estático em site/: uma página por nó (HTML pré-renderizado + app), sitemap.xml, robots.txt, JSON-LD.

Sem framework: o mesmo web/index.html vira o template; cada página recebe <title>, descrição, canonical,
JSON-LD e o painel do nó já renderizado dentro de <noscript>/<div id="ssr"> para rastreadores.
Uso: .venv/bin/python scripts/build_site.py [--base https://atlas.exemplo.br]
"""
import json, pathlib, argparse, html, shutil, re, datetime
ROOT = pathlib.Path(__file__).resolve().parent.parent
ap = argparse.ArgumentParser(); ap.add_argument("--base", default="https://atlasdarepublica.org"); a = ap.parse_args()
BASE = a.base.rstrip("/")
G = json.load(open(ROOT / "build" / "graph.br.json", encoding="utf-8")); N = G["nodes"]; E = G["edges"]
tpl = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
site = ROOT / "site"; shutil.rmtree(site, ignore_errors=True); (site / "br").mkdir(parents=True)
shutil.copy(ROOT / "web" / "graph.br.js", site / "graph.br.js")
tpl = tpl.replace('<script src="graph.br.js"></script>', '<script src="/graph.br.js"></script>')
REL = {"elege": "elege", "nomeia": "nomeia", "sabatina": "sabatina e aprova", "fiscaliza": "fiscaliza", "supervisiona": "supervisiona", "aconselha": "aconselha", "chefia": "chefia", "membro_nato": "é membro nato de", "integra": "integra", "indica": "indica"}
TYPE_SCHEMA = {"department": "GovernmentOrganization", "elected": "GovernmentOrganization", "commission": "GovernmentOrganization", "advisory": "GovernmentOrganization", "dept_head": "Role", "constituency": "Organization"}
esc = html.escape

def page(n):
    url = f"{BASE}/br/{n['id']}/"
    desc = (n.get("description") or "")[:300]
    title = f"{n['name']} · Atlas da República"
    ld = {"@context": "https://schema.org", "@type": TYPE_SCHEMA.get(n["type"], "Thing"), "name": n["name"], "description": desc, "url": url}
    if n.get("official_url"): ld["sameAs"] = [n["official_url"]]
    if n.get("aliases"): ld["alternateName"] = n["aliases"]
    if n.get("parent") and n["parent"] in N: ld["parentOrganization"] = {"@type": "GovernmentOrganization", "name": N[n["parent"]]["name"], "url": f"{BASE}/br/{n['parent']}/"}
    if n["type"] == "dept_head":
        ld["@type"] = "Role"; ld["roleName"] = n["name"]
        if n.get("people"): ld["member"] = [{"@type": "Person", "name": p.get("name"), "startDate": p.get("started_at")} for p in n["people"][:50] if p.get("name")]
    rels = []
    for eid in n.get("edges", []):
        e = E[eid]; other = e["to"] if e["from"] == n["id"] else e["from"]; o = N.get(other)
        if not o: continue
        rels.append(f'<li>{esc(n["name"]) if e["from"]==n["id"] else esc(o["name"])} <em>{REL.get(e["type"], e["type"])}</em> <a href="/br/{other}/">{esc(o["name"]) if e["from"]==n["id"] else esc(n["name"])}</a> <small>({esc(e.get("cite") or "")})</small></li>')
    people = "".join(f'<li>{esc(p.get("name") or "")}{(" · " + esc(p["party"])) if p.get("party") else ""}{(" · desde " + esc(p["started_at"])) if p.get("started_at") else ""}</li>' for p in (n.get("people") or [])[:600])
    kids = "".join(f'<li><a href="/br/{k}/">{esc(N[k]["name"])}</a></li>' for k in n.get("children", []) if k in N)
    ssr = f'''<div id="ssr" hidden><article><h1>{esc(n["name"])}</h1><p>{esc(n.get("description") or "")}</p><p>Fonte legal: {esc(n.get("cite") or "")}</p>
{("<h2>Ocupantes</h2><ul>" + people + "</ul>") if people else ""}{("<h2>Órgãos integrados e vinculados</h2><ul>" + kids + "</ul>") if kids else ""}<h2>Relações</h2><ul>{"".join(rels)}</ul><p><a href="/">Atlas da República</a></p></article></div>'''
    head = f'<title>{esc(title)}</title>\n<meta name="description" content="{esc(desc)}">\n<link rel="canonical" href="{url}">\n<meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(desc)}"><meta property="og:url" content="{url}"><meta property="og:type" content="website">\n<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>\n'
    out = tpl.replace("<title>Atlas da República</title>\n", head, 1)
    out = out.replace('<div id="content"></div>', '<div id="content"></div>' + ssr, 1)
    out = out.replace("select(location.hash.slice(1));", f"select(location.hash.slice(1) || {json.dumps(n['id'])});", 1)
    return out

urls = [f"{BASE}/"]
for n in N.values():
    d = site / "br" / n["id"]; d.mkdir(parents=True, exist_ok=True)
    (d / "index.html").write_text(page(n), encoding="utf-8"); urls.append(f"{BASE}/br/{n['id']}/")
home = tpl.replace("<title>Atlas da República</title>\n", f'<title>Atlas da República</title>\n<meta name="description" content="Mapa navegável do governo federal brasileiro: órgãos, cargos, colegiados e as relações legais entre eles, com citação da norma.">\n<link rel="canonical" href="{BASE}/">\n', 1)
links = "".join(f'<li><a href="/br/{n["id"]}/">{esc(n["name"])}</a></li>' for n in sorted(N.values(), key=lambda x: x["name"]) if n["type"] != "dept_head")
home = home.replace('<div id="content"></div>', '<div id="content"></div><div id="ssr" hidden><h1>Atlas da República</h1><ul>' + links + '</ul></div>', 1)
(site / "index.html").write_text(home, encoding="utf-8")
today = datetime.date.today().isoformat()
(site / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + "".join(f"<url><loc>{u}</loc><lastmod>{today}</lastmod></url>\n" for u in urls) + "</urlset>\n", encoding="utf-8")
(site / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {BASE}/sitemap.xml\n", encoding="utf-8")
(site / "404.html").write_text(tpl.replace("<title>Atlas da República</title>", "<title>Página não encontrada · Atlas da República</title>"), encoding="utf-8")
(site / "vercel.json").write_text(json.dumps({"cleanUrls": True, "headers": [{"source": "/(.*)", "headers": [{"key": "X-Content-Type-Options", "value": "nosniff"}, {"key": "X-Frame-Options", "value": "SAMEORIGIN"}, {"key": "Referrer-Policy", "value": "strict-origin-when-cross-origin"}, {"key": "Permissions-Policy", "value": "camera=(), microphone=(), geolocation=()"}]}, {"source": "/graph.br.js", "headers": [{"key": "Cache-Control", "value": "public, max-age=3600, stale-while-revalidate=86400"}]}]}, indent=1), encoding="utf-8")
print(f"site/: {len(urls)} páginas, sitemap, robots, 404, vercel.json")
