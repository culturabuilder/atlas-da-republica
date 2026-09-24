#!/usr/bin/env python3
"""Área "Do zero": o governo explicado em palavras simples, a partir de data/do-zero.yaml.

Chamado por scripts/build_site.py: build(site_dir, prefix, base, G). Roda sozinho para teste:
.venv/bin/python scripts/build_do_zero.py

A página é estática e legível sem JavaScript: cada capítulo é uma pergunta, com resposta curta,
explicação, comparação do dia a dia, as palavras difíceis e um link para ver aquilo no mapa.
"""
import html, json, pathlib, re, sys
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent


def esc(t):
    return html.escape(str(t or ""), quote=True)


def build(site, prefix, base, G):
    src = ROOT / "data" / "do-zero.yaml"
    if not src.exists():
        print("aviso: data/do-zero.yaml não existe; área Do zero não gerada"); return None
    d = yaml.safe_load(src.read_text(encoding="utf-8")) or {}
    caps = d.get("capitulos") or []
    N = (G or {}).get("nodes") or {}

    def link_de(cap):
        l = str(cap.get("link") or "").strip()
        if not l: return None, None
        if l.startswith("/"): return f"{prefix}{l}", "ver no site"
        n = N.get(l)
        if not n: return f"{prefix}/#{l}", "ver no mapa"
        nome = n["name"] if len(n["name"]) <= 34 else (n.get("aliases") or [n["name"][:32] + "…"])[0]
        return f"{prefix}/#{l}", f"ver {nome} no mapa"

    itens = []
    for i, c in enumerate(caps, 1):
        href, rot = link_de(c)
        palavras = "".join(
            f'<div class="w"><b>{esc(p.get("termo"))}</b><span>{esc(p.get("e"))}</span></div>'
            for p in (c.get("palavras") or []))
        _lk = f' <a href="{href}">{esc(rot)} →</a>' if href else ""
        no_atlas = f'<p class="no-atlas">{esc(c.get("no_atlas"))}{_lk}</p>' if c.get("no_atlas") else ""
        itens.append(f'''<section class="cap" id="{esc(c.get('id'))}">
  <div class="n">{i:02d}</div>
  <div class="txt">
    <h2>{esc(c.get('pergunta'))}</h2>
    <p class="curta">{esc(c.get('resposta_curta'))}</p>
    <p>{esc(c.get('texto'))}</p>
    {f'<p class="ana"><b>É parecido com isto.</b> {esc(c.get("analogia"))}</p>' if c.get("analogia") else ''}
    {f'<div class="words">{palavras}</div>' if palavras else ''}
    {no_atlas}
  </div>
</section>''')

    gloss = "".join(
        f'<div class="g"><b>{esc(t.get("termo"))}</b><span>{esc(t.get("e"))}</span></div>'
        for t in (d.get("glossario") or []))
    indice = "".join(
        f'<li><a href="#{esc(c.get("id"))}"><b>{i:02d}</b><span>{esc(c.get("pergunta"))}</span></a></li>'
        for i, c in enumerate(caps, 1))

    page = f'''<!doctype html>
<html lang="pt-BR">
<head>
<script>try{{var _t=localStorage.getItem('atlas-theme')||'dark';if(_t!=='auto')document.documentElement.dataset.theme=_t}}catch(e){{document.documentElement.dataset.theme='dark'}}</script>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Do zero · Atlas da República</title>
<meta name="description" content="{esc(d.get('subtitulo'))} Área do Atlas da República para quem nunca estudou como o governo funciona.">
<link rel="canonical" href="{base}{prefix}/do-zero/">
<meta property="og:title" content="Do zero · Atlas da República">
<meta property="og:description" content="{esc(d.get('subtitulo'))}">
<meta property="og:type" content="article">
<meta property="og:url" content="{base}{prefix}/do-zero/">
<meta property="og:image" content="{base}{prefix}/og/atlas.png">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@600;700&family=JetBrains+Mono:wght@400;500&family=Source+Sans+3:wght@400;600&display=swap" media="print" onload="this.media='all'">
<link rel="stylesheet" href="{prefix}/atlas.css">
<style>
body{{background:var(--bg);color:var(--ink);font:17px/1.6 var(--sans);margin:0;padding:0 20px;padding-block:28px 72px}}
main{{max-width:760px;margin:0 auto}}
.voltar{{font-size:14px;color:var(--accent);text-decoration:none}}
h1{{font:700 40px/1.05 var(--disp);letter-spacing:-.02em;margin:14px 0 6px;text-wrap:balance}}
.sub{{font-size:20px;color:var(--ink-2);margin:0 0 10px;max-width:34ch}}
.intro{{font-size:17px;color:var(--ink-2);margin:0 0 6px;max-width:60ch}}
.aviso{{background:var(--accent-soft);border:1px solid var(--accent);border-radius:10px;padding:12px 14px;font-size:14px;line-height:1.5;color:var(--ink-2);margin:16px 0 26px}}
.aviso b{{color:var(--ink)}}
.toc{{list-style:none;padding:0;margin:0 0 34px;display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:4px 14px}}
.toc a{{display:flex;gap:9px;align-items:baseline;text-decoration:none;color:var(--ink-2);font-size:15px;padding:5px 6px;border-radius:7px}}
.toc a:hover{{background:var(--panel);color:var(--ink)}}
.toc b{{font:500 12px var(--mono);color:var(--ink-3)}}
.cap{{display:grid;grid-template-columns:52px minmax(0,1fr);gap:14px;padding:22px 0;border-top:1px solid var(--line-2)}}
.cap>*,.cap .txt *{{min-width:0}}
.cap h2,.cap p,.words b,.words span,.gloss b,.gloss span{{overflow-wrap:anywhere}}
.cap .n{{font:700 26px/1 var(--disp);color:var(--line);letter-spacing:-.02em}}
.cap h2{{font:700 26px/1.15 var(--disp);margin:0 0 8px;text-wrap:balance}}
.cap p{{margin:0 0 12px;max-width:62ch}}
.curta{{font-size:19px;color:var(--ink);font-weight:600;line-height:1.4}}
.ana{{background:var(--panel);border-left:3px solid var(--accent);border-radius:0 8px 8px 0;padding:10px 12px;font-size:16px;color:var(--ink-2)}}
.ana b{{color:var(--ink)}}
.words{{display:grid;gap:6px;margin:0 0 12px}}
.words .w{{display:grid;grid-template-columns:minmax(0,auto) minmax(0,1fr);gap:4px 10px;font-size:14.5px;align-items:baseline}}
.words b{{font-family:var(--mono);font-size:13px;color:var(--accent)}}
.words span{{color:var(--ink-2)}}
.no-atlas{{font-size:15px;color:var(--ink-3)}}
.no-atlas a{{color:var(--accent);text-decoration:none;border-bottom:1px solid var(--line-2);overflow-wrap:anywhere}}
.gloss{{margin-top:40px;border-top:1px solid var(--line);padding-top:20px}}
.gloss h2{{font:700 24px/1.2 var(--disp);margin:0 0 10px}}
.gloss .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:8px 18px}}
.gloss .g{{font-size:15px}}
.gloss .g b{{display:block;font-family:var(--mono);font-size:13.5px;color:var(--accent)}}
.gloss .g span{{color:var(--ink-2)}}
.fim{{margin-top:34px;padding-top:18px;border-top:1px solid var(--line);font-size:15px;color:var(--ink-2)}}
.fim a{{color:var(--accent)}}
@media (max-width:640px){{
  h1{{font-size:32px}} .sub{{font-size:18px}}
  .cap{{grid-template-columns:1fr;gap:4px}} .cap .n{{font-size:15px;font-family:var(--mono);font-weight:500}}
  .cap h2{{font-size:23px}}
}}
</style>
</head>
<body>
<main>
<a class="voltar" href="{prefix}/">← Atlas da República</a>
<h1>{esc(d.get('titulo'))}</h1>
<p class="sub">{esc(d.get('subtitulo'))}</p>
<p class="intro">{esc(d.get('intro'))}</p>
<div class="aviso"><b>Este projeto é apartidário.</b> {esc(d.get('neutralidade'))}</div>
<ol class="toc">{indice}</ol>
{''.join(itens)}
<div class="gloss"><h2>Palavras que aparecem no site</h2><div class="grid">{gloss}</div></div>
<p class="fim">Quando quiser ir além, a área <a href="{prefix}/como-funciona/">Como funciona a República</a> mostra a mesma coisa pelo mapa, em nove minutos. Todos os números do site vêm de fontes oficiais, listadas na <a href="{prefix}/metodologia/">metodologia</a>, e os dados podem ser baixados em <a href="{prefix}/dados/">dados abertos</a>.</p>
</main>
<script>window.ATLAS_PREFIX="{prefix}";</script>
<script src="{prefix}/atlas-menu.js" defer></script>
</body>
</html>'''
    d_out = site / "do-zero"; d_out.mkdir(parents=True, exist_ok=True)
    (d_out / "index.html").write_text(page, encoding="utf-8")
    print(f"   do-zero/: {len(caps)} capítulos, {len(d.get('glossario') or [])} termos")
    return f"{base}{prefix}/do-zero/"


if __name__ == "__main__":
    G = json.load(open(ROOT / "build" / "graph.br.json", encoding="utf-8"))
    build(ROOT / "site", "", "https://atlasdarepublica.org", G)
