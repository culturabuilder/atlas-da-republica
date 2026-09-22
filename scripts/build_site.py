#!/usr/bin/env python3
"""Gera o site estático em site/: uma página por nó (HTML pré-renderizado + app), sitemap.xml, robots.txt, JSON-LD.

Sem framework: o mesmo web/index.html vira o template; cada página recebe <title>, descrição, canonical,
JSON-LD e o painel do nó já renderizado dentro de <noscript>/<div id="ssr"> para rastreadores.
Uso: .venv/bin/python scripts/build_site.py [--base https://atlas.exemplo.br]
"""
import json, pathlib, argparse, html, shutil, re, datetime
ROOT = pathlib.Path(__file__).resolve().parent.parent
ap = argparse.ArgumentParser(); ap.add_argument("--base", default="https://atlasdarepublica.org"); ap.add_argument("--prefix", default=""); ap.add_argument("--cname", default=""); ap.add_argument("--previa", action="store_true", help="prévia de testes: noindex, faixa de aviso, câmera em foco suave por padrão"); a = ap.parse_args()
PREFIX = a.prefix.rstrip("/")
BASE = a.base.rstrip("/")
G = json.load(open(ROOT / "build" / "graph.br.json", encoding="utf-8")); N = G["nodes"]; E = G["edges"]
tpl = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
site = ROOT / "site"
shutil.rmtree(site, ignore_errors=True); (site / "br").mkdir(parents=True)
if (ROOT / "assets" / "img").exists(): shutil.copytree(ROOT / "assets" / "img", site / "img")
core_js = (ROOT / "build" / "graph.core.js").read_text(encoding="utf-8")
core_js = core_js.replace('"detail_base":"/nodes/"', f'"detail_base":"{PREFIX}/nodes/"').replace('"img_base":"/img/"', f'"img_base":"{PREFIX}/img/"').replace('"people_base":"/people/"', f'"people_base":"{PREFIX}/people/"')
(site / "graph.br.js").write_text(core_js, encoding="utf-8")
shutil.copytree(ROOT / "build" / "nodes", site / "nodes")
shutil.copytree(ROOT / "build" / "people", site / "people")
if (ROOT / "site_img_cache").exists(): pass
tpl = tpl.replace('<script src="graph.br.js" defer></script>', f'<script src="{PREFIX}/graph.br.js" defer></script>').replace('<script src="atlas.js" defer></script>', f'<script src="{PREFIX}/atlas.js" defer></script>').replace('<link rel="stylesheet" href="atlas.css">', f'<link rel="stylesheet" href="{PREFIX}/atlas.css">')
for f in ("atlas.js", "atlas.css", "atlas-camera.js"): shutil.copy(ROOT / "web" / f, site / f)
# câmera reversível da roda: módulo separado, só no navegador (render_wheel.js não o carrega)
_cam_flags = '<script>window.ATLAS_PREVIA=true;window.ATLAS_CAMERA_DEFAULT="focus";</script>' if a.previa else ''
tpl = tpl.replace(f'<script src="{PREFIX}/atlas.js" defer></script>', f'{_cam_flags}<script src="{PREFIX}/atlas.js" defer></script><script src="{PREFIX}/atlas-camera.js" defer></script>', 1)
if a.previa: tpl = tpl.replace("<title>", '<meta name="robots" content="noindex,nofollow">\n<title>', 1)
# atlas.css é pequeno: embutido para não bloquear a renderização com mais uma requisição
for _form in (f'<link rel="stylesheet" href="{PREFIX}/atlas.css">', '<link rel="stylesheet" href="atlas.css">'):
    tpl = tpl.replace(_form, "<style>" + (ROOT / "web" / "atlas.css").read_text(encoding="utf-8") + "</style>", 1)
# roda pré-renderizada (LCP sem esperar o JS): node executa o mesmo atlas.js sem DOM
import subprocess
WHEEL = ""
try:
    subprocess.run(["node", str(ROOT / "scripts" / "render_wheel.js"), str(ROOT / "build" / "graph.core.js"), str(ROOT / "web" / "atlas.js"), str(ROOT / "build" / "wheel.svg")], check=True, capture_output=True)
    WHEEL = (ROOT / "build" / "wheel.svg").read_text(encoding="utf-8")
