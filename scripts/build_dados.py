#!/usr/bin/env python3
"""Dados abertos do Atlas da República em site/dados/: CSV (ponto e vírgula, UTF-8 com BOM) e JSON, com índice em HTML.

Chamado por scripts/build_site.py: build(site_dir, prefix, base, G) -> lista de URLs geradas.
Também roda sozinho para teste: .venv/bin/python scripts/build_dados.py
Só republica o que o site já mostra. Nenhum dado pessoal além de nome, partido, UF e cargo.
"""
import json, csv, io, pathlib, datetime, html

ROOT = pathlib.Path(__file__).resolve().parent.parent
esc = html.escape
LICENSE = "CC BY 4.0"


def num(v):
    """Números com vírgula decimal para o Excel em português; inteiros sem casas."""
    if v is None or v == "": return ""
    if isinstance(v, bool): return "sim" if v else "não"
    if isinstance(v, int): return str(v)
    if isinstance(v, float): return f"{v:.2f}".replace(".", ",")
    return str(v)


def write_csv(path, header, rows):
    buf = io.StringIO(); w = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    w.writerow(header)
    for r in rows: w.writerow([num(v) for v in r])
    path.write_text(buf.getvalue(), encoding="utf-8-sig")
    return len(rows)


def write_json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=0, separators=(",", ":")), encoding="utf-8")


def _people_detail(pid):
    p = ROOT / "build" / "people" / f"{pid}.json"
    if not p.exists(): return {}
    try: return json.load(open(p, encoding="utf-8"))
    except Exception: return {}


