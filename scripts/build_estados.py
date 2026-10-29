#!/usr/bin/env python3
"""Gera /estados/ e /estados/<uf>/ — "no seu estado": quem representa e quanto dinheiro federal chega.

Por que existe: o Atlas tinha dado por estado desde sempre e jogava fora na agregação. O conector de
emendas lia a UF de cada pagamento e publicava só os 15 municípios de maior valor por habitante; o de
transferências já trazia as 27 UFs com valor por habitante; e os 594 parlamentares já tinham partido e
UF. Nenhuma fonte nova: o que faltava era a página. A ideia de entrar pelo lugar onde a pessoa mora vem
do politicometro.org.

Chamado por scripts/build_site.py: build(site_dir, prefix, base, G).
Sozinho: .venv/bin/python scripts/build_estados.py
"""
import json, pathlib, html, datetime, statistics
ROOT = pathlib.Path(__file__).resolve().parent.parent
esc = html.escape

UF_NOME = {"AC": "Acre", "AL": "Alagoas", "AM": "Amazonas", "AP": "Amapá", "BA": "Bahia", "CE": "Ceará",
           "DF": "Distrito Federal", "ES": "Espírito Santo", "GO": "Goiás", "MA": "Maranhão", "MG": "Minas Gerais",
           "MS": "Mato Grosso do Sul", "MT": "Mato Grosso", "PA": "Pará", "PB": "Paraíba", "PE": "Pernambuco",
           "PI": "Piauí", "PR": "Paraná", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte", "RO": "Rondônia",
           "RR": "Roraima", "RS": "Rio Grande do Sul", "SC": "Santa Catarina", "SE": "Sergipe", "SP": "São Paulo",
           "TO": "Tocantins"}
# dois artigos, porque "representa no Acre" não é português: um para o lugar ("em/no/na") e um para o
# objeto direto ("o Acre", "a Bahia", "São Paulo" sem artigo nenhum).
ARTIGO_D = {u: "o " for u in ("AC", "AM", "AP", "CE", "DF", "ES", "MA", "MS", "MT", "PA", "PI", "PR", "RJ", "RN", "RS", "TO")}
ARTIGO_D.update({u: "a " for u in ("BA", "PB")})
ARTIGO_D.update({u: "" for u in ("AL", "GO", "MG", "PE", "RO", "RR", "SC", "SE", "SP")})
ARTIGO = {"AC": "no", "AL": "em", "AM": "no", "AP": "no", "BA": "na", "CE": "no", "DF": "no", "ES": "no", "GO": "em",
          "MA": "no", "MG": "em", "MS": "no", "MT": "no", "PA": "no", "PB": "na", "PE": "em", "PI": "no", "PR": "no",
          "RJ": "no", "RN": "no", "RO": "em", "RR": "em", "RS": "no", "SC": "em", "SE": "em", "SP": "em", "TO": "no"}


def brl(v):
    if v is None: return "—"
    if abs(v) >= 1e9: return f"R$ {v/1e9:,.1f} bi".replace(",", "X").replace(".", ",").replace("X", ".")
    if abs(v) >= 1e6: return f"R$ {v/1e6:,.1f} mi".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {v:,.0f}".replace(",", ".")


def num(v):
    if v is None: return "—"
    return f"{v:,.0f}".replace(",", ".") if float(v) == int(v) else f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def coletar(G):
    em = (G.get("emendas") or {}).get("por_uf") or {}
    tr = (G.get("transferencias") or {}).get("por_uf") or {}
    ano_em = str((G.get("emendas") or {}).get("year") or datetime.date.today().year)
    anos_tr = sorted({a for v in tr.values() for a in v}, reverse=True)
    ano_tr = anos_tr[0] if anos_tr else None
    gente = {}
    for pid, p in (G.get("people") or {}).items():
        uf = p.get("uf")
        if not uf or uf not in UF_NOME: continue
        casa = next((q.get("id") for q in (p.get("positions") or []) if q.get("id") in ("br-deputado-federal", "br-senador")), None)
        if not casa: continue
        gente.setdefault(uf, {"br-senador": [], "br-deputado-federal": []})[casa].append(
            {"id": pid, "nome": p.get("name"), "partido": p.get("party")})
    for uf in gente:
        for k in gente[uf]: gente[uf][k].sort(key=lambda x: (x["nome"] or ""))
    return em, tr, ano_em, ano_tr, gente