except Exception as e: print("aviso: roda não pré-renderizada:", e)
# só a home e a área educativa recebem o SVG embutido (páginas de nó e de pessoa desenham no cliente, para manter o site leve)
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
    ssr = f'''<div id="ssr"><article><h1>{esc(n["name"])}</h1><p>{esc(n.get("description") or "")}</p><p>Fonte legal: {esc(n.get("cite") or "")}</p>
{("<h2>Ocupantes</h2><ul>" + people + "</ul>") if people else ""}{("<h2>Órgãos integrados e vinculados</h2><ul>" + kids + "</ul>") if kids else ""}<h2>Relações</h2><ul>{"".join(rels)}</ul><p><a href="/">Atlas da República</a></p></article></div>'''
    og_img = f"{BASE}{PREFIX}/og/{n['id']}.png" if n["id"] in OG_IDS else f"{BASE}{PREFIX}/og/atlas.png"
    head = f'<title>{esc(title)}</title>\n<meta name="description" content="{esc(desc)}">\n<link rel="canonical" href="{url}">\n<meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(desc)}"><meta property="og:url" content="{url}"><meta property="og:type" content="website"><meta property="og:image" content="{og_img}"><meta property="og:image:width" content="1200"><meta property="og:image:height" content="630"><meta name="twitter:card" content="summary_large_image">\n<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>\n'
    out = tpl.replace("<title>Atlas da República</title>\n", head, 1)
    out = out.replace('<div id="content"></div>', '<div id="content"></div>' + ssr, 1)
    out = out.replace("select(location.hash.slice(1));", f"select(location.hash.slice(1) || {json.dumps(n['id'])});", 1)
    return out

def person_page(p):
    url = f"{BASE}/br/pessoa/{p['id']}/"; title = f"{p['name']} · Atlas da República"
    pos = "".join(f'<li><a href="/br/{q["id"]}/">{esc(q["name"])}</a>{(" · desde " + esc(q["since"])) if q.get("since") else ""}</li>' for q in p["positions"] if q["id"] in N)
    desc = f"{p['name']}: " + "; ".join(q["name"] for q in p["positions"][:3])
    ld = {"@context": "https://schema.org", "@type": "Person", "name": p["name"], "url": url, "hasOccupation": [{"@type": "Role", "roleName": q["name"]} for q in p["positions"][:5]]}
    if p.get("party"): ld["memberOf"] = {"@type": "Organization", "name": p["party"]}
    if p.get("photo"): ld["image"] = f"{BASE}/img/{p['id']}.jpg"
    og_img = f"{BASE}{PREFIX}/og/{p['id']}.png" if p["id"] in OG_IDS else f"{BASE}{PREFIX}/og/atlas.png"
    head = f'<title>{esc(title)}</title>\n<meta name="description" content="{esc(desc[:300])}">\n<link rel="canonical" href="{url}">\n<meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(desc[:300])}"><meta property="og:url" content="{url}"><meta property="og:type" content="profile"><meta property="og:image" content="{og_img}"><meta property="og:image:width" content="1200"><meta property="og:image:height" content="630"><meta name="twitter:card" content="summary_large_image">\n<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>\n'
    ssr = f'<div id="ssr"><article><h1>{esc(p["name"])}</h1><p>{esc(p.get("party") or "")} {esc(p.get("uf") or "")}</p><h2>Cargos</h2><ul>{pos}</ul><p><a href="/">Atlas da República</a></p></article></div>'
    out = tpl.replace("<title>Atlas da República</title>\n", head, 1).replace('<div id="content"></div>', '<div id="content"></div>' + ssr, 1)
    out = out.replace("select(location.hash.slice(1));", f"select(location.hash.slice(1) || {json.dumps(p['id'])});", 1)
    return out.replace('href="/br/', f'href="{PREFIX}/br/').replace('href="/"', f'href="{PREFIX}/"')

import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("build_como_funciona", ROOT / "scripts" / "build_como_funciona.py"); _cf = _ilu.module_from_spec(_spec); _spec.loader.exec_module(_cf)
def _mod(name):
    sp = _ilu.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py"); m = _ilu.module_from_spec(sp); sp.loader.exec_module(m); return m
