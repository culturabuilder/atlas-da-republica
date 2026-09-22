#!/usr/bin/env python3
"""Gera a página /comparar/ (rankings e comparador lado a lado de parlamentares) a partir de build/graph.br.json e build/people/*.json.
Chamado por scripts/build_site.py: build(site_dir, prefix, base, G). Também roda sozinho para teste: .venv/bin/python scripts/build_comparar.py
"""
import json, pathlib, html, datetime, statistics
ROOT = pathlib.Path(__file__).resolve().parent.parent
esc = html.escape

HOUSE_POS = {"br-deputado-federal": "camara", "br-senador": "senado"}
# métricas cuja mediana vem pronta de G["stats"]["gabinetes"][casa]["medianas"] (chave lá → chave aqui)
STATS_MEDIANS = {"assessores": "assessores", "folha_mensal_estimada": "folha_mensal", "cota": "cota_total", "custo_ano_total": "custo_ano_total"}
MEDIAN_KEYS = ["custo_ano_total", "presenca_pct", "votacoes", "cota_total", "cota_media_mes", "assessores", "folha_mensal", "emendas_ano", "emendas_top15_pct",
               "patrimonio_2018", "patrimonio_2022", "variacao_real_pct", "receita_2022", "n_sinais"]

def r2(v):
    if v is None: return None
    try: v = float(v)
    except (TypeError, ValueError): return None
    return int(v) if v == int(v) else round(v, 2)

def house_of(rec):
    for p in rec.get("positions") or []:
        if p.get("id") in HOUSE_POS: return HOUSE_POS[p["id"]]
    return None

def person_row(pid, rec, d, year):
    casa = house_of(rec)
    a = d.get("activity") or {}; g = d.get("gabinete") or {}; e = d.get("emendas") or {}; p = d.get("patrimonio") or {}; do = d.get("doadores") or {}
    cota = a.get("cota") or {}; custo = g.get("custo_ano") or {}
    cota_total = cota.get("total") if cota else custo.get("cota")
    if cota:
        media = cota.get("media_mes")
    elif custo.get("cota") and custo.get("meses"):
        media = custo["cota"] / custo["meses"]
    else: media = None
    anos = e.get("anos") or {}; v22 = e.get("votos_2022") or {}
    pat18 = (p.get("2018") or {}).get("total"); pat22 = (p.get("2022") or {}).get("total")
    return {
        "id": pid, "nome": rec.get("name"), "casa": casa, "partido": rec.get("party"), "uf": rec.get("uf"), "foto": bool(rec.get("photo")),
        "presenca_pct": r2(a.get("pct")), "votacoes": a.get("votacoes_nominais"),
        "cota_total": r2(cota_total), "cota_media_mes": r2(media),
        "assessores": g.get("assessores"), "folha_mensal": r2(g.get("folha_mensal") if g.get("folha_mensal") is not None else g.get("folha_mensal_estimada")),
        "custo_ano_total": r2(custo.get("total")),
        "emendas_ano": r2((anos.get(str(year)) or {}).get("empenhado")),
        "emendas_top15_pct": r2(v22.get("emendas_nos_top15_pct")),
        "patrimonio_2018": r2(pat18), "patrimonio_2022": r2(pat22), "variacao_real_pct": r2(p.get("variacao_real_pct")),
        "receita_2022": r2(do.get("total")), "n_sinais": len(d.get("sinais") or []),
    }

def collect(G):
    people_dir = ROOT / "build" / "people"
    rows = []; year = datetime.date.today().year
    # ano das emendas: o corrente, ou o mais recente com dado se o corrente ainda não tiver nada
    years_seen = set()
    details = {}
    for pid, rec in G.get("people", {}).items():
        if not house_of(rec): continue
        f = people_dir / f"{pid}.json"
        d = json.load(open(f, encoding="utf-8")) if f.exists() else {}
        details[pid] = d
        years_seen.update(int(y) for y in ((d.get("emendas") or {}).get("anos") or {}).keys() if str(y).isdigit())
    if years_seen and year not in years_seen: year = max(years_seen)
    for pid, rec in G.get("people", {}).items():
        if pid in details: rows.append(person_row(pid, rec, details[pid], year))
    rows.sort(key=lambda r: (r["nome"] or "").lower())
    med = {}
    gab = (G.get("stats") or {}).get("gabinetes") or {}
    for casa in ("camara", "senado"):
        m = {}
        ready = (gab.get(casa) or {}).get("medianas") or {}
        for src, dst in STATS_MEDIANS.items():
            if ready.get(src) is not None: m[dst] = r2(ready[src])
        for k in MEDIAN_KEYS:
            if k in m: continue
            vals = [r[k] for r in rows if r["casa"] == casa and r[k] is not None]
            m[k] = r2(statistics.median(vals)) if vals else None
        med[casa] = m
    notas = {"camara": (gab.get("camara") or {}).get("nota"), "senado": (gab.get("senado") or {}).get("nota"),
             "folha_mes_senado": (gab.get("senado") or {}).get("folha_mes"), "patrimonio_ipca": ((G.get("stats") or {}).get("patrimonio") or {}).get("ipca_fator_2018_2022")}
    return rows, med, year, notas

def build(site, prefix, base, G):
    rows, med, year, notas = collect(G)
    data = {"ano": year, "gerado": (G.get("stats") or {}).get("generated_at") or datetime.date.today().isoformat(), "home": f"{prefix}/", "img": f"{prefix}/img/",
            "medianas": med, "notas": notas, "pessoas": rows}
    tpl = (ROOT / "web" / "comparar.html").read_text(encoding="utf-8")
    out = tpl.replace("<!--CMP_DATA-->", json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"))
    out = out.replace('<link rel="stylesheet" href="atlas.css">', "<style>" + (ROOT / "web" / "atlas.css").read_text(encoding="utf-8") + "</style>").replace('<a class="brand" href="/">', f'<a class="brand" href="{prefix}/">')
    out = out.replace('href="/como-funciona/"', f'href="{prefix}/como-funciona/"')
    desc = f"Rankings e comparação lado a lado de {len(rows)} deputados e senadores: custo do mandato, presença, cota, equipe, emendas, patrimônio e receita de campanha, sempre contra a mediana da Casa."
    out = out.replace("<title>Comparar parlamentares · Atlas da República</title>", f'<title>Comparar parlamentares · Atlas da República</title>\n<meta name="description" content="{esc(desc)}">\n<link rel="canonical" href="{base}/comparar/">\n<meta property="og:title" content="Comparar parlamentares"><meta property="og:description" content="{esc(desc)}"><meta property="og:url" content="{base}/comparar/"><meta property="og:type" content="website"><meta property="og:image" content="{base}{prefix}/og/atlas.png"><meta property="og:image:width" content="1200"><meta property="og:image:height" content="630"><meta name="twitter:card" content="summary_large_image">', 1)
    d = site / "comparar"; d.mkdir(parents=True, exist_ok=True)
    _menu = '<script>window.ATLAS_PREFIX="%s";</script><script src="%s/atlas-menu.js" defer></script>\n' % (prefix, prefix)
    out = out.replace("</html>", _menu + "</html>") if "</html>" in out else out + _menu
    (d / "index.html").write_text(out, encoding="utf-8")
    return f"{base}/comparar/"

if __name__ == "__main__":
    G = json.load(open(ROOT / "build" / "graph.br.json", encoding="utf-8"))
    print(build(ROOT / "site", "", "http://localhost:8765", G))