def medianas(em, tr, ano_em, ano_tr):
    e = [v.get("por_habitante") for v in em.values() if v.get("por_habitante")]
    t = [(v.get(ano_tr) or {}).get("por_habitante") for v in tr.values() if (v.get(ano_tr) or {}).get("por_habitante")] if ano_tr else []
    return (round(statistics.median(e), 2) if e else None), (round(statistics.median(t), 2) if t else None)


def pagina_uf(uf, G, em, tr, ano_em, ano_tr, gente, med_em, med_tr, prefix, base, data):
    e = em.get(uf) or {}; t = (tr.get(uf) or {}).get(ano_tr) or {}
    g = gente.get(uf) or {"br-senador": [], "br-deputado-federal": []}
    nome = UF_NOME[uf]
    emp = (e.get("anos") or {}).get(ano_em, {}).get("empenhado")
    st = []
    st.append(("parlamentares", num(len(g["br-senador"]) + len(g["br-deputado-federal"])), f"que representam {ARTIGO_D[uf]}{nome} em Brasília"))
    if emp: st.append(("emendas", brl(emp), f"em emendas parlamentares empenhadas em {ano_em}"))
    if e.get("por_habitante"): st.append(("por hab", brl(e["por_habitante"]), f"de emenda por habitante — a mediana dos estados é {brl(med_em)}"))
    if t.get("total"): st.append(("transferências", brl(t["total"]), f"transferidos pela União em {ano_tr}, ao estado e aos municípios"))
    if t.get("por_habitante"): st.append(("por hab", brl(t["por_habitante"]), f"de transferência por habitante — mediana {brl(med_tr)}"))
    cartoes = "".join(f'<div class="stat"><div class="n">{v}</div><div class="l">{esc(l)}</div></div>' for _, v, l in st)
    lista = lambda xs: "".join(f'<li><a href="{prefix}/br/pessoa/{esc(x["id"])}/">{esc(x["nome"] or "")}</a>'
                               f'{(" · " + esc(x["partido"])) if x.get("partido") else ""}</li>' for x in xs)
    serie = ""
    if (e.get("anos") or {}):
        linhas = "".join(f'<tr><td>{esc(a)}</td><td style="text-align:right;font-family:var(--mono)">{brl(v.get("empenhado"))}</td>'
                         f'<td style="text-align:right;font-family:var(--mono)">{brl(v.get("pago"))}</td></tr>'
                         for a, v in sorted((e.get("anos") or {}).items(), reverse=True))
        serie = (f'<h2>Emendas ano a ano</h2><div class="tbl"><table><thead><tr><th>Ano</th>'
                 f'<th style="text-align:right">empenhado</th><th style="text-align:right">pago</th></tr></thead><tbody>{linhas}</tbody></table></div>')
    tipos = ""
    if t.get("por_tipo"):
        itens = "".join(f'<li>{esc(k)}: <b>{brl(v)}</b></li>' for k, v in sorted(t["por_tipo"].items(), key=lambda kv: -(kv[1] or 0)))
        tipos = f'<h2>De que tipo é a transferência</h2><ul>{itens}</ul>'
    repart = ""
    if t.get("a_estado") or t.get("a_municipios"):
        repart = (f'<p>Em {ano_tr}, <b>{brl(t.get("a_estado"))}</b> foram para o governo do estado e '
                  f'<b>{brl(t.get("a_municipios"))}</b> para as prefeituras.</p>')
    return f"""  <header>
    <div class="eyebrow">Atlas da República · no seu estado</div>
    <h1>{esc(nome)}</h1>
    <p class="lead">Quem representa {esc(ARTIGO_D[uf])}{esc(nome)} no Congresso, e quanto dinheiro federal chega ao estado e às suas prefeituras. Tudo com a fonte oficial e a data da leitura.</p>
    <div class="meta"><span>build de {esc(data)}</span><span>{esc(str(e.get("municipios_alcancados") or "—"))} municípios alcançados por emenda desde {esc(str(e.get("desde") or ""))}</span></div>
    <div class="stats" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:18px 0">{cartoes}</div>
  </header>
  <section>
    <h2>Quem representa este estado</h2>
    <h3>Senadores · {len(g["br-senador"])}</h3>
    <ul>{lista(g["br-senador"]) or "<li>sem registro</li>"}</ul>
    <h3>Deputados federais · {len(g["br-deputado-federal"])}</h3>
    <ul style="columns:2;column-gap:28px">{lista(g["br-deputado-federal"]) or "<li>sem registro</li>"}</ul>
    <p class="note">A bancada vem da composição oficial da Câmara e do Senado. Quem assumiu como suplente aparece quando a Casa registra.</p>
  </section>
  <section>
    <h2>Dinheiro federal que chega</h2>
    {repart}
    {serie}
    {tipos}
    <p class="note">Emendas: Portal da Transparência, valor empenhado e pago por UF do favorecido, lido em {esc(str((G.get("emendas") or {}).get("generated_at") or "")[:10])}. Transferências: {esc(str((G.get("transferencias") or {}).get("fonte") or "Tesouro Nacional"))}, lido em {esc(str((G.get("transferencias") or {}).get("generated_at") or "")[:10])}. Valor por habitante usa a população estimada do IBGE. "Empenhado" é o compromisso assumido; "pago" é o que saiu do caixa — os dois são do mesmo ano e não se somam.</p>
    <p class="note">Emenda registrada para um favorecido sediado em Brasília entra no Distrito Federal, mesmo quando a obra é em outro lugar: é assim que a fonte publica.</p>
  </section>
"""


