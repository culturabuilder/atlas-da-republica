#!/usr/bin/env python3
"""Área "Do zero": o governo explicado em palavras simples, com desenho, fotos e movimento.

Chamado por scripts/build_site.py: build(site_dir, prefix, base, G). Roda sozinho:
.venv/bin/python scripts/build_do_zero.py

Conteúdo: data/do-zero.yaml (14 capítulos) + data/do-zero-extra.yaml (curiosidades, números, linhas do tempo).
Cada capítulo ganha um visual: um diagrama em SVG, uma grade com as fotos dos ocupantes reais (as mesmas que o
site já serve em /img/) ou um número grande vindo do build.

A página é legível sem JavaScript e sem rolar: o movimento só acrescenta entrada suave e contagem de números,
e é desligado quando o sistema pede menos animação.
"""
import html, json, pathlib, re
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent


def esc(t):
    return html.escape(str(t or ""), quote=True)


def brl(v):
    v = float(v or 0)
    if v >= 1e12: return f"R$ {v/1e12:.2f} tri".replace(".", ",")
    if v >= 1e9: return f"R$ {v/1e9:.0f} bi"
    if v >= 1e6: return f"R$ {v/1e6:.0f} mi"
    return f"R$ {v:,.0f}".replace(",", ".")


def num(v):
    return f"{int(v):,}".replace(",", ".")


MINUSC = {"da", "de", "do", "das", "dos", "e", "a", "o", "em", "por", "para", "com", "ao", "aos", "à", "às"}


def tit(t):
    ws = str(t or "").lower().split()
    return " ".join(w if i and w in MINUSC else (w[:1].upper() + w[1:]) for i, w in enumerate(ws))


def curto(t, n=26):
    t = re.sub(r"\s+", " ", str(t or "")).strip()
    if len(t) <= n: return t
    corte = t[:n].rsplit(" ", 1)[0]
    return (corte if len(corte) >= n * 0.5 else t[:n]).rstrip(" ,.;:-") + "…"


PROG_CURTO = (
    ("REFINANCIAMENTO DA DIVIDA", "Refinanciamento da dívida"),
    ("SERVICO DA DIVIDA", "Juros e amortização da dívida"),
    ("PREVIDENCIA SOCIAL", "Previdência social"),
    ("TRANSFERENCIAS CONSTITUCIONAIS", "Repasses a estados e municípios"),
    ("GESTAO E MANUTENCAO DO PODER EXECUTIVO", "Folha e custeio do Executivo"),
    ("OUTROS ENCARGOS ESPECIAIS", "Outros encargos especiais"),
    ("BOLSA FAMILIA", "Bolsa Família"),
    ("ASSISTENCIA SOCIAL", "Assistência social (SUAS)"),
    ("FINANCIAMENTOS COM RETORNO", "Financiamentos com retorno"),
    ("ATENCAO ESPECIALIZADA A SAUDE", "Atenção especializada à saúde"),
    ("ATENCAO PRIMARIA A SAUDE", "Atenção primária à saúde"),
    ("EDUCACAO BASICA", "Educação básica"),
)


def prog_nome(nome):
    up = str(nome or "").upper()
    for chave, rot in PROG_CURTO:
        if chave in up: return rot
    limpo = re.sub(r"^OPERACOES ESPECIAIS:\s*", "", up)
    return curto(tit(limpo.split(":")[0]), 32)


def valor_fmt(valor, unidade=""):
    """Texto mostrado e, quando couber, o atributo que dispara a contagem."""
    u = str(unidade or "").lower()
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return esc(valor), ""
    if "rea" in u or "R$" in str(unidade or ""):
        return brl(v), ""
    if "%" in u or "por cento" in u:
        return (f"{v:.0f}%" if v == int(v) else f"{v:.1f}%".replace(".", ",")), ""
    if v >= 1000:
        return num(v), f' data-count="{v:.0f}"'
    return (str(int(v)) if v == int(v) else str(valor)), ""


def svg(body, vb="0 0 320 200", label=""):
    return (f'<svg class="viz" viewBox="{vb}" role="img" aria-label="{esc(label)}" '
            f'preserveAspectRatio="xMidYMid meet">{body}</svg>')


def fotos(pessoas, prefix, limite=12):
    cel = []
    for p in pessoas[:limite]:
        ini = "".join(w[0] for w in str(p.get("name") or "").split()[:2]).upper()
        img = (f'<img src="{prefix}/img/{p["id"]}.jpg" alt="{esc(p.get("name"))}" loading="lazy" width="64" height="64">'
               if p.get("_img") else f'<span class="ini">{esc(ini)}</span>')
        cel.append(f'<figure class="fc"><span class="ph">{img}</span>'
                   f'<figcaption>{esc(curto(p.get("cargo") or p.get("name"), 28))}</figcaption></figure>')
    return f'<div class="fotos">{"".join(cel)}</div>'


