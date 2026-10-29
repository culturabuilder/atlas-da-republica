#!/usr/bin/env python3
"""Gera /quem-publica/ — o que cada órgão do governo federal deixa ver, medido pelo que o Atlas leu.

A ideia vem de uma página do politicometro.org, que mede isso para as 5.569 cidades. Aqui a medida é
federal e sai do próprio build: para cada órgão, quantos assuntos algum conector conseguiu preencher;
por setor, quantos órgãos ficaram sem nenhum; quem responde pedido de acesso à informação e quem nega;
e o que o Atlas não consegue ler, com o motivo. Nenhuma fonte nova: tudo isto já estava no repositório,
só não estava na tela.

Chamado por scripts/build_site.py: build(site_dir, prefix, base, G).
Sozinho, para teste: .venv/bin/python scripts/build_quem_publica.py
"""
import json, pathlib, html, datetime, glob, os
ROOT = pathlib.Path(__file__).resolve().parent.parent
esc = html.escape

SETOR_ROT = {"executivo": "Executivo", "judiciario": "Judiciário", "legislativo": "Legislativo", "essenciais": "Funções essenciais à Justiça"}
# campos de um nó que não são "assunto sobre o órgão": identidade, texto e navegação
NAO_E_BLOCO = {"id", "type", "name", "sector", "ring", "parent", "cluster", "source", "aliases", "description",
               "siorg_description", "cite", "cite_url", "official_url", "verified", "siorg_code", "subtype",
               "positions", "people", "edges", "children", "x", "y", "angle", "seats", "note", "checked_at",
               "head_of", "nomeado_por", "eleito_por", "mandato_anos", "vacant_seats", "competencia", "img", "photo"}
# nome legível de cada bloco, para a lista do órgão
BLOCO_ROT = {"budget": "orçamento", "programas": "programas", "transferencias": "transferências a estados e municípios",
             "contratos": "contratos", "sancoes": "punições", "falabr": "pedidos de acesso à informação",
             "recebidos": "quem o órgão recebeu", "agenda": "agenda pública", "subsidio": "quanto o cargo paga",
             "custo": "custo da cadeira", "historico": "quem ocupou", "composicao": "composição",
             "sabatinas": "sabatinas no Senado", "dou": "atos no Diário Oficial", "candidaturas": "candidaturas",
             "casa": "atividade da Casa", "teto": "acima do teto", "dirigentes": "dirigentes",
             "composicao_membros": "quem compõe"}

def _blocos(d):
    bl = sorted(k for k, v in d.items() if k not in NAO_E_BLOCO and v not in (None, "", [], {}, 0))
    # Quem compõe o colegiado É dado publicado sobre ele, e dos mais pedidos: a CCJ da Câmara tem os
    # 130 membros no nó e nada mais. Contar isso como "nenhum dado" daria 94% do Legislativo opaco,
    # o que é falso — e seria exatamente o tipo de número que esta página existe para não publicar.
    if d.get("people"): bl = sorted(bl + ["composicao_membros"])
    return bl

def medir(G):
    N = G["nodes"] if isinstance(G["nodes"], list) else list(G["nodes"].values())
    setor = {n["id"]: (n.get("sector") or "?") for n in N}
    nome = {n["id"]: n.get("name") or n["id"] for n in N}
    tipo = {n["id"]: n.get("type") for n in N}
    por_setor = {}
    sem_nada, com_tudo = [], []
    for f in glob.glob(str(ROOT / "build" / "nodes" / "*.json")):
        i = os.path.basename(f)[:-5]
        s = setor.get(i)
        # cargo (dept_head) não é órgão: ele herda a transparência de quem o abriga
        if not s or tipo.get(i) == "dept_head": continue
        d = json.load(open(f, encoding="utf-8"))
        bl = _blocos(d)
        g = por_setor.setdefault(s, {"nos": 0, "blocos": 0, "vazios": 0})
        g["nos"] += 1; g["blocos"] += len(bl)
        if not bl: g["vazios"] += 1; sem_nada.append((nome[i], i, s))
        elif len(bl) >= 6: com_tudo.append((len(bl), nome[i], i, bl))
    sem_nada.sort(key=lambda x: x[0]); com_tudo.sort(reverse=True)
    return por_setor, sem_nada, com_tudo