def build(site, prefix, base, G):
    tpl_p = ROOT / "web" / "estado.html"
    if not tpl_p.exists(): return []
    tpl = tpl_p.read_text(encoding="utf-8")
    em, tr, ano_em, ano_tr, gente = coletar(G)
    if not em and not tr: return []
    med_em, med_tr = medianas(em, tr, ano_em, ano_tr)
    data = str((G.get("stats") or {}).get("generated_at") or datetime.date.today().isoformat())[:10]
    urls = []
    rodape = lambda: ('<nav class="ufs" aria-label="Todos os estados">'
                      + "".join(f'<a href="{prefix}/estados/{u.lower()}/">{u}</a>' for u in sorted(UF_NOME)) + "</nav>")

    def escrever(destino, corpo, titulo, desc, url):
        out = tpl.replace("__CORPO__", corpo + rodape()).replace("__PREFIX__", prefix)
        out = out.replace("<title>__TITULO__</title>", f'<title>{esc(titulo)}</title>\n<meta name="description" content="{esc(desc)}">\n'
                          f'<link rel="canonical" href="{url}">\n<meta property="og:title" content="{esc(titulo)}">'
                          f'<meta property="og:description" content="{esc(desc)}"><meta property="og:url" content="{url}">'
                          f'<meta property="og:type" content="website"><meta property="og:image" content="{base}{prefix}/og/atlas.png">'
                          f'<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">'
                          f'<meta name="twitter:card" content="summary_large_image">', 1)
        out = out.replace("__CRUMB__", esc(titulo.split(" · ")[0]))
        out = out.replace("</html>", f'<script>window.ATLAS_PREFIX="{prefix}";</script><script src="{prefix}/atlas-menu.js" defer></script>\n</html>')
        destino.mkdir(parents=True, exist_ok=True)
        (destino / "index.html").write_text(out, encoding="utf-8")
        urls.append(url)

    # índice: os 27, ordenados por emenda por habitante, que é a comparação que diz algo
    linhas = []
    for u in sorted(UF_NOME, key=lambda x: -((em.get(x) or {}).get("por_habitante") or 0)):
        e = em.get(u) or {}; t = (tr.get(u) or {}).get(ano_tr) or {}
        g = gente.get(u) or {"br-senador": [], "br-deputado-federal": []}
        linhas.append(f'<tr><td><a href="{prefix}/estados/{u.lower()}/">{esc(UF_NOME[u])}</a></td>'
                      f'<td style="text-align:right;font-family:var(--mono)">{len(g["br-senador"]) + len(g["br-deputado-federal"])}</td>'
                      f'<td style="text-align:right;font-family:var(--mono)">{brl((e.get("anos") or {}).get(ano_em, {}).get("empenhado"))}</td>'
                      f'<td style="text-align:right;font-family:var(--mono)">{brl(e.get("por_habitante"))}</td>'
                      f'<td style="text-align:right;font-family:var(--mono)">{brl(t.get("por_habitante"))}</td></tr>')
    maior = max(em.items(), key=lambda kv: kv[1].get("por_habitante") or 0, default=(None, {}))
    menor = min(((k, v) for k, v in em.items() if v.get("por_habitante")), key=lambda kv: kv[1]["por_habitante"], default=(None, {}))
    razao = ""
    if maior[0] and menor[0]:
        r = maior[1]["por_habitante"] / menor[1]["por_habitante"]
        razao = (f'<p>Por habitante, {esc(UF_NOME[maior[0]])} recebeu <b>{num(round(r, 1))}×</b> mais emenda '
                 f'que {esc(UF_NOME[menor[0]])} em {esc(ano_em)} — {brl(maior[1]["por_habitante"])} contra {brl(menor[1]["por_habitante"])} '
                 f'por pessoa. A emenda é escolhida por parlamentar, não repartida por população, e é por isso que a diferença aparece.</p>')
    indice = f"""  <header>
    <div class="eyebrow">Atlas da República · no seu estado</div>
    <h1>No seu estado</h1>
    <p class="lead">Quem representa cada estado em Brasília e quanto dinheiro federal chega lá. Comece pelo seu.</p>
    <div class="meta"><span>build de {esc(data)}</span><span>27 estados</span><span>emendas de {esc(ano_em)}</span></div>
  </header>
  <section>
    {razao}
    <div class="tbl"><table>
      <thead><tr><th>Estado</th><th style="text-align:right">bancada</th><th style="text-align:right">emendas {esc(ano_em)}</th><th style="text-align:right">emenda/hab</th><th style="text-align:right">transferência/hab</th></tr></thead>
      <tbody>{"".join(linhas)}</tbody>
    </table></div>
    <p class="note">Ordenado por emenda por habitante. "Bancada" é o número de deputados federais e senadores do estado. Transferência por habitante é do ano de {esc(str(ano_tr or ""))}, e inclui o que vai ao governo estadual e às prefeituras.</p>
  </section>
"""
    escrever(site / "estados", indice, "No seu estado · Atlas da República",
             "Quem representa cada estado no Congresso e quanto dinheiro federal chega, estado por estado.", f"{base}/estados/")
    for u in sorted(UF_NOME):
        corpo = pagina_uf(u, G, em, tr, ano_em, ano_tr, gente, med_em, med_tr, prefix, base, data)
        escrever(site / "estados" / u.lower(), corpo, f"{UF_NOME[u]} · no seu estado · Atlas da República",
                 f"Quem representa {ARTIGO_D[u]}{UF_NOME[u]} no Congresso e quanto dinheiro federal chega ao estado e às suas prefeituras.",
                 f"{base}/estados/{u.lower()}/")
    return urls


if __name__ == "__main__":
    G = json.load(open(ROOT / "build" / "graph.br.json", encoding="utf-8"))
    print(len(build(ROOT / "site", "", "http://localhost:8765", G)), "páginas")
