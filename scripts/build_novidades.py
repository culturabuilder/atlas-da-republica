#!/usr/bin/env python3
"""Página "O que mudou no Atlas" em site/novidades/.

Chamado por scripts/build_site.py: build(site_dir, prefix, base, G) -> lista de URLs geradas.
Também roda sozinho para teste: .venv/bin/python scripts/build_novidades.py

A fonte é data/generated/novidades.yaml, que scripts/novidades.py tira do histórico do projeto. O
texto de cada item é o parágrafo de abertura do commit — escrito, desde o começo, para ser lido por
gente e não por quem mexe no código.
"""
import datetime, html, json, pathlib
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
esc = html.escape
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
# rótulo -> cor do assunto, as mesmas quatro do resto do site
COR = {"fonte nova": "var(--povo)", "tela": "var(--exe)", "coleta": "var(--exe)",
       "verificação": "var(--jud)", "método": "var(--jud)", "dado curado": "var(--accent)",
       "publicação": "var(--leg)", "projeto": "var(--ink-3)"}


def data_pt(d):
    try:
        y, m, dd = str(d).split("-")
        return f"{int(dd)} de {MESES[int(m) - 1]} de {y}"
    except Exception: return str(d)


def mes_pt(ym):
    try:
        y, m = str(ym).split("-")
        return f"{MESES[int(m) - 1]} de {y}"
    except Exception: return str(ym)