def corpo(G):
    por_setor, sem_nada, com_tudo = medir(G)
    st = G.get("stats") or {}
    partes = []
    tot_nos = sum(g["nos"] for g in por_setor.values()); tot_vaz = sum(g["vazios"] for g in por_setor.values())
    partes.append(f"""  <section id="placar">
    <div class="eyebrow">O placar</div>
    <h2>De {tot_nos} órgãos da União, {tot_vaz} não deixam ver nada</h2>
    <p>Nada aqui quer dizer: nenhum dos 46 conectores do Atlas conseguiu ler um único assunto sobre aquele órgão numa fonte oficial em formato aberto — nem orçamento, nem contrato, nem punição, nem pedido de informação respondido.</p>
    <div class="grid" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:16px 0">""")
    for s, g in sorted(por_setor.items(), key=lambda x: -x[1]["nos"]):
        if s not in SETOR_ROT: continue
        pct = round(100 * g["vazios"] / g["nos"])
        partes.append(f"""      <div class="it" style="border:1px solid var(--line);border-radius:10px;padding:12px">
        <b>{esc(SETOR_ROT[s])}</b>
        <div style="font-family:var(--mono);font-size:26px;margin:6px 0 2px">{pct}%</div>
        <div style="font-size:13.5px;color:var(--ink-2)">dos {g['nos']} órgãos sem nenhum dado aberto ({g['vazios']})</div>
        <div style="font-size:13px;color:var(--ink-3);margin-top:6px">{str(round(g['blocos'] / g['nos'], 2)).replace('.', ',')} assuntos por órgão, na média</div>
      </div>""")
    partes.append("    </div>\n  </section>")

    # quem responde pedido de acesso à informação
    fb = G.get("falabr") or {}
    if fb.get("resumo"):
        r = fb["resumo"]; mais = fb.get("mais_negam") or []
        # a chave do nó é "node"; com "id" saíam 12 links para /br// — achado ao conferir o HTML gerado
        def _cel(x):
            nome = esc(x.get("orgao") or x.get("nome") or "")
            nid = x.get("node") or x.get("id")
            return f'<a href="__PREFIX__/br/{esc(nid)}/">{nome}</a>' if nid else nome
        linhas = "".join(
            f'<tr><td>{_cel(x)}</td>'
            f'<td style="text-align:right;font-family:var(--mono)">{x.get("pedidos", "—")}</td>'
            f'<td style="text-align:right;font-family:var(--mono)">{str(x.get("pct_negado_ou_parcial", "—")).replace(".", ",")}%</td></tr>'
            for x in mais[:12])
        geral = str(r.get("pct_negado_ou_parcial_geral", "—")).replace(".", ",")
        partes.append(f"""  <section id="lai-placar">
    <div class="eyebrow">Quando alguém pergunta</div>
    <h2>Quem responde e quem nega</h2>
    <p>Publicar sozinho é uma coisa; responder quando perguntam é outra. No Executivo federal, <b>{geral}%</b> dos pedidos decididos pela Lei de Acesso à Informação em {esc(str(fb.get('ano') or ''))} foram negados de todo ou concedidos apenas em parte. Órgãos que mais negam, entre os que decidiram o bastante para a taxa significar algo:</p>
    <table style="width:100%;border-collapse:collapse;font-size:15px;margin:12px 0">
      <thead><tr><th style="text-align:left;border-bottom:1px solid var(--line);padding:6px 0">Órgão</th><th style="text-align:right;border-bottom:1px solid var(--line)">pedidos</th><th style="text-align:right;border-bottom:1px solid var(--line)">negados ou em parte</th></tr></thead>
      <tbody>{linhas}</tbody>
    </table>
    <p style="font-size:14px;color:var(--ink-3)">Fonte: {esc(str(fb.get('fonte') or 'Fala.BR/CGU'))}, lido em {esc(str(fb.get('generated_at') or '')[:10])}. Resposta de "informação inexistente" e "fora da competência do órgão" fica fora desta taxa: não é recusa de dado que o órgão tenha.</p>
  </section>""")

    # o que a própria fonte não publica, dito com nome e motivo
    # (órgão, verbo, o que, por quê) — o verbo existe porque uma das linhas é sobre o próprio Atlas,
    # e "o Atlas não publica" diria a coisa errada: ele não consegue atualizar sozinho.
    nao = []
    casa_sen = next((json.load(open(f, encoding="utf-8")).get("casa") for f in [str(ROOT / "build" / "nodes" / "br-senado-federal.json")] if os.path.exists(f)), None)
    if (casa_sen or {}).get("gabinetes", {}).get("folha_nao_publicada"):
        nao.append(("Senado Federal", "não publica", "a folha de pagamento dos gabinetes", "publica o tamanho da equipe e a cota por rubrica, mas não quanto paga a cada pessoa do gabinete; por isso o Atlas mostra equipe e cota, e nenhum valor de folha"))
    nao.append(("Senado Federal", "não publica", "a lista de presença de cada sessão", "publica como cada senador aparece em cada votação nominal, não a presença em sessão; o Atlas mostra participação em votação nominal e diz que é isso"))
    nao.append(("Supremo Tribunal Federal", "não publica", "dados abertos de julgamento", "não há API pública; o que o Atlas mostra do STF vem de estrutura, nomeação e sabatina, não de processo"))
    nao.append(("Tribunal Superior Eleitoral", "não oferece", "download automático de bens e votação", "os arquivos existem, abertos, mas atrás de um formulário: têm de ser baixados à mão, e por isso patrimônio e votos não atualizam sozinhos no servidor"))
    ex = (st.get("execucao") or {})
    for n in (ex.get("sem_arquivo_local") or []):
        nao.append(("Atlas da República", "não atualiza sozinho", f"o bloco {str(n)}", "depende de arquivo que a fonte só entrega por formulário; o dado publicado é o da última vez que alguém rodou o conector com o arquivo em disco"))
    itens = "".join(f'<li><b>{esc(o)}</b> {esc(v)} {esc(q)} — {esc(p)}.</li>' for o, v, q, p in nao)
    partes.append(f"""  <section id="nao-publica">
    <div class="eyebrow">Dito com nome</div>
    <h2>O que a fonte não publica</h2>
    <p>Quando falta dado, o Atlas não estima: diz que falta e de quem é a falta.</p>
    <ul style="line-height:1.6">{itens}</ul>
  </section>""")

    # os órgãos mais transparentes e os mais fechados, com link
    if com_tudo:
        top = "".join(f'<li><a href="__PREFIX__/br/{esc(i)}/">{esc(nm)}</a> — {n} assuntos: {esc(", ".join(BLOCO_ROT.get(b, b) for b in bl)[:170])}</li>' for n, nm, i, bl in com_tudo[:10])
        partes.append(f"""  <section id="mais-abertos">
    <div class="eyebrow">O outro lado</div>
    <h2>Os órgãos sobre os quais mais se sabe</h2>
    <p>Nem sempre porque são mais abertos: órgão grande aparece em mais cadastros. Ainda assim, é aqui que o cidadão consegue mais resposta sem pedir.</p>
    <ol style="line-height:1.6">{top}</ol>
  </section>""")
    if sem_nada:
        por_s = {}
        for nm, i, s in sem_nada: por_s.setdefault(s, []).append((nm, i))
        blocos_s = []
        for s, lst in sorted(por_s.items(), key=lambda x: -len(x[1])):
            if s not in SETOR_ROT: continue
            links = ", ".join(f'<a href="__PREFIX__/br/{esc(i)}/">{esc(nm)}</a>' for nm, i in lst[:40])
            mais = f" e outros {len(lst) - 40}" if len(lst) > 40 else ""
            blocos_s.append(f'<p><b>{esc(SETOR_ROT[s])}</b> · {len(lst)}: {links}{mais}.</p>')
        partes.append(f"""  <section id="sem-nada">
    <div class="eyebrow">A lista</div>
    <h2>Órgãos sem nenhum dado aberto que o Atlas consiga ler</h2>
    <p>Cada nome abaixo tem página no Atlas com a norma que o cria, o cargo que o chefia e as relações com os outros — e nada além disso, porque nada além disso está publicado em formato aberto.</p>
    {''.join(blocos_s)}
  </section>""")
    return "\n".join(partes)