def build(site_dir, prefix, base, G):
    site = pathlib.Path(site_dir); out = site / "dados"; out.mkdir(parents=True, exist_ok=True)
    base = base.rstrip("/"); prefix = (prefix or "").rstrip("/")
    N = G["nodes"]; E = G["edges"]; P = G.get("people") or {}
    today = (G.get("stats") or {}).get("generated_at") or datetime.date.today().isoformat()
    files = []  # (arquivo, descrição, linhas)

    # nós
    nos_h = ["id", "tipo", "subtipo", "setor", "anel", "nome", "pai", "cite", "official_url"]
    nos = [[n["id"], n.get("type"), n.get("subtype"), n.get("sector"), n.get("ring"), n.get("name"), n.get("parent"), n.get("cite"), n.get("official_url")] for n in N.values()]
    write_csv(out / "nos.csv", nos_h, nos); write_json(out / "nos.json", [dict(zip(nos_h, r)) for r in nos])
    files.append(("nos.csv", "Órgãos, cargos e colegiados: tipo, setor, anel, órgão pai, citação legal e página oficial.", len(nos))); files.append(("nos.json", "O mesmo conteúdo de nos.csv em JSON.", len(nos)))

    # ligações
    lig_h = ["from", "to", "tipo", "cite"]
    lig = [[e["from"], e["to"], e.get("type"), e.get("cite")] for e in E.values()]
    write_csv(out / "ligacoes.csv", lig_h, lig); write_json(out / "ligacoes.json", [dict(zip(lig_h, r)) for r in lig])
    files.append(("ligacoes.csv", "Relações entre nós (elege, nomeia, sabatina, supervisiona, fiscaliza, integra…), com a norma citada.", len(lig))); files.append(("ligacoes.json", "O mesmo conteúdo de ligacoes.csv em JSON.", len(lig)))

    # pessoas
    pes_h = ["id", "nome", "partido", "uf", "cargos"]
    pes = []
    for p in P.values():
        seen = []; [seen.append(q["name"]) for q in p.get("positions") or [] if q.get("name") and q["name"] not in seen]
        pes.append([p["id"], p.get("name"), p.get("party"), p.get("uf"), " | ".join(seen)])
    write_csv(out / "pessoas.csv", pes_h, pes); write_json(out / "pessoas.json", [dict(zip(pes_h, r)) for r in pes])
    files.append(("pessoas.csv", "Ocupantes conhecidos: nome, partido, UF e cargos atuais.", len(pes))); files.append(("pessoas.json", "O mesmo conteúdo de pessoas.csv em JSON.", len(pes)))

    # ocupantes (cadeira a cadeira)
    oc_h = ["cargo_id", "cargo", "pessoa_id", "pessoa", "papel", "desde", "modo_entrada", "quem_nomeou", "fim_mandato", "interino", "fonte"]
    oc = []
    for n in N.values():
        for q in n.get("people") or []:
            en = q.get("entry") or {}
            oc.append([n["id"], n["name"], q.get("id"), q.get("name"), q.get("role"), q.get("started_at") or en.get("date"), en.get("mode") or q.get("entry_mode"), en.get("by_person") or en.get("by_name"), en.get("term_end"), bool(q.get("acting")), q.get("source_url")])
    write_csv(out / "ocupantes.csv", oc_h, oc); write_json(out / "ocupantes.json", [dict(zip(oc_h, r)) for r in oc])
    files.append(("ocupantes.csv", "Cada cadeira com ocupante: desde quando, como entrou, quem nomeou, fim do mandato e fonte.", len(oc))); files.append(("ocupantes.json", "O mesmo conteúdo de ocupantes.csv em JSON.", len(oc)))

    # mudanças
    mu_h = ["data", "tipo", "pessoa", "cargo_id", "cargo", "interino", "fonte"]
    mu = [[c.get("date"), c.get("kind"), c.get("personName"), c.get("positionId"), c.get("positionName"), bool(c.get("acting")), c.get("sourceUrl")] for c in G.get("changes") or []]
    write_csv(out / "mudancas.csv", mu_h, mu); write_json(out / "mudancas.json", [dict(zip(mu_h, r)) for r in mu])
    files.append(("mudancas.csv", "Posses e sabatinas registradas pelo Atlas, com data e fonte.", len(mu))); files.append(("mudancas.json", "O mesmo conteúdo de mudancas.csv em JSON.", len(mu)))

    # blocos temáticos, como o site recebe
    for key, fn, desc in (("omissao", "omissao.json", "Placar da omissão: vetos vencidos, MPs a vencer e pedidos de CPI aguardando."), ("temas", "temas.json", "Temas acompanhados: processos, estado, dias parado e cobertura."), ("arrecadacao", "arrecadacao.json", "Arrecadômetro: receitas por mês, ritmo, comparação real e por habitante.")):
        if G.get(key): write_json(out / fn, G[key]); files.append((fn, desc, None))

    # por pessoa, a partir de build/people
    em, gab, pat, via = [], [], [], []
    for pid, p in P.items():
        d = _people_detail(pid)
        if not d: continue
        nome = p.get("name")
        e = d.get("emendas") or {}
        for ano, v in sorted((e.get("anos") or {}).items()): em.append([pid, nome, int(ano), v.get("empenhado"), v.get("pago")])
        g = d.get("gabinete") or {}
        if g: gab.append([pid, nome, g.get("casa"), g.get("assessores"), g.get("folha_mensal") if g.get("casa") == "senado" else g.get("folha_mensal_estimada"), (g["custo_ano"].get("total") if isinstance(g.get("custo_ano"), dict) else g.get("custo_ano")), "real (último mês)" if g.get("casa") == "senado" else "estimativa"])
        t = d.get("patrimonio") or {}
        if t.get("2018") or t.get("2022"): pat.append([pid, nome, (t.get("2018") or {}).get("total"), (t.get("2022") or {}).get("total"), t.get("variacao_nominal_pct"), t.get("variacao_real_pct"), (t.get("2022") or t.get("2018") or {}).get("casado_por")])
        v = d.get("viagens") or {}
        if v: via.append([pid, nome, v.get("viagens"), v.get("diarias"), v.get("passagens"), v.get("total"), v.get("exterior")])
    write_csv(out / "emendas-por-pessoa.csv", ["id", "nome", "ano", "empenhado", "pago"], em); files.append(("emendas-por-pessoa.csv", "Emendas parlamentares por autor e ano: valor empenhado e pago (Portal da Transparência).", len(em)))
    write_csv(out / "gabinetes.csv", ["id", "nome", "casa", "assessores", "folha_mensal", "custo_ano_total", "base"], gab); files.append(("gabinetes.csv", "Gabinetes parlamentares: assessores, folha mensal e custo total no ano (subsídio + cota + gabinete; Câmara: folha estimada por nível; Senado: folha real).", len(gab)))
    write_csv(out / "patrimonio.csv", ["id", "nome", "2018", "2022", "variacao_nominal_pct", "variacao_real_pct", "casado_por"], pat); files.append(("patrimonio.csv", "Bens declarados ao TSE em 2018 e 2022, com variação nominal e real (IPCA).", len(pat)))
    write_csv(out / "viagens-por-pessoa.csv", ["id", "nome", "viagens", "diarias", "passagens", "total", "exterior"], via); files.append(("viagens-por-pessoa.csv", f"Viagens a serviço por pessoa em {(G.get('viagens') or {}).get('ano', '')}: diárias, passagens e total (Portal da Transparência).", len(via)))

    # índice
    _h = index_html(files, out, prefix, base, today).replace("</html>", '<script>window.ATLAS_PREFIX="%s";</script><script src="%s/atlas-menu.js" defer></script>\n</html>' % (prefix, prefix))
    (out / "index.html").write_text(_h, encoding="utf-8")
    return [f"{base}{prefix}/dados/"] + [f"{base}{prefix}/dados/{f}" for f, _, _ in files]