def visual_de(cid, G, prefix):
    N = (G or {}).get("nodes") or {}
    st = (G or {}).get("stats") or {}
    P = (G or {}).get("people") or {}

    def ocupantes(node_id, limite=12):
        n = N.get(node_id) or {}
        out = []
        for pid in (n.get("positions") or []):
            for p in (N.get(pid) or {}).get("people") or []:
                out.append({"id": p["id"], "name": p["name"], "cargo": p["name"],
                            "_img": (P.get(p["id"]) or {}).get("photo")})
        return out[:limite]

    if cid == "o-que-e-governo":
        pontos = "".join(f'<circle class="pp" cx="{28+i*26}" cy="46" r="7" style="--d:{i*.05}s"/>' for i in range(10))
        return svg('<g fill="none" stroke="currentColor" stroke-width="2">'
                   f'<g fill="currentColor">{pontos}</g>'
                   '<path class="dr" d="M160 62 L160 94" marker-end="url(#dza)"/>'
                   '<rect class="dr" x="72" y="100" width="176" height="76" rx="8" style="--d:.15s"/>'
                   '<path class="dr" d="M72 128 H248" style="--d:.25s"/>'
                   '<path class="dr" d="M112 128 V176" style="--d:.3s"/>'
                   '<path class="dr" d="M208 128 V176" style="--d:.3s"/></g>'
                   '<text x="160" y="28" class="lb" text-anchor="middle">você e mais de 150 milhões de eleitores</text>'
                   '<text x="92" y="156" class="lb" text-anchor="middle">saúde</text>'
                   '<text x="160" y="156" class="lb" text-anchor="middle">escola</text>'
                   '<text x="228" y="156" class="lb" text-anchor="middle">estrada</text>'
                   '<defs><marker id="dza" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" '
                   'orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="currentColor"/></marker></defs>',
                   "0 0 320 190", "Eleitores escolhem quem cuida dos serviços públicos")

    if cid == "tres-poderes":
        cores = [("Legislativo", "var(--leg)", 18), ("Executivo", "var(--exe)", 118), ("Judiciário", "var(--jud)", 218)]
        caixas = "".join(
            f'<g class="dr" style="--d:{i*.12}s"><rect x="{x}" y="56" width="84" height="64" rx="8" fill="none" '
            f'stroke="{c}" stroke-width="2"/><text x="{x+42}" y="93" class="lb" fill="{c}" text-anchor="middle">{n}</text></g>'
            for i, (n, c, x) in enumerate(cores))
        return svg(caixas +
                   '<g class="dr" fill="none" stroke="currentColor" stroke-width="1.5" stroke-dasharray="4 4" style="--d:.45s">'
                   '<path d="M60 52 C60 34, 160 34, 160 52" marker-end="url(#dzb)"/>'
                   '<path d="M160 52 C160 34, 260 34, 260 52" marker-end="url(#dzb)"/>'
                   '<path d="M260 124 C260 142, 60 142, 60 124" marker-end="url(#dzb)"/></g>'
                   '<text x="160" y="20" class="lb" text-anchor="middle">cada um confere o trabalho do outro</text>'
                   '<text x="160" y="160" class="lb sm" text-anchor="middle">escreve a lei · governa · julga</text>'
                   '<defs><marker id="dzb" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" '
                   'orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="currentColor"/></marker></defs>',
                   "0 0 320 172", "Os três poderes se fiscalizam")

    if cid == "o-que-faz-o-presidente":
        pr = (N.get("br-presidente-da-republica") or {}).get("people") or []
        out = ""
        if pr:
            p = pr[0]
            tem = (P.get(p["id"]) or {}).get("photo")
            img = (f'<img src="{prefix}/img/{p["id"]}.jpg" alt="{esc(p["name"])}" loading="lazy" width="96" height="96">'
                   if tem else "")
            out += (f'<figure class="solo"><span class="ph big">{img}</span><figcaption>{esc(p["name"])}'
                    f'<span>presidente da República</span></figcaption></figure>')
        vice = (N.get("br-vice-presidente-da-republica") or {}).get("people") or []
        lista = []
        for p in vice[:1]:
            lista.append({"id": p["id"], "name": p["name"], "cargo": "vice-presidente",
                          "_img": (P.get(p["id"]) or {}).get("photo")})
        for nid in ("br-casa-civil", "br-secretaria-geral-da-presidencia", "br-gabinete-de-seguranca-institucional"):
            for pid in ((N.get(nid) or {}).get("positions") or [])[:1]:
                for p in (N.get(pid) or {}).get("people") or []:
                    org = re.sub(r"\s+d[ao]\s+Presid[êe]ncia( da Rep[úu]blica)?$", "", (N.get(nid) or {}).get("name", ""))
                    lista.append({"id": p["id"], "name": p["name"], "cargo": org,
                                  "_img": (P.get(p["id"]) or {}).get("photo")})
        return out + (fotos(lista, prefix, 5) if lista else "") + '<p class="cap-viz">O presidente escolhe quem ocupa estes cargos, e pode trocar quando quiser.</p>'

    if cid == "ministro-e-ministerio":
        ms = []
        for n in N.values():
            if n.get("subtype") != "ministerio": continue
            for pid in (n.get("positions") or []):
                for p in (N.get(pid) or {}).get("people") or []:
                    pasta = re.sub(r"^Minist[ée]rio\s+(d[aeo]s?\s+)?", "", n["name"])
                    ms.append({"id": p["id"], "name": p["name"], "cargo": pasta,
                               "_img": (P.get(p["id"]) or {}).get("photo")})
        tot = len([n for n in N.values() if n.get("subtype") == "ministerio"])
        return fotos(ms, prefix, 12) + f'<p class="cap-viz">São {tot} ministérios hoje. Cada um cuida de uma área, e o presidente escolhe quem chefia.</p>'

    if cid == "quem-escreve-as-leis":
        cd = "".join(f'<circle class="pp" cx="{12+(i%29)*10.6}" cy="{34+(i//29)*10.6}" r="3.4" style="--d:{i*.003}s"/>' for i in range(513))
        sf = "".join(f'<circle class="pp" cx="{12+(i%29)*10.6}" cy="{150+(i//29)*10.6}" r="3.4" style="--d:{i*.004}s"/>' for i in range(81))
        return svg(f'<g fill="currentColor">{cd}</g><g fill="currentColor">{sf}</g>'
                   '<text x="12" y="22" class="lb">513 deputados · quanto mais gente no estado, mais deputados</text>'
                   '<text x="12" y="140" class="lb">81 senadores · três por estado, do maior ao menor</text>',
                   "0 0 320 190", "513 deputados e 81 senadores")

    if cid == "deputado-e-senador":
        return svg('<g class="dr" fill="none" stroke="currentColor" stroke-width="2">'
                   '<rect x="14" y="36" width="118" height="26" rx="6"/></g>'
                   '<g class="dr" style="--d:.2s" fill="none" stroke="currentColor" stroke-width="2">'
                   '<rect x="14" y="98" width="240" height="26" rx="6"/></g>'
                   '<text x="14" y="28" class="lb">deputado: 4 anos de mandato</text>'
                   '<text x="14" y="90" class="lb">senador: 8 anos de mandato</text>'
                   '<text x="14" y="148" class="lb sm">a Câmara troca todo mundo de uma vez; o Senado, por partes</text>',
                   "0 0 320 160", "Mandato de quatro e de oito anos")

    if cid == "como-nasce-uma-lei":
        passos = [("ideia", 10), ("Câmara", 78), ("Senado", 146), ("presidente", 214)]
        g = ""
        for i, (n, x) in enumerate(passos):
            g += (f'<g class="dr" style="--d:{i*.15}s"><rect x="{x}" y="52" width="60" height="32" rx="7" fill="none" '
                  f'stroke="currentColor" stroke-width="2"/><text x="{x+30}" y="72" class="lb" text-anchor="middle">{n}</text></g>')
            if i < 3:
                g += (f'<path class="dr" style="--d:{i*.15+.08}s" d="M{x+60} 68 H{x+74}" stroke="currentColor" '
                      f'stroke-width="1.8" marker-end="url(#dzc)"/>')
        return svg(g +
                   '<g class="dr" style="--d:.7s" fill="none" stroke="currentColor" stroke-width="1.8">'
                   '<path d="M244 84 V106"/><path d="M244 106 H110" marker-end="url(#dzc)"/></g>'
                   '<text x="286" y="72" class="lb" text-anchor="middle">vira lei</text>'
                   '<text x="110" y="124" class="lb" text-anchor="middle">se vetar, volta ao Congresso, que pode derrubar o veto</text>'
                   '<defs><marker id="dzc" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" '
                   'orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="currentColor"/></marker></defs>',
                   "0 0 320 140", "Caminho de um projeto até virar lei")

    if cid == "medida-provisoria":
        return svg('<g class="dr" fill="none" stroke="currentColor" stroke-width="2"><rect x="14" y="58" width="132" height="26" rx="6"/></g>'
                   '<g class="dr" style="--d:.25s" fill="none" stroke="currentColor" stroke-width="2" stroke-dasharray="5 4">'
                   '<rect x="152" y="58" width="132" height="26" rx="6"/></g>'
                   '<text x="14" y="48" class="lb">60 dias</text><text x="152" y="48" class="lb">mais 60, se prorrogada</text>'
                   '<text x="14" y="108" class="lb sm">vale desde o dia em que é publicada</text>'
                   '<text x="14" y="126" class="lb sm">se o Congresso não votar no prazo, ela perde a validade</text>',
                   "0 0 320 140", "Prazo de uma medida provisória")

    if cid == "juiz-e-supremo":
        stf = ocupantes("br-supremo-tribunal-federal", 11)
        return (fotos(stf, prefix, 11) if stf else "") + '<p class="cap-viz">Onze ministros julgam as questões sobre a Constituição. Cada um fica no cargo até os 75 anos.</p>'

    if cid == "quem-vigia-o-governo":
        orgs = [("Tribunal de Contas", 6), ("Ministério Público", 110), ("Controladoria", 214)]
        g = "".join(
            f'<g class="dr" style="--d:{i*.12}s"><circle cx="{x+50}" cy="54" r="24" fill="none" stroke="currentColor" stroke-width="2"/>'
            f'<path d="M{x+67} 71 l11 11" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" fill="none"/>'
            f'<text x="{x+50}" y="110" class="lb" text-anchor="middle">{n}</text></g>'
            for i, (n, x) in enumerate(orgs))
        return svg(g + '<text x="160" y="140" class="lb sm" text-anchor="middle">olham contas, conduta e uso do dinheiro público</text>',
                   "0 0 320 152", "Órgãos que fiscalizam o governo")

    if cid == "de-onde-vem-o-dinheiro":
        a = (G or {}).get("arrecadacao") or {}
        val = (a.get("anchor") or {}).get("value")
        if not val: return ""
        return (f'<div class="bignum" data-count="{int(val)}" data-prefix="R$ ">{brl(val)}</div>'
                f'<p class="cap-viz">arrecadados pela União em {a.get("year")}. '
                f'Cerca de {brl(a.get("rate_per_second"))} por segundo, quase tudo de impostos e contribuições.</p>')

    if cid == "para-onde-vai-o-dinheiro":
        try:
            pg = yaml.safe_load((ROOT / "data" / "generated" / "programas.yaml").read_text(encoding="utf-8")) or {}
        except Exception:
            return ""
        mp = [x for x in (pg.get("maiores_programas") or [])[:6] if x.get("pago")]
        if not mp: return ""
        tot = max(x["pago"] for x in mp)
        linhas = "".join(
            f'<div class="brow"><span class="bk">{esc(prog_nome(x.get("nome")))}</span>'
            f'<span class="bv">{brl(x["pago"])}</span>'
            f'<span class="bb"><i style="width:{100*x["pago"]/tot:.1f}%"></i></span></div>' for x in mp)
        return f'<div class="bars2">{linhas}</div><p class="cap-viz">Os seis maiores programas do orçamento federal, pelo que já foi pago no ano.</p>'

    if cid == "emenda-parlamentar":
        return svg('<g class="dr" fill="none" stroke="currentColor" stroke-width="2"><circle cx="36" cy="76" r="16"/></g>'
                   '<text x="36" y="112" class="lb" text-anchor="middle">parlamentar</text>'
                   '<g class="dr" style="--d:.2s" fill="none" stroke="currentColor" stroke-width="1.6">'
                   '<path d="M54 70 C110 40, 160 40, 214 52" marker-end="url(#dzd)"/>'
                   '<path d="M54 76 C110 76, 160 76, 214 80" marker-end="url(#dzd)"/>'
                   '<path d="M54 82 C110 112, 160 112, 214 106" marker-end="url(#dzd)"/></g>'
                   '<text x="262" y="56" class="lb" text-anchor="middle">hospital</text>'
                   '<text x="262" y="84" class="lb" text-anchor="middle">escola</text>'
                   '<text x="262" y="110" class="lb" text-anchor="middle">obra</text>'
                   '<defs><marker id="dzd" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" '
                   'orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="currentColor"/></marker></defs>',
                   "0 0 320 132", "Parlamentar destina dinheiro a obras e serviços")

    if cid == "como-acompanhar":
        c = st.get("cobertura") or {}
        return (f'<div class="bignum" data-count="{c.get("nos", 0)}">{num(c.get("nos", 0))}</div>'
                '<p class="cap-viz">órgãos, cargos e colegiados no Atlas, cada um com a norma que o cria e a fonte do dado. '
                'Tudo pode ser baixado e conferido.</p>')
    return ""