urls = [f"{BASE}/", _cf.build(site, PREFIX, BASE, G, WHEEL)]
_met = (ROOT / "web" / "metodologia.html")
if _met.exists():
    (site / "metodologia").mkdir(parents=True, exist_ok=True)
    _mt = _met.read_text(encoding="utf-8").replace("__PREFIX__", PREFIX)
    _ex = (G.get("stats") or {}).get("execucao") or {}
    _bl = _ex.get("blocos") or {}
    if _bl:
        _hoje = datetime.date.today()
        def _dias(d):
            try: return (_hoje - datetime.date.fromisoformat(d)).days
            except Exception: return None
        _its = []
        for _lbl, _v in _bl.items():
            if not _v.get("existe"): _its.append(f'<div class="it miss"><b>{html.escape(_lbl)}</b><span>sem dado</span></div>'); continue
            _d = _v.get("lido_em"); _n = _dias(_d) if _d else None
            _cls = " old" if (_n is not None and _n > 7) else ""
            _q = "hoje" if _n == 0 else ("ontem" if _n == 1 else (f"há {_n} dias" if _n is not None else "—"))
            _its.append(f'<div class="it{_cls}"><b>{html.escape(_lbl)}</b><span>{_q}</span></div>')
        _falhas = _ex.get("falhas") or []
        _nota = ("Cada bloco é lido por um conector próprio; a data abaixo é a da última leitura bem-sucedida daquela fonte. "
                 "Fontes com atualização mensal ou eleitoral aparecem com mais dias por natureza, não por falha.")
        _alerta = (f'<p style="color:var(--leg,#B8452E);font-size:13.5px;margin:0 0 8px"><b>Conectores com falha na última rodada:</b> {html.escape(", ".join(_falhas))}.</p>' if _falhas else "")
        _quadro = f'<div class="fresh"><h2>Quando cada bloco foi lido</h2><p>{_nota}</p>{_alerta}<div class="grid">{"".join(_its)}</div></div>'
    else:
        _quadro = ""
    (site / "metodologia" / "index.html").write_text(_mt.replace("__ATUALIZACAO__", _quadro), encoding="utf-8"); urls.append(f"{BASE}/metodologia/")
OG_IDS = set()
for _name in ("build_comparar", "build_feeds", "build_dados", "build_og"):
    if (ROOT / "scripts" / f"{_name}.py").exists():
        try:
            r = _mod(_name).build(site, PREFIX, BASE, G)
            if isinstance(r, str): urls.append(r)
            elif isinstance(r, list): urls += [u for u in r if isinstance(u, str) and u.startswith("http")]
            elif isinstance(r, dict) and _name == "build_og": OG_IDS = set(r.keys())
        except Exception as e: print(f"aviso: {_name} falhou:", e)
PEOPLE = G.get("people", {})
for p in PEOPLE.values():
    d = site / "br" / "pessoa" / p["id"]; d.mkdir(parents=True, exist_ok=True)
    (d / "index.html").write_text(person_page(p), encoding="utf-8"); urls.append(f"{BASE}/br/pessoa/{p['id']}/")
for n in N.values():
    d = site / "br" / n["id"]; d.mkdir(parents=True, exist_ok=True)
    (d / "index.html").write_text(page(n), encoding="utf-8"); urls.append(f"{BASE}/br/{n['id']}/")