def fmt_size(n):
    return f"{n / 1024 / 1024:.1f} MB".replace(".", ",") if n >= 1024 * 1024 else f"{max(1, round(n / 1024))} KB"


def index_html(files, out, prefix, base, today):
    rows = "".join(f'<tr><td><a href="{esc(f)}" download>{esc(f)}</a></td><td>{esc(d)}</td><td class="n">{("{:,}".format(n).replace(",", ".") + " linhas") if n is not None else "—"}</td><td class="n">{fmt_size((out / f).stat().st_size)}</td></tr>' for f, d, n in files)
    y, m, d = today.split("-"); meses = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]; data_pt = f"{int(d)} de {meses[int(m) - 1]} de {y}"
    return f'''<!doctype html>
<html lang="pt-BR">
<script>try{{document.documentElement.dataset.theme=localStorage.getItem('atlas-theme')||'dark'}}catch(e){{document.documentElement.dataset.theme='dark'}}</script>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dados abertos · Atlas da República</title>
<meta name="description" content="Dados do Atlas da República em CSV e JSON: órgãos, cargos, ligações, ocupantes, mudanças, omissão, temas, arrecadação, emendas, gabinetes, patrimônio e viagens. Licença CC BY 4.0.">
<link rel="canonical" href="{esc(base)}{esc(prefix)}/dados/">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns=%27http://www.w3.org/2000/svg%27 viewBox=%270 0 32 32%27%3E%3Ccircle cx=%2716%27 cy=%2716%27 r=%2714%27 fill=%27%23C25A12%27/%3E%3C/svg%3E">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@500;600;700;800&family=Source+Sans+3:ital,wght@0,400;0,600;1,400&family=JetBrains+Mono:wght@400;600&display=swap" media="print" onload="this.media='all'">
<link rel="stylesheet" href="{esc(prefix)}/atlas.css">
<style>
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:17px;line-height:1.55}}
a{{color:var(--accent)}}
.bar{{position:sticky;top:0;z-index:5;display:flex;align-items:center;gap:14px;padding:8px 16px;background:color-mix(in srgb,var(--bg) 88%,transparent);backdrop-filter:blur(8px);border-bottom:1px solid var(--line-2)}}
.bar .brand{{display:flex;align-items:center;gap:8px;font-family:var(--disp);font-weight:700;font-size:15px;color:var(--ink);text-decoration:none;white-space:nowrap}}
.bar .brand .mark{{width:16px;height:16px;border-radius:50%;background:var(--povo);box-shadow:0 0 0 2px var(--card),0 0 0 3px var(--povo)}}
.bar .crumb{{color:var(--ink-3);font-weight:500}}
.bar .sp{{flex:1}}
.btn{{font:inherit;font-size:13px;padding:6px 10px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--ink);cursor:pointer}}
main{{max-width:960px;margin:0 auto;padding:24px 20px 80px}}
.eyebrow{{font-family:var(--mono);font-size:11.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--ink-3)}}
h1{{font-family:var(--disp);font-size:clamp(30px,5vw,44px);font-weight:800;letter-spacing:-.02em;line-height:1.05;margin:10px 0 12px}}
h2{{font-family:var(--disp);font-size:22px;font-weight:800;letter-spacing:-.01em;margin:36px 0 8px}}
p.lead{{font-size:19px;color:var(--ink-2);max-width:60ch;margin:0 0 8px}}
.meta{{display:flex;gap:16px;flex-wrap:wrap;font-family:var(--mono);font-size:12px;color:var(--ink-3);margin:12px 0 24px}}
.tbl{{overflow-x:auto;border:1px solid var(--line-2);border-radius:10px;background:var(--card)}}
table{{border-collapse:collapse;width:100%;font-size:15px}}
th,td{{text-align:left;padding:9px 12px;border-bottom:1px solid var(--line-2);vertical-align:top}}
th{{font-family:var(--mono);font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--ink-3);font-weight:600}}
tr:last-child td{{border-bottom:0}}
td a{{font-family:var(--mono);font-size:13.5px;white-space:nowrap}}
td.n{{font-family:var(--mono);font-size:13px;color:var(--ink-3);white-space:nowrap;text-align:right}}
code,pre{{font-family:var(--mono);font-size:13.5px}}
pre{{background:var(--card);border:1px solid var(--line-2);border-radius:8px;padding:12px 14px;overflow-x:auto;white-space:pre-wrap}}
ul{{padding-left:20px}} li{{margin:4px 0}}
.foot{{margin-top:40px;padding-top:16px;border-top:1px solid var(--line-2);font-size:14px;color:var(--ink-3)}}
@media (max-width:600px){{ .bar .crumb{{display:none}} th,td{{padding:8px}} }}
</style>
<div class="bar">
  <a class="brand" href="{esc(prefix)}/"><span class="mark"></span>Atlas da República <span class="crumb">/ Dados</span></a>
  <span class="sp"></span>
  <a class="btn" href="{esc(prefix)}/metodologia/">Metodologia</a>
  <button class="btn" id="theme" aria-label="Alternar tema claro e escuro">◐ Tema</button>
</div>
<main>
  <div class="eyebrow">Atlas da República · dados abertos</div>
  <h1>Dados para baixar</h1>
  <p class="lead">Tudo o que o Atlas mostra, em arquivos abertos. CSV separado por ponto e vírgula, em UTF-8 com BOM (abre direto no Excel em português; decimais com vírgula). JSON em UTF-8.</p>
  <div class="meta"><span>gerado em {esc(data_pt)}</span><span>licença {LICENSE}</span><span>{len(files)} arquivos</span></div>
  <div class="tbl"><table>
    <thead><tr><th>Arquivo</th><th>Conteúdo</th><th>Linhas</th><th>Tamanho</th></tr></thead>
    <tbody>{rows}</tbody>
  </table></div>
  <h2>Licença e citação</h2>
  <p>Os arquivos são publicados sob <a href="https://creativecommons.org/licenses/by/4.0/deed.pt-br" rel="license">Creative Commons Atribuição 4.0 Internacional (CC BY 4.0)</a>. Você pode copiar, redistribuir, transformar e usar para qualquer fim, inclusive comercial, desde que cite a fonte. Os dados de origem são públicos e pertencem aos órgãos que os publicam.</p>
  <p>Como citar:</p>
  <pre>Atlas da República, atlasdarepublica.org, dados de {esc(today)}</pre>
  <h2>Avisos</h2>
  <ul>
    <li>Os arquivos são regenerados a cada build do site; a data acima é a da geração. Colunas podem ganhar campos novos; a ordem das existentes é mantida.</li>
    <li><code>ocupantes.csv</code> traz uma linha por cadeira ocupada; a mesma pessoa pode aparecer em várias linhas. A coluna <code>fonte</code> é a página de onde o nome foi lido.</li>
    <li><code>gabinetes.csv</code>: na Câmara a folha é estimativa (quantidade de funcionários × tabela de níveis); no Senado é a folha real do último mês publicado. A coluna <code>base</code> distingue os dois.</li>
    <li><code>patrimonio.csv</code>: bens declarados ao TSE pelo valor de aquisição; a variação real usa o IPCA de ago/2018 a ago/2022. <code>casado_por</code> diz como a declaração foi ligada à pessoa.</li>
    <li>Não há CPF, endereço, telefone ou qualquer dado além do que já aparece nas páginas do Atlas. A metodologia completa está em <a href="{esc(prefix)}/metodologia/">Metodologia</a>.</li>
    <li>Erro nos dados? <a href="https://github.com/culturabuilder/atlas-da-republica/issues/new">Abra um issue</a>.</li>
  </ul>
  <div class="foot">Atlas da República · <a href="{esc(prefix)}/">roda completa</a> · <a href="{esc(prefix)}/como-funciona/">como funciona</a> · <a href="{esc(prefix)}/feeds/mudancas.xml">RSS</a></div>
</main>
<script>
const root=document.documentElement,tb=document.getElementById('theme');
tb.addEventListener('click',()=>{{const dark=root.dataset.theme!=='light';root.dataset.theme=dark?'light':'dark';try{{localStorage.setItem('atlas-theme',root.dataset.theme)}}catch(e){{}}}});
</script>
</html>
'''


if __name__ == "__main__":
    G = json.load(open(ROOT / "build" / "graph.br.json", encoding="utf-8"))
    urls = build(ROOT / "site", "", "http://localhost:8765", G)
    out = ROOT / "site" / "dados"
    for u in urls[1:]:
        fn = u.rsplit("/", 1)[1]; p = out / fn
        if fn.endswith(".csv"):
            with open(p, encoding="utf-8-sig", newline="") as fh:
                rows = list(csv.reader(fh, delimiter=";")); widths = {len(r) for r in rows}
            assert len(widths) == 1, (fn, widths)
            print(f"{fn}: {len(rows) - 1} linhas, {len(rows[0])} colunas, {p.stat().st_size} bytes")
        else:
            json.load(open(p, encoding="utf-8")); print(f"{fn}: JSON ok, {p.stat().st_size} bytes")
    print("index:", (out / "index.html").stat().st_size, "bytes")