def build(site, prefix, base, G):
    src = ROOT / "data" / "do-zero.yaml"
    if not src.exists():
        print("aviso: data/do-zero.yaml não existe; área Do zero não gerada"); return None
    d = yaml.safe_load(src.read_text(encoding="utf-8")) or {}
    ex_p = ROOT / "data" / "do-zero-extra.yaml"
    ex = (yaml.safe_load(ex_p.read_text(encoding="utf-8")) if ex_p.exists() else {}) or {}
    ex_caps = {c.get("id"): c for c in (ex.get("capitulos") or [])}
    caps = d.get("capitulos") or []
    N = (G or {}).get("nodes") or {}

    def link_de(cap):
        l = str(cap.get("link") or "").strip()
        if not l: return None, None
        if l.startswith("/"): return f"{prefix}{l}", "ver no site"
        n = N.get(l)
        if not n: return f"{prefix}/#{l}", "ver no mapa"
        nome = n["name"] if len(n["name"]) <= 32 else (n.get("aliases") or [n["name"][:30] + "…"])[0]
        return f"{prefix}/#{l}", f"ver {nome} no mapa"

    itens = []
    for i, c in enumerate(caps, 1):
        cid = c.get("id")
        href, rot = link_de(c)
        e = ex_caps.get(cid) or {}
        palavras = "".join(
            f'<div class="w"><b>{esc(p.get("termo"))}</b><span>{esc(p.get("e"))}</span></div>'
            for p in (c.get("palavras") or []))
        cur = ""
        for x in (e.get("curiosidades") or []):
            fonte = (f'<a href="{esc(x.get("url"))}" target="_blank" rel="noopener">{esc(x.get("fonte"))}'
                     + (f", {esc(x.get('ano'))}" if x.get("ano") else "") + " ↗</a>") if x.get("url") else \
                    (f'<em>{esc(x.get("fonte"))}</em>' if x.get("fonte") else "")
            cur += f'<li><span>{esc(x.get("texto"))}</span>{fonte}</li>'
        nm = e.get("numero_marcante") or {}
        num_box = ""
        if nm.get("valor") is not None:
            mostrado, cnt = valor_fmt(nm.get("valor"), nm.get("unidade"))
            num_box = (f'<div class="nm"><div class="v"{cnt}>{mostrado}</div>'
                       f'<div class="l">{esc(nm.get("legenda"))}</div>'
                       + (f'<a href="{esc(nm.get("url"))}" target="_blank" rel="noopener">{esc(nm.get("fonte"))} ↗</a>'
                          if nm.get("url") else "") + "</div>")
        tl_html = "".join(f'<li><b>{esc(x.get("ano"))}</b><span>{esc(x.get("fato"))}</span></li>'
                          for x in (e.get("linha_do_tempo") or []))
        viz = visual_de(cid, G, prefix)
        lado = "b" if i % 2 == 0 else "a"
        no_atlas = ""
        if c.get("no_atlas"):
            no_atlas = f'<p class="no-atlas">{esc(c.get("no_atlas"))}' + (f' <a href="{href}">{esc(rot)} →</a>' if href else "") + "</p>"
        itens.append(f'''<section class="cap {lado}" id="{esc(cid)}">
  <div class="txt reveal">
    <div class="n">{i:02d} de {len(caps)}</div>
    <h2>{esc(c.get('pergunta'))}</h2>
    <p class="curta">{esc(c.get('resposta_curta'))}</p>
    <p>{esc(c.get('texto'))}</p>
    {f'<p class="ana"><b>É parecido com isto.</b> {esc(c.get("analogia"))}</p>' if c.get("analogia") else ''}
    {f'<div class="words">{palavras}</div>' if palavras else ''}
    {no_atlas}
  </div>
  <div class="viz-col reveal">{viz}{num_box}
    {f'<ol class="tl">{tl_html}</ol>' if tl_html else ''}
    {f'<div class="cur"><h3>Você sabia?</h3><ul>{cur}</ul></div>' if cur else ''}
  </div>
</section>''')

    faixa = ""
    for x in (ex.get("recordes") or []):
        if x.get("valor") is None: continue
        mostrado, cnt = valor_fmt(x.get("valor"), x.get("unidade"))
        faixa += (f'<div class="r"><div class="v"{cnt}>{mostrado}</div><div class="l">{esc(x.get("rotulo"))}</div>'
                  + (f'<a href="{esc(x.get("url"))}" target="_blank" rel="noopener">{esc(curto(str(x.get("fonte") or "").replace("build de ", ""), 34))} ↗</a>' if x.get("url") else "")
                  + "</div>")

    gloss = "".join(f'<div class="g"><b>{esc(t.get("termo"))}</b><span>{esc(t.get("e"))}</span></div>'
                    for t in (d.get("glossario") or []))
    indice = "".join(f'<li><a href="#{esc(c.get("id"))}"><b>{i:02d}</b><span>{esc(c.get("pergunta"))}</span></a></li>'
                     for i, c in enumerate(caps, 1))

    css = """
body{background:var(--bg);color:var(--ink);font:17px/1.6 var(--sans);margin:0;padding:0 20px;padding-block:24px 80px}
main{max-width:1080px;margin:0 auto}
.voltar{font-size:14px;color:var(--accent);text-decoration:none}
.hero{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,1fr);gap:28px;align-items:center;margin:18px 0 8px}
h1{font:800 clamp(38px,7vw,68px)/1 var(--disp);letter-spacing:-.03em;margin:0 0 10px;text-wrap:balance}
.sub{font-size:clamp(18px,2.4vw,23px);color:var(--ink-2);margin:0 0 12px;max-width:26ch;line-height:1.3}
.intro{font-size:16.5px;color:var(--ink-2);margin:0;max-width:52ch}
.hero .art{width:100%;max-width:340px;justify-self:center;color:var(--accent)}
.aviso{background:var(--accent-soft);border:1px solid var(--accent);border-radius:12px;padding:13px 15px;font-size:14px;line-height:1.5;color:var(--ink-2);margin:20px 0 8px}
.aviso b{color:var(--ink)}
.toc{list-style:none;padding:0;margin:22px 0 10px;display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:3px 14px}
.toc a{display:flex;gap:9px;align-items:baseline;text-decoration:none;color:var(--ink-2);font-size:15px;padding:6px;border-radius:8px}
.toc a:hover{background:var(--panel);color:var(--ink)}
.toc b{font:500 12px var(--mono);color:var(--ink-3)}
.cap{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:24px 40px;align-items:start;padding:44px 0;border-top:1px solid var(--line-2)}
.cap.b .txt{order:2}.cap.b .viz-col{order:1}
.cap>*{min-width:0}.cap .txt *{min-width:0}
.cap .n{font:500 12px var(--mono);color:var(--ink-3);letter-spacing:.1em;margin-bottom:8px}
.cap h2{font:700 clamp(25px,3.4vw,34px)/1.12 var(--disp);margin:0 0 10px;text-wrap:balance;letter-spacing:-.02em}
.cap p{margin:0 0 13px;max-width:56ch}
.cap h2,.cap p,.words b,.words span,.gloss b,.gloss span,.cur span{overflow-wrap:anywhere}
.curta{font-size:19.5px;color:var(--ink);font-weight:600;line-height:1.4}
.ana{background:var(--panel);border-left:3px solid var(--accent);border-radius:0 10px 10px 0;padding:11px 13px;font-size:16px;color:var(--ink-2)}
.ana b{color:var(--ink)}
.words{display:grid;gap:6px;margin:0 0 13px}
.words .w{display:grid;grid-template-columns:minmax(0,auto) minmax(0,1fr);gap:4px 10px;font-size:14.5px;align-items:baseline}
.words b{font-family:var(--mono);font-size:13px;color:var(--accent)}
.words span{color:var(--ink-2)}
.no-atlas{font-size:15px;color:var(--ink-3)}
.no-atlas a{color:var(--accent);text-decoration:none;border-bottom:1px solid var(--line-2)}
.viz{width:100%;height:auto;display:block;color:var(--ink-2);margin:0 0 10px}
.viz .lb{font-family:var(--mono);font-size:8.5px;fill:var(--ink-3)}
.viz .lb.sm{font-size:7.5px}
.cap-viz{font-size:14px;color:var(--ink-3);margin:2px 0 14px;max-width:46ch}
.fotos{display:grid;grid-template-columns:repeat(auto-fill,minmax(76px,1fr));gap:10px;margin:0 0 12px}
.fc{margin:0;text-align:center}
.fc .ph{width:64px;height:64px;margin:0 auto 5px;border-radius:50%;overflow:hidden;background:var(--accent-soft);color:var(--accent);display:flex;align-items:center;justify-content:center;border:1px solid var(--line-2)}
.fc .ph img{width:64px;height:64px;object-fit:cover;display:block}
.fc .ini{font:600 16px var(--mono)}
.fc{min-width:0}
.fc figcaption{font-size:11.5px;color:var(--ink-3);line-height:1.25;overflow-wrap:anywhere;hyphens:auto}
.fotos>*{min-width:0}
.solo{margin:0 0 14px;display:flex;gap:14px;align-items:center}
.solo .ph.big{width:96px;height:96px;border-radius:50%;overflow:hidden;flex:none;border:2px solid var(--accent);display:flex;align-items:center;justify-content:center;background:var(--accent-soft)}
.solo .ph.big img{width:96px;height:96px;object-fit:cover}
.solo figcaption{font-size:16px;font-weight:600}
.solo figcaption span{display:block;font-weight:400;font-size:13.5px;color:var(--ink-3)}
.bignum{font:800 clamp(40px,7vw,62px)/1 var(--disp);letter-spacing:-.03em;color:var(--accent);font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
.bars2{display:grid;gap:9px;margin:0 0 10px}
.bars2 .brow{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:2px 10px;font-size:13.5px;align-items:baseline}
.bars2 .bk{overflow-wrap:anywhere}
.bars2 .bv{font-family:var(--mono);font-size:12px;color:var(--ink-3);text-align:right}
.bars2 .bb{grid-column:1/-1;height:8px;background:var(--line-2);border-radius:4px;overflow:hidden}
.bars2 .bb i{display:block;height:100%;background:var(--accent);transition:width .9s ease}
.nm{background:var(--panel);border:1px solid var(--line-2);border-radius:12px;padding:14px 16px;margin:0 0 12px}
.nm .v{font:800 clamp(26px,3vw,34px)/1 var(--disp);overflow-wrap:anywhere;color:var(--accent);letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.nm .l{font-size:14px;color:var(--ink-2);margin-top:4px}
.nm a{font-size:12px;color:var(--ink-3);text-decoration:none;display:inline-block;margin-top:6px}
.tl{list-style:none;padding:0;margin:0 0 12px;border-left:2px solid var(--line-2)}
.tl li{display:grid;grid-template-columns:50px minmax(0,1fr);gap:10px;padding:5px 0 5px 12px;font-size:14px;color:var(--ink-2)}
.tl b{font:500 13px var(--mono);color:var(--accent)}
.cur{background:var(--panel);border:1px solid var(--line-2);border-radius:12px;padding:13px 15px}
.cur h3{font:600 13px var(--mono);letter-spacing:.08em;text-transform:uppercase;color:var(--ink-3);margin:0 0 8px}
.cur ul{list-style:none;padding:0;margin:0;display:grid;gap:10px}
.cur li{font-size:14.5px;color:var(--ink-2);line-height:1.45}
.cur li a,.cur li em{display:block;font:400 11.5px var(--mono);color:var(--ink-3);text-decoration:none;font-style:normal;margin-top:3px}
.cur li a:hover{color:var(--accent)}
.recordes{margin:40px 0 0;padding:22px 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
.recordes h2{font:700 22px/1.2 var(--disp);margin:0 0 14px}
.recordes .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(168px,1fr));gap:16px}
.recordes .r .v{font:800 clamp(22px,2.4vw,28px)/1 var(--disp);color:var(--ink);letter-spacing:-.02em;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
.recordes .r .l{font-size:13.5px;color:var(--ink-2);margin-top:3px}
.recordes .r a{font:400 11px var(--mono);color:var(--ink-3);text-decoration:none}
.gloss{margin-top:34px}
.gloss h2{font:700 22px/1.2 var(--disp);margin:0 0 10px}
.gloss .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(265px,1fr));gap:8px 18px}
.gloss .g{font-size:15px}
.gloss .g b{display:block;font-family:var(--mono);font-size:13.5px;color:var(--accent)}
.gloss .g span{color:var(--ink-2)}
.fim{margin-top:30px;padding-top:18px;border-top:1px solid var(--line);font-size:15px;color:var(--ink-2)}
.fim a{color:var(--accent)}
.prog{position:fixed;left:0;top:0;height:3px;background:var(--accent);width:0;z-index:20}
html.js .reveal{opacity:0;transform:translateY(14px)}
html.js .reveal.on{opacity:1;transform:none;transition:opacity .5s ease,transform .5s ease}
html.js .dr{opacity:0}html.js .on .dr{opacity:1;transition:opacity .5s ease;transition-delay:var(--d,0s)}
html.js .pp{opacity:0}html.js .on .pp{opacity:.9;transition:opacity .35s ease;transition-delay:var(--d,0s)}
@media (prefers-reduced-motion:reduce){html.js .reveal,html.js .dr,html.js .pp{opacity:1;transform:none;transition:none}.bars2 .bb i{transition:none}}
@media (max-width:820px){
  .hero{grid-template-columns:1fr;gap:14px}.hero .art{max-width:280px}
  .cap{grid-template-columns:1fr;gap:16px;padding:34px 0}
  .cap.b .txt{order:0}.cap.b .viz-col{order:1}
}
"""

    js = """
(function(){
  var red = matchMedia('(prefers-reduced-motion: reduce)').matches;
  var els = document.querySelectorAll('.reveal');
  function barras(root){ root.querySelectorAll('.bars2 .bb i').forEach(function(i){ var w=i.style.width; i.style.width='0'; requestAnimationFrame(function(){ i.style.width=w; }); }); }
  function conta(root){
    root.querySelectorAll('[data-count]').forEach(function(el){
      var alvo = parseFloat(el.getAttribute('data-count')); if (!isFinite(alvo)) return;
      var fim = el.textContent, t0 = performance.now(), dur = 900;
      function passo(t){ var k = Math.min(1, (t - t0) / dur); var v = Math.round(alvo * (1 - Math.pow(1 - k, 3)));
        el.textContent = (el.dataset.prefix || '') + v.toLocaleString('pt-BR');
        if (k < 1) requestAnimationFrame(passo); else el.textContent = fim; }
      requestAnimationFrame(passo);
    });
  }
  if (!('IntersectionObserver' in window) || red) {
    els.forEach(function(e){ e.classList.add('on'); });
  } else {
    var io = new IntersectionObserver(function(es){
      es.forEach(function(en){ if (!en.isIntersecting) return; en.target.classList.add('on'); conta(en.target); barras(en.target); io.unobserve(en.target); });
    }, { rootMargin: '0px 0px -12% 0px', threshold: 0.12 });
    els.forEach(function(e){ io.observe(e); });
  }
  var prog = document.getElementById('prog');
  addEventListener('scroll', function(){
    var h = document.documentElement.scrollHeight - innerHeight;
    prog.style.width = (h > 0 ? (scrollY / h) * 100 : 0) + '%';
  }, { passive: true });
})();
"""

    page = f'''<!doctype html>
<html lang="pt-BR">
<head>
<script>try{{var _t=localStorage.getItem('atlas-theme')||'dark';if(_t!=='auto')document.documentElement.dataset.theme=_t}}catch(e){{document.documentElement.dataset.theme='dark'}}document.documentElement.classList.add('js')</script>
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
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@600;700;800&family=JetBrains+Mono:wght@400;500&family=Source+Sans+3:wght@400;600&display=swap" media="print" onload="this.media='all'">
<link rel="stylesheet" href="{prefix}/atlas.css">
<style>{css}</style>
</head>
<body>
<div class="prog" id="prog" aria-hidden="true"></div>
<main>
<a class="voltar" href="{prefix}/">← Atlas da República</a>
<div class="hero">
  <div>
    <h1>{esc(d.get('titulo'))}</h1>
    <p class="sub">{esc(d.get('subtitulo'))}</p>
    <p class="intro">{esc(d.get('intro'))}</p>
  </div>
  <svg class="art" viewBox="0 0 300 190" role="img" aria-label="Do povo para os três poderes">
    <g fill="none" stroke="currentColor" stroke-width="2">
      <circle cx="150" cy="36" r="20"/>
      <path d="M150 56 V86"/><path d="M60 86 H240"/><path d="M60 86 V96"/><path d="M150 86 V96"/><path d="M240 86 V96"/>
      <rect x="26" y="96" width="68" height="0" rx="6"><animate attributeName="height" to="50" dur=".7s" fill="freeze" begin=".2s"/></rect>
      <rect x="116" y="96" width="68" height="0" rx="6"><animate attributeName="height" to="50" dur=".7s" fill="freeze" begin=".35s"/></rect>
      <rect x="206" y="96" width="68" height="0" rx="6"><animate attributeName="height" to="50" dur=".7s" fill="freeze" begin=".5s"/></rect>
    </g>
    <text x="150" y="41" text-anchor="middle" style="font:600 11px var(--sans);fill:currentColor">povo</text>
    <g style="font:600 10px var(--sans);fill:var(--ink-2)" text-anchor="middle">
      <text x="60" y="126">faz as leis</text><text x="150" y="126">governa</text><text x="240" y="126">julga</text></g>
    <text x="60" y="166" text-anchor="middle" style="font:500 9px var(--mono);fill:var(--ink-3)">LEGISLATIVO</text>
    <text x="150" y="166" text-anchor="middle" style="font:500 9px var(--mono);fill:var(--ink-3)">EXECUTIVO</text>
    <text x="240" y="166" text-anchor="middle" style="font:500 9px var(--mono);fill:var(--ink-3)">JUDICIÁRIO</text>
  </svg>
</div>
<div class="aviso"><b>Este projeto é apartidário.</b> {esc(d.get('neutralidade'))}</div>
<ol class="toc">{indice}</ol>
{''.join(itens)}
{f'<section class="recordes"><h2>Números do governo federal</h2><div class="grid">{faixa}</div></section>' if faixa else ''}
<div class="gloss"><h2>Palavras que aparecem no site</h2><div class="grid">{gloss}</div></div>
<p class="fim">Quando quiser ir além, a área <a href="{prefix}/como-funciona/">Como funciona a República</a> mostra a mesma coisa pelo mapa, em nove minutos. Todos os números vêm de fontes oficiais, listadas na <a href="{prefix}/metodologia/">metodologia</a>, e podem ser baixados em <a href="{prefix}/dados/">dados abertos</a>.</p>
</main>
<script>{js}</script>
<script>window.ATLAS_PREFIX="{prefix}";</script>
<script src="{prefix}/atlas-menu.js" defer></script>
</body>
</html>'''
    d_out = site / "do-zero"; d_out.mkdir(parents=True, exist_ok=True)
    (d_out / "index.html").write_text(page, encoding="utf-8")
    ncur = sum(len((ex_caps.get(c.get("id")) or {}).get("curiosidades") or []) for c in caps)
    print(f"   do-zero/: {len(caps)} capítulos, {len(d.get('glossario') or [])} termos, {ncur} curiosidades")
    return f"{base}{prefix}/do-zero/"


if __name__ == "__main__":
    G = json.load(open(ROOT / "build" / "graph.br.json", encoding="utf-8"))
    build(ROOT / "site", "", "https://atlasdarepublica.org", G)
