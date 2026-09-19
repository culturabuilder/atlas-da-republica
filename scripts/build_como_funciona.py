#!/usr/bin/env python3
"""Gera a área educativa /como-funciona/ a partir de data/como-funciona.yaml, data/glossario.yaml e build/graph.br.json.
Chamado por scripts/build_site.py: build(site_dir, prefix, base, G). Também roda sozinho para teste: .venv/bin/python scripts/build_como_funciona.py
"""
import json, re, pathlib, html, math, unicodedata, datetime
import yaml
ROOT = pathlib.Path(__file__).resolve().parent.parent
esc = html.escape

def norm(s): return re.sub(r"[^a-z0-9 ]", "", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()).strip()
def fmt_date(d):
    if not d: return ""
    y, m, dd = str(d)[:10].split("-"); M = ["jan","fev","mar","abr","mai","jun","jul","ago","set","out","nov","dez"]
    return f"{int(dd)} {M[int(m)-1]} {y}"
def brl(v):
    if v >= 1e9: return f"R$ {v/1e9:.1f} bi".replace(".", ",")
    if v >= 1e6: return f"R$ {v/1e6:.0f} mi"
    return f"R$ {v:,.0f}".replace(",", ".")

def markup(text, prefix):
    t = esc(text.strip())
    t = re.sub(r"\(\(([^|)]+)\|([^)]+)\)\)", lambda m: f'<a class="nl" href="{prefix}/#{m.group(1)}" data-id="{m.group(1)}">{m.group(2)}</a>', t)
    t = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", lambda m: f'<button class="gl" type="button" data-term="{m.group(1)}">{m.group(2)}</button>', t)
    t = re.sub(r"\[\[([^\]]+)\]\]", lambda m: f'<button class="gl" type="button" data-term="{m.group(1)}">{m.group(1)}</button>', t)
    return t