def build(site_dir, prefix, base, G):
    site = pathlib.Path(site_dir); out = site / "novidades"; out.mkdir(parents=True, exist_ok=True)
    base = base.rstrip("/"); prefix = (prefix or "").rstrip("/")
    f = ROOT / "data" / "generated" / "novidades.yaml"
    if not f.exists(): return []
    d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    itens = d.get("novidades") or []
    if not itens: return []
    st = G.get("stats") or {}

    # agrupado por mês, do mais recente para o mais antigo
    blocos = []
    atual = None
    for x in itens:
        ym = str(x.get("data") or "")[:7]
        if ym != atual:
            if atual is not None: blocos.append("</div>")
            blocos.append(f'<h2 id="m{esc(ym)}">{esc(mes_pt(ym))}</h2><div class="lista">')
            atual = ym
        tags = "".join(f'<span class="tag" style="--c:{COR.get(t, "var(--ink-3)")}">{esc(t)}</span>' for t in (x.get("areas") or []))
        txt = f'<p>{esc(x["texto"])}</p>' if x.get("texto") else ""
        blocos.append(f'''<article class="it">
      <div class="hd"><time datetime="{esc(x.get("data") or "")}">{esc(data_pt(x.get("data")))}</time>{tags}</div>
      <h3>{esc(x.get("titulo") or "")}</h3>{txt}</article>''')
    if atual is not None: blocos.append("</div>")

    # o que o Atlas cobre hoje, para a página não ser só história
    cob = st.get("cobertura") or {}
    numeros = [(f'{st.get("nodes", 0):,}'.replace(",", "."), "órgãos, cargos e colegiados"),
               (f'{st.get("edges", 0):,}'.replace(",", "."), "ligações com a norma que as cria"),
               (f'{st.get("people", 0):,}'.replace(",", "."), "pessoas"),
               (f'{(st.get("sancoes") or {}).get("ceaf", 0):,}'.replace(",", "."), "servidores expulsos registrados"),
               (f'{(st.get("contratos") or {}).get("contratos", 0):,}'.replace(",", "."), "contratos federais lidos"),
               (f'{(st.get("falabr") or {}).get("pedidos", 0):,}'.replace(",", "."), "pedidos de acesso à informação")]
    cards = "".join(f'<div class="num"><b>{v}</b><span>{esc(l)}</span></div>' for v, l in numeros if v != "0")
    faltas = [(cob.get("colegiados_sem_membros"), f'de {cob.get("colegiados", 0)} colegiados sem a composição registrada'),
              (cob.get("cargos_sem"), f'de {cob.get("cargos", 0)} cargos de chefia sem ocupante conhecido'),
              (cob.get("nomeacoes_sem_data"), "nomeações sem a data em que começaram"),
              (st.get("unverified"), "citações curadas ainda por conferir")]
    falta_html = "".join(f"<li><b>{v}</b> {esc(l)}</li>" for v, l in faltas if v)

    hoje = st.get("generated_at") or datetime.date.today().isoformat()
    por_mes = d.get("por_mes") or {}
    html_doc = f'''<!doctype html>
<html lang="pt-BR">
<script>try{{document.documentElement.dataset.theme=localStorage.getItem('atlas-theme')||'dark'}}catch(e){{document.documentElement.dataset.theme='dark'}}</script>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>O que mudou no Atlas · Atlas da República</title>
<meta name="description" content="Cada mudança do Atlas da República: fonte nova, tela nova, conserto de coleta e verificação. Tirado do histórico do projeto, que é aberto.">
<link rel="canonical" href="{esc(base)}{esc(prefix)}/novidades/">
<link rel="alternate" type="application/rss+xml" title="Novidades do Atlas da República" href="{esc(prefix)}/feeds/novidades.xml">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns=%27http://www.w3.org/2000/svg%27 viewBox=%270 0 32 32%27%3E%3Ccircle cx=%2716%27 cy=%2716%27 r=%2714%27 fill=%27%23C25A12%27/%3E%3C/svg%3E">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@500;600;700;800&family=Source+Sans+3:ital,wght@0,400;0,600;1,400&family=JetBrains+Mono:wght@400;600&display=swap" media="print" onload="this.media='all'">
<link rel="stylesheet" href="{esc(prefix)}/atlas.css">
<style>
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:17px;line-height:1.55}}
a{{color:var(--accent)}}
.bar{{position:sticky;top:0;z-index:5;display:flex;align-items:center;gap:14px;padding:8px 16px;background:color-mix(in srgb,var(--bg) 88%,transparent);backdrop-filter:blur(8px);border-bottom:1px solid var(--line-2)}}
.bar .brand{{display:flex;align-items:center;gap:8px;font-family:var(--disp);font-weight:700;font-size:15px;color:var(--ink);text-decoration:none;white-space:nowrap;min-width:0;overflow:hidden;text-overflow:ellipsis}}
.bar .brand .mark{{width:16px;height:16px;border-radius:50%;background:var(--povo);box-shadow:0 0 0 2px var(--card),0 0 0 3px var(--povo)}}
.bar .crumb{{color:var(--ink-3);font-weight:500}}
.bar .sp{{flex:1}}
.btn{{font:inherit;font-size:13px;padding:6px 10px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--ink);cursor:pointer;text-decoration:none}}
main{{max-width:820px;margin:0 auto;padding:24px 20px 80px}}
.eyebrow{{font-family:var(--mono);font-size:11.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--ink-3)}}
h1{{font-family:var(--disp);font-size:clamp(30px,5vw,44px);font-weight:800;letter-spacing:-.02em;line-height:1.05;margin:10px 0 12px}}
h2{{font-family:var(--disp);font-size:15px;font-weight:700;letter-spacing:.02em;text-transform:lowercase;color:var(--ink-3);margin:34px 0 6px;padding-bottom:5px;border-bottom:1px solid var(--line-2)}}
h3{{font-family:var(--disp);font-size:19px;font-weight:700;letter-spacing:-.01em;line-height:1.25;margin:2px 0 4px}}
p.lead{{font-size:19px;color:var(--ink-2);max-width:62ch;margin:0 0 10px}}
.meta{{display:flex;gap:16px;flex-wrap:wrap;font-family:var(--mono);font-size:12px;color:var(--ink-3);margin:12px 0 22px}}
.nums{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:0 0 10px}}
.num{{background:var(--card);border:1px solid var(--line-2);border-radius:10px;padding:10px 12px}}
.num b{{display:block;font-family:var(--disp);font-size:22px;font-weight:800;letter-spacing:-.01em}}
.num span{{display:block;font-size:12.5px;color:var(--ink-3);line-height:1.3;margin-top:1px}}
.lista{{display:flex;flex-direction:column}}
.it{{padding:13px 0 14px;border-bottom:1px dashed var(--line-2)}}
.it:last-child{{border-bottom:0}}
.it .hd{{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:3px}}
.it time{{font-family:var(--mono);font-size:11.5px;color:var(--ink-3)}}
.tag{{font-family:var(--mono);font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;padding:2px 7px;border-radius:999px;color:var(--c);border:1px solid color-mix(in srgb,var(--c) 45%,transparent);background:color-mix(in srgb,var(--c) 10%,transparent)}}
.it p{{margin:4px 0 0;font-size:15.5px;color:var(--ink-2);max-width:66ch}}
.falta{{background:var(--card);border:1px solid var(--line-2);border-radius:10px;padding:12px 16px;margin:8px 0 0}}
.falta ul{{margin:6px 0 0;padding-left:20px}} .falta li{{margin:3px 0;font-size:15px;color:var(--ink-2)}}
.foot{{margin-top:40px;padding-top:16px;border-top:1px solid var(--line-2);font-size:14px;color:var(--ink-3)}}
/* a barra tem um botão a mais que as outras páginas e não cabe em 390px: o RSS sai, porque o mesmo
   link está no rodapé. Sem isto a página rolava de lado, o que nenhuma outra faz. */
@media (max-width:600px){{ .bar .crumb{{display:none}} .bar .rss{{display:none}} }}
</style>
<div class="bar">
  <a class="brand" href="{esc(prefix)}/"><span class="mark"></span>Atlas da República <span class="crumb">/ O que mudou</span></a>
  <span class="sp"></span>
  <a class="btn rss" href="{esc(prefix)}/feeds/novidades.xml">RSS</a>
  <a class="btn" href="{esc(prefix)}/metodologia/">Metodologia</a>
  <button class="btn" id="theme" aria-label="Alternar tema claro e escuro">◐ Tema</button>
</div>
<main>
  <div class="eyebrow">Atlas da República · o que mudou</div>
  <h1>O que mudou no Atlas</h1>
  <p class="lead">O Atlas muda todo dia: fonte nova, tela nova, conserto de coleta, verificação que passa a existir. Esta página sai do histórico do projeto, que é aberto — cada item abaixo é uma mudança de verdade, com a explicação que foi escrita quando ela aconteceu.</p>
  <div class="meta"><span>{d.get("total", 0)} mudanças registradas</span><span>atualizado em {esc(data_pt(hoje))}</span><span>{len(por_mes)} {"mês" if len(por_mes) == 1 else "meses"}</span></div>
  <h2>onde o Atlas está hoje</h2>
  <div class="nums">{cards}</div>
  {f'<div class="falta"><b>E o que ainda falta</b><ul>{falta_html}</ul></div>' if falta_html else ''}
  {"".join(blocos)}
  <div class="foot">
    <p>Os commits automáticos de atualização de dado ficam fora desta lista: o que eles mudam está no <a href="{esc(prefix)}/metodologia/">painel de frescor da metodologia</a>, que diz quando cada bloco foi lido pela última vez.</p>
    <p>Todo o código e todos os dados são abertos: <a href="https://github.com/culturabuilder/atlas-da-republica" rel="noopener">github.com/culturabuilder/atlas-da-republica</a>. Para acompanhar sem voltar aqui, há <a href="{esc(prefix)}/feeds/novidades.xml">feed RSS</a>.</p>
  </div>
</main>
<script>window.ATLAS_PREFIX="{prefix}";</script><script src="{esc(prefix)}/atlas-menu.js" defer></script>
</html>'''
    (out / "index.html").write_text(html_doc, encoding="utf-8")
    return [f"{base}{prefix}/novidades/"]


if __name__ == "__main__":
    G = json.load(open(ROOT / "build" / "graph.br.json", encoding="utf-8"))
    print(build(ROOT / "site", "", "https://atlasdarepublica.org", G))