home = tpl.replace("<title>Atlas da República</title>\n", f'<title>Atlas da República</title>\n<meta name="description" content="Mapa navegável do governo federal brasileiro: órgãos, cargos, colegiados e as relações legais entre eles, com citação da norma.">\n<link rel="canonical" href="{BASE}/">\n<meta property="og:title" content="Atlas da República"><meta property="og:description" content="Quem manda em quê no governo federal, com a lei que diz isso."><meta property="og:url" content="{BASE}/"><meta property="og:type" content="website"><meta property="og:image" content="{BASE}{PREFIX}/og/atlas.png"><meta property="og:image:width" content="1200"><meta property="og:image:height" content="630"><meta name="twitter:card" content="summary_large_image">\n<link rel="alternate" type="application/rss+xml" title="Mudanças de cargo" href="{BASE}{PREFIX}/feeds/mudancas.xml"><link rel="alternate" type="application/rss+xml" title="Prazos vencendo" href="{BASE}{PREFIX}/feeds/prazos.xml"><link rel="alternate" type="application/rss+xml" title="Temas" href="{BASE}{PREFIX}/feeds/temas.xml">\n', 1)
links = "".join(f'<li><a href="/br/{n["id"]}/">{esc(n["name"])}</a></li>' for n in sorted(N.values(), key=lambda x: x["name"]) if n["type"] != "dept_head")
st = G["stats"]
first = (f'<a class="card start" href="{PREFIX}/como-funciona/"><span class="eyebrow">Comece por aqui</span><b>Como funciona a República</b><span>Uma visita guiada de 9 minutos pela roda: quem você elege, quem nomeia quem, quem vigia quem. Para quem nunca precisou entender isso e agora quer.</span><span class="go">Começar →</span></a>'
         f'<div class="card"><h1>Quem manda em quê no governo federal</h1><p>Um mapa de cada órgão, cargo e colegiado da União e das relações legais entre eles: quem elege, nomeia, sabatina, supervisiona e fiscaliza quem. Cada ligação cita a norma que a cria.</p>'
         f'<div class="stats"><div class="stat"><div class="n">{st["nodes"]}</div><div class="l">nós</div></div><div class="stat"><div class="n">{st["edges"]}</div><div class="l">relações</div></div><div class="stat"><div class="n">{st.get("seats_filled", 0)}</div><div class="l">de {st["seats_total"]} cadeiras com ocupante</div></div></div></div>')
# os dois primeiros cartões da home já vêm no HTML (pintura imediata); o JS os substitui pelo painel completo
home = home.replace('<div id="content"></div>', '<div id="content">' + first + '</div><div id="ssr" hidden><h1>Atlas da República</h1><ul>' + links + '</ul></div>', 1)
if WHEEL: home = home.replace('<div id="graph"></div>', '<div id="graph">' + WHEEL + '</div>', 1)
home = home.replace('href="/br/', f'href="{PREFIX}/br/').replace('href="/como-funciona/"', f'href="{PREFIX}/como-funciona/"').replace('href="/comparar/"', f'href="{PREFIX}/comparar/"').replace('href="/dados/"', f'href="{PREFIX}/dados/"').replace('href="/metodologia/"', f'href="{PREFIX}/metodologia/"').replace('href="/feeds/', f'href="{PREFIX}/feeds/')
(site / "index.html").write_text(home, encoding="utf-8")
(site / ".nojekyll").write_text("", encoding="utf-8")
if a.cname: (site / "CNAME").write_text(a.cname + "\n", encoding="utf-8")
today = datetime.date.today().isoformat()
(site / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + "".join(f"<url><loc>{u}</loc><lastmod>{today}</lastmod></url>\n" for u in urls) + "</urlset>\n", encoding="utf-8")
(site / "robots.txt").write_text("User-agent: *\nDisallow: /\n" if a.previa else f"User-agent: *\nAllow: /\nSitemap: {BASE}/sitemap.xml\n", encoding="utf-8")
(site / "404.html").write_text(tpl.replace("<title>Atlas da República</title>", "<title>Página não encontrada · Atlas da República</title>"), encoding="utf-8")
(site / "vercel.json").write_text(json.dumps({"cleanUrls": True, "headers": [{"source": "/(.*)", "headers": [{"key": "X-Content-Type-Options", "value": "nosniff"}, {"key": "X-Frame-Options", "value": "SAMEORIGIN"}, {"key": "Referrer-Policy", "value": "strict-origin-when-cross-origin"}, {"key": "Permissions-Policy", "value": "camera=(), microphone=(), geolocation=()"}]}, {"source": "/graph.br.js", "headers": [{"key": "Cache-Control", "value": "public, max-age=3600, stale-while-revalidate=86400"}]}]}, indent=1), encoding="utf-8")
print(f"site/: {len(urls)} páginas ({len(PEOPLE)} de pessoas), sitemap, robots, 404, vercel.json")