def live_widgets(G, prefix):
    N, P = G["nodes"], G.get("people", {})
    st = G["stats"]; img = f"{prefix}/img/"
    def person(p, extra=""):
        if not p: return ""
        pid = p.get("id"); rec = P.get(pid) or {}
        av = f'<img src="{img}{pid}.jpg" alt="" loading="lazy">' if rec.get("photo") else f'<span class="ini">{esc("".join(w[0] for w in (p.get("name") or "?").split()[:2]))}</span>'
        return f'<div class="pl"><a class="av" href="{prefix}/#{pid}" aria-label="{esc(p.get("name") or "")}">{av}</a><div><b>{esc(p.get("name") or "")}</b><span>{extra}</span></div></div>'
    def face(p):
        pid = p.get("id"); rec = P.get(pid) or {}
        inner = f'<img src="{img}{pid}.jpg" alt="{esc(p.get("name") or "")}" loading="lazy">' if rec.get("photo") else f'<span class="ini">{esc("".join(w[0] for w in (p.get("name") or "?").split()[:2]))}</span>'
        return f'<a href="{prefix}/#{pid}" title="{esc(p.get("name") or "")}">{inner}</a>'
    W = {}
    W["stats"] = f'<h3>O mapa hoje</h3><div class="row"><div><div class="big">{st["nodes"]}</div>órgãos e cargos</div><div><div class="big">{st["edges"]}</div>ligações com base legal</div><div><div class="big">{st["seats_filled"]}<small>de {st["seats_total"]}</small></div>cadeiras com ocupante conhecido</div></div><div class="src">Atualizado em {fmt_date(st.get("generated_at"))}</div>'
    # ministros
    ms = sorted([n for n in N.values() if n["type"] == "dept_head" and n["name"].startswith("Ministro de Estado") and n.get("people")], key=lambda n: n["name"])
    faces = "".join(face(n["people"][0]) for n in ms)
    W["ministros"] = f'<h3>Os ministros de Estado hoje · {len(ms)}</h3><div class="faces">{faces}</div><div class="src">Toque numa foto para abrir a pessoa na roda. Fonte: Planalto, conferido em página oficial.</div>'
    # presidentes das casas
    pc = (N["br-presidente-da-camara-dos-deputados"].get("people") or [None])[0]; ps = (N["br-presidente-do-senado-federal"].get("people") or [None])[0]
    def since(p): e = (p or {}).get("entry") or {}; return f"desde {fmt_date(e.get('date'))}" + (f" · mandato até {fmt_date(e.get('term_end'))}" if e.get("term_end") else "")
    W["presidentes_casas"] = f'<h3>Quem preside as Casas</h3>{person(pc, "Presidente da Câmara · " + since(pc))}{person(ps, "Presidente do Senado · " + since(ps))}<div class="src">Fonte: Câmara e Senado, dados abertos.</div>'
    # composição partidária
    from collections import Counter
    def bars(people, total):
        c = Counter(p.get("party") or "—" for p in people); top = c.most_common(8); mx = top[0][1] if top else 1
        return f'<div class="bars">' + "".join(f'<span class="k">{esc(k)}</span><span class="b"><i style="width:{round(100*v/mx)}%"></i></span><span class="v">{v}</span>' for k, v in top) + f'</div><div class="src">{len(people)} de {total} · {len(c)} partidos</div>'
    W["casas_composicao"] = f'<h3>Câmara, por partido</h3>{bars(N["br-deputado-federal"].get("people") or [], 513)}<h3 style="margin-top:12px">Senado, por partido</h3>{bars(N["br-senador"].get("people") or [], 81)}'
    # STF
    stf = N["br-supremo-tribunal-federal-ministro"]; ppl = stf.get("people") or []; dated = [p for p in ppl if p.get("started_at")]
    old = min(dated, key=lambda p: p["started_at"]) if dated else None; new = max(dated, key=lambda p: p["started_at"]) if dated else None
    vac = (stf.get("seats") or 11) - len(ppl)
    W["stf"] = f'<h3>O STF hoje</h3><div class="row"><div><div class="big">{len(ppl)}<small>de {stf.get("seats") or 11}</small></div>ministros{f" · {vac} vaga aberta" if vac == 1 else (f" · {vac} vagas abertas" if vac else "")}</div></div>' + (person(old, f"mais antigo · desde {fmt_date(old['started_at'])} · nomeado por {(old.get('entry') or {}).get('by_person') or 'Presidente'}") if old else "") + (person(new, f"mais recente · desde {fmt_date(new['started_at'])} · nomeado por {(new.get('entry') or {}).get('by_person') or 'Presidente'}") if new else "") + '<div class="src">Fonte: STF, composição atual.</div>'
    # TCU e PGR
    tcu = N.get("br-ministro-do-tcu") or {}; pgr = (N["br-procurador-geral-da-republica"].get("people") or [None])[0]
    W["tcu_pgr"] = f'<h3>Quem vigia, hoje</h3><div class="row"><div><div class="big">{len(tcu.get("people") or [])}<small>de {tcu.get("seats") or 9}</small></div>ministros do TCU</div></div>{person(pgr, "Procurador-Geral da República · " + since(pgr) + " · mandato de 2 anos")}<div class="src">Fonte: TCU e MPF, páginas oficiais.</div>'
    # sabatinas
    sabs = [c for c in G.get("changes", []) if c.get("kind") == "sabatina" and c.get("result") == "APROVADA_NO_PLENARIO"]
    last = sabs[0] if sabs else None
    W["sabatinas_ultima"] = f'<h3>Sabatinas desde 2023</h3><div class="row"><div><div class="big">{st.get("sabatinas", 0)}</div>indicações enviadas ao Senado</div><div><div class="big">{st.get("seats_sabatina", 0)}</div>cadeiras que passam por sabatina</div></div>' + (f'<div style="margin-top:8px">Última aprovada: <b>{esc(last.get("personName") or "")}</b> para <a href="{prefix}/#{last["positionId"]}">{esc(last.get("positionName") or "")}</a>, em {fmt_date(last["date"])}{", por " + str(last["votes"][0]) + " a " + str(last["votes"][1]) if last.get("votes") and last["votes"][0] is not None else ""}.</div>' if last else "") + '<div class="src">Fonte: Senado, mensagens (MSF) e votações.</div>'
    # distância
    W["distancia"] = f'<h3>Do seu voto ao presidente da Anatel</h3><ol class="path" style="margin-top:4px"><li>Você elege o <b>Presidente da República</b><small>CF/88 art. 77</small></li><li>O Presidente <b>indica</b> o presidente da Anatel<small>Lei 9.472/1997 art. 23</small></li><li>O Senado <b>sabatina e aprova</b> por maioria<small>CF/88 art. 52, III, f</small></li><li>Mandato de <b>5 anos</b>, sem demissão pelo Presidente<small>Lei 9.986/2000 arts. 6º e 9º</small></li></ol>'
    # orçamento
    year = str(datetime.date.today().year)
    mins = [n for n in N.values() if n.get("subtype") == "ministerio" and (n.get("budget") or {}).get(year)]
    if not mins: year = str(datetime.date.today().year - 1); mins = [n for n in N.values() if n.get("subtype") == "ministerio" and (n.get("budget") or {}).get(year)]
    mins.sort(key=lambda n: n["budget"][year].get("empenhado") or 0, reverse=True)
    total = sum(n["budget"][year].get("empenhado") or 0 for n in mins); mx = (mins[0]["budget"][year].get("empenhado") or 1) if mins else 1
    rows = "".join(f'<span class="k"><a href="{prefix}/#{n["id"]}" style="color:inherit;text-decoration:none">{esc((n.get("aliases") or [n["name"]])[0] if len((n.get("aliases") or [""])[0]) <= 14 else n["name"].replace("Ministério ", ""))}</a></span><span class="b"><i style="width:{round(100*(n["budget"][year].get("empenhado") or 0)/mx)}%"></i></span><span class="v">{brl(n["budget"][year].get("empenhado") or 0)}</span>' for n in mins[:8])
    W["orcamento_top"] = f'<h3>Empenhado em {year}, por ministério</h3><div class="bars">{rows}</div><div class="src">Total dos ministérios: {brl(total)} · inclui as entidades vinculadas · Portal da Transparência</div>'
    budget_scale = {n["id"]: round(1 + 1.8 * math.sqrt((n["budget"][year].get("empenhado") or 0) / mx), 2) for n in mins}
    # última mudança e notícia
    chg = (G.get("changes") or [None])[0]; nw = (G.get("news") or [None])[0]
    KIND = {"sabatina": "sabatina", "posse": "posse", "nomeacao": "nomeação", "exoneracao": "exoneração", "designacao": "designação", "entrada": "entrada", "saida": "saída"}
    W["ultima"] = '<h3>Agora mesmo no Atlas</h3>' + (f'<div>Mudança mais recente: <b>{esc(chg.get("personName") or "")}</b>, {KIND.get(chg["kind"], chg["kind"])} em <a href="{prefix}/#{chg["positionId"]}">{esc(chg.get("positionName") or "")}</a>, {fmt_date(chg["date"])}.</div>' if chg else "") + (f'<div style="margin-top:6px">Notícia mais recente: <a href="{prefix}/#news:{nw["id"]}">{esc(nw["title"])}</a> <small style="font-family:var(--mono);color:var(--ink-3)">{esc(nw.get("publication") or "")} · {fmt_date(nw["date"])}</small></div>' if nw else "") + f'<div class="src">Fontes: DOU, Senado, páginas oficiais e {st.get("news_sources", 8)} veículos, lidos todo dia.</div>'
    # transição 2027
    free = sum(1 for n in N.values() if n["type"] == "dept_head" for p in (n.get("people") or []) if ((p.get("entry") or {}).get("term_note") or "").startswith("livre"))
    fixed = sum(1 for n in N.values() if n["type"] == "dept_head" for p in (n.get("people") or []) if ((p.get("entry") or {}).get("term_end") or "") > "2027-01-01")
    life = sum(1 for n in N.values() if n["type"] == "dept_head" for p in (n.get("people") or []) if "vital" in ((p.get("entry") or {}).get("term_note") or ""))
    W["transicao"] = f'<h3>Transição de 2027</h3><div class="row"><div><div class="big">{free + 2}</div>cadeiras que trocam com o novo Presidente</div><div><div class="big">{fixed}</div>mandatos fixos que atravessam a posse</div><div><div class="big">{life}</div>cargos vitalícios</div></div><div class="src">Contagem sobre os ocupantes conhecidos hoje. A aba Transição da roda acompanha cadeira a cadeira.</div>'
    return W, budget_scale