def build(site, prefix, base, G):
    tpl_p = ROOT / "web" / "quem-publica.html"
    if not tpl_p.exists(): return None
    data = str((G.get("stats") or {}).get("generated_at") or datetime.date.today().isoformat())[:10]
    out = tpl_p.read_text(encoding="utf-8").replace("__CORPO__", corpo(G)).replace("__DATA__", esc(data)).replace("__PREFIX__", prefix)
    desc = "Quais órgãos do governo federal publicam dado aberto e quais não publicam, medido pelo que o Atlas da República conseguiu ler em cada um."
    out = out.replace("</head>", "") if "</head>" in out else out
    out = out.replace("<title>Quem publica e quem não publica · Atlas da República</title>",
                      f'<title>Quem publica e quem não publica · Atlas da República</title>\n<link rel="canonical" href="{base}/quem-publica/">\n'
                      f'<meta property="og:title" content="Quem publica e quem não publica"><meta property="og:description" content="{esc(desc)}">'
                      f'<meta property="og:url" content="{base}/quem-publica/"><meta property="og:type" content="website">'
                      f'<meta property="og:image" content="{base}{prefix}/og/atlas.png"><meta property="og:image:width" content="1200">'
                      f'<meta property="og:image:height" content="630"><meta name="twitter:card" content="summary_large_image">', 1)
    out = out.replace("</html>", f'<script>window.ATLAS_PREFIX="{prefix}";</script><script src="{prefix}/atlas-menu.js" defer></script>\n</html>') if "</html>" in out \
        else out + f'<script>window.ATLAS_PREFIX="{prefix}";</script><script src="{prefix}/atlas-menu.js" defer></script>\n'
    d = site / "quem-publica"; d.mkdir(parents=True, exist_ok=True)
    (d / "index.html").write_text(out, encoding="utf-8")
    return f"{base}/quem-publica/"

if __name__ == "__main__":
    G = json.load(open(ROOT / "build" / "graph.br.json", encoding="utf-8"))
    print(build(ROOT / "site", "", "http://localhost:8765", G))