def build(site, prefix, base, G):
    cf = yaml.safe_load(open(ROOT / "data" / "como-funciona.yaml", encoding="utf-8"))
    gl = yaml.safe_load(open(ROOT / "data" / "glossario.yaml", encoding="utf-8")) or {}
    W, budget_scale = live_widgets(G, prefix)
    N = G["nodes"]
    html_parts = []
    chapters = cf["chapters"]
    toc = "".join(f'<li><a href="#{c["id"]}"><b>{i:02d}</b><span>{esc(c["title"])}</span></a></li>' for i, c in enumerate(chapters))
    html_parts.append(f'<header class="hero"><div class="eyebrow">Atlas da República · área educativa</div><h1>{esc(cf["title"])}</h1><p>{esc(cf["subtitle"])}</p><div class="meta"><span>{len(chapters)} capítulos</span><span>{cf.get("minutes", 9)} minutos</span><span>com dados de hoje</span></div><a class="cta" href="#c0">Começar ↓</a><ol class="toc">{toc}</ol></header>')
    for i, c in enumerate(chapters):
        steps = []
        for s in c["steps"]:
            wheel = s.get("wheel") or {}
            for k in ("nodes", "select"):
                ids = wheel.get(k) if k == "nodes" else ([wheel[k]] if wheel.get(k) else [])
                for nid in ids or []:
                    if nid not in N: print(f"aviso: {c['id']}: nó inexistente {nid}")
            body = f'<p>{markup(s["text"], prefix)}</p>'
            if s.get("cite"): body += f'<cite>{esc(s["cite"])}</cite>'
            if s.get("live") and s["live"] in W: body += f'<div class="live" data-live="{s["live"]}">{W[s["live"]]}</div>'
            if s.get("try"): body += f'<div class="try" data-try="{s["try"]}"></div>'
            steps.append(f'<div class="step" data-state=\'{json.dumps(wheel, ensure_ascii=False).replace("&", "&amp;").replace("\'", "&#39;")}\'>{body}</div>')
        html_parts.append(f'<section class="chapter" id="{c["id"]}" data-title="{esc(c["title"])}" data-short="{i:02d} {esc(c["title"])}"><div class="eyebrow">Capítulo {i}</div><h2>{esc(c["title"])}</h2><p class="q">{esc(c["question"])}</p>{"".join(steps)}</section>')
    html_parts.append(f'<div class="end"><div class="eyebrow">Fim da visita</div><p style="margin:8px 0 0">Tudo o que você leu vem dos mesmos dados da roda: cada órgão com a norma que o criou, cada cadeira com a fonte do nome. Quando algo mudar no Diário Oficial ou no Senado, muda aqui também.</p><a class="cta" href="{prefix}/">Abrir a roda completa →</a></div>')
    tpl = (ROOT / "web" / "como-funciona.html").read_text(encoding="utf-8")
    data = {"glossary": gl, "home": f"{prefix}/", "budget_scale": budget_scale}
    out = tpl.replace("<!--CF_CONTENT-->", "\n".join(html_parts)).replace("<!--CF_DATA-->", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    out = out.replace('<script src="graph.br.js" defer></script>', f'<script src="{prefix}/graph.br.js" defer></script>').replace('<script src="atlas.js" defer></script>', f'<script src="{prefix}/atlas.js" defer></script>').replace('<link rel="stylesheet" href="atlas.css">', f'<link rel="stylesheet" href="{prefix}/atlas.css">').replace('<a class="brand" href="/">', f'<a class="brand" href="{prefix}/">')
    desc = cf["subtitle"]
    out = out.replace("<title>Como funciona a República · Atlas da República</title>", f'<title>Como funciona a República · Atlas da República</title>\n<meta name="description" content="{esc(desc)}">\n<link rel="canonical" href="{base}/como-funciona/">\n<meta property="og:title" content="Como funciona a República"><meta property="og:description" content="{esc(desc)}"><meta property="og:url" content="{base}/como-funciona/"><meta property="og:type" content="article">', 1)
    d = site / "como-funciona"; d.mkdir(parents=True, exist_ok=True)
    (d / "index.html").write_text(out, encoding="utf-8")
    return f"{base}/como-funciona/"

if __name__ == "__main__":
    G = json.load(open(ROOT / "build" / "graph.br.json", encoding="utf-8"))
    print(build(ROOT / "site", "", "http://localhost:8765", G))
