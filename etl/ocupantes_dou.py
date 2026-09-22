#!/usr/bin/env python3
"""Ocupante de cargo vago, achado pelo CARGO no Diário Oficial → data/generated/ocupantes-dou.yaml

Problema: 118 cargos de chefia do Executivo no grafo não têm ocupante nenhum — o site mostra "sem ocupante
conhecido". São 69 reitorias de universidades, institutos e centros federais, 25 dirigentes de estatais
(empresa pública e sociedade de economia mista), 18 secretarias de segundo escalão, 3 autarquias e 3
fundações: justamente os órgãos cuja página oficial o projeto ainda não raspa e que o Wikidata não cobre.

Estratégia (inversa à de etl/posses.py, que busca pelo NOME de quem já se sabe estar no cargo): aqui se
busca pelo CARGO na busca pública do in.gov.br e extrai-se o NOME do ato. As funções de rede, paginação
por cursor e leitura do texto integral são reaproveitadas de etl/posses.py (import), a quem se credita a
mecânica de busca; a extração e o casamento são próprios, porque o que se conhece é o outro lado do par.

O QUE A BUSCA DO in.gov.br FAZ: `q` entre aspas é frase exata (com radicalização: "Reitora" acha "Reitor"),
vale para todas as seções e devolve do mais recente para o mais antigo. Não há limite de palavras na frase
— o que existe é a frase certa. Medindo: "cargo de Reitor da Universidade Federal de Alagoas" devolve ZERO
resultados, porque o decreto não escreve assim. Ele escreve:

    NOMEAR, a partir de 16 de agosto de 2026, JOÃO CARLOS SALLES PIRES DA SILVA, Professor da Universidade
    Federal da Bahia, para exercer o cargo de Reitor DA REFERIDA UNIVERSIDADE, com mandato de quatro anos.

Ou seja: nos decretos de reitor o nome da universidade aparece na QUALIFICAÇÃO da pessoa ("Professor da
..."), e o cargo vira "Reitor da referida Universidade". Por isso a escada de consultas termina numa
varredura por papel — "cargo de Reitor da referida" e "cargo de Reitor do referido" — compartilhada por
todas as reitorias (uma consulta serve 69 cargos, e o cache a torna um único acesso).

ESCADA DE CONSULTAS por cargo, da mais específica para a mais ampla (para em qualquer degrau que resolva):
  1. "para exercer o cargo de <cargo>"     — o ato de entrada, quando o ato escreve o cargo por extenso
  2. "cargo de <cargo>"                    — pega também "do cargo de" (exoneração) e "no cargo de"
  3. as duas acima sem "Fundação" e sem o nome do órgão pai, que o DOU ora escreve, ora não
  4. "cargo de <papel> da referida" / "do referido"  — varredura por papel, compartilhada entre cargos

A consulta pelo cargo NU ("Reitor da Universidade Federal de Mato Grosso") foi medida e descartada: devolve
55 páginas de portarias ASSINADAS pelo reitor — e ainda casa com a UFMS, porque a busca é aproximada nos
termos. Sem o "cargo de" na frente, o ruído é maior que o sinal.

CASAMENTO (nada é inventado; na dúvida o cargo fica sem ocupante):
  - o cargo citado no ato tem de casar com o cargo do grafo em TODOS os termos significativos, nos dois
    sentidos: termo faltando só se for genérico ("Fundação", "Educação", "Ciência", "Tecnologia") e termo
    sobrando só se for de papel ("Diretor"). É essa simetria que impede o ato da Universidade Federal de
    Mato Grosso DO SUL de ser colado na Universidade Federal de Mato Grosso, e o da Companhia Docas do
    CEARÁ na Companhia Docas do PARÁ.
  - "Vice-Reitor", "substituto eventual", "suplente" e "encargo de" são descartados.
  - confiança alta = cargo e órgão casam (o nome do órgão está no ato); média = só o cargo casa e o órgão
    vem da sigla ou da hierarquia do ato, ou a nomeação é pro tempore/interina.
  - escolhe-se o ato de NOMEAR/DESIGNAR/RECONDUZIR mais recente, varrendo do mais novo para o mais antigo;
    quem foi EXONERADO/DISPENSADO depois é descartado (a varredura de trás para frente já vê a saída antes
    da entrada, então a pessoa exonerada nunca é escolhida).

O QUE `started_at` SIGNIFICA: o dia em que o ato foi PUBLICADO no DOU, não o da posse (a mesma convenção de
etl/posses.py). Em reitoria o decreto costuma dizer "a partir de <data>", alguns dias depois.

Uso: .venv/bin/python etl/ocupantes_dou.py --amostra 8     (mistura reitoria, estatal e secretaria)
     .venv/bin/python etl/ocupantes_dou.py                  (todos os cargos sem ocupante)
     .venv/bin/python etl/ocupantes_dou.py --so-cache       (não vai à rede; usa só build/cache-dou/)
Cache: build/cache-dou/cargos/<consulta>.json (resultados) e build/cache-dou/textos/<ato>.txt (texto do
ato, o mesmo diretório que etl/dou.py e etl/posses.py já alimentam). Gravação parcial a cada 10 cargos.
"""
import json, re, sys, html, time, pathlib, datetime, argparse, urllib.parse
import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import posses  # busca paginada, recuo em 429/5xx e fold() — ver crédito no docstring

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "generated" / "ocupantes-dou.yaml"
CACHE = ROOT / "build" / "cache-dou"
BUSCA = CACHE / "cargos"
TEXTOS = CACHE / "textos"
FONTE = "Diário Oficial da União — busca pública www.in.gov.br/consulta (todas as seções), consulta pelo nome do cargo"

fold = posses.fold          # minúsculas sem acento, mantendo o comprimento (índices servem no texto original)

# "para" NÃO é palavra vazia aqui: é o que distingue a Companhia Docas do PARÁ da Companhia Docas do Ceará.
STOP = {"de", "da", "do", "das", "dos", "e", "em", "a", "o", "as", "os", "no", "na", "nos", "nas", "ao", "aos", "com"}
# termos genéricos de instituição: o ato pode omiti-los ("Fundação Universidade Federal de Mato Grosso" vira
# "Universidade Federal de Mato Grosso"; "Instituto Federal de Educação, Ciência e Tecnologia do Pará" vira
# "Instituto Federal do Pará"). O que distingue o órgão — o topônimo — continua obrigatório dos dois lados.
OPC_FALTA = {"fundaca", "educaca", "cienci", "tecnologi", "tecnologic"}
OPC_SOBRA = OPC_FALTA | {"diretor"}
RUIDO = re.compile(r"substitut|suplent|eventual|encargo|em substitui|respond")
INTERINO = re.compile(r"\binterin|pro tempor")
VETO_CARGO = re.compile(r"\bvice|\badjunt|\bsubstitut|\bsuplent")

VERBOS = {"nomear": "entrada", "nomeia": "entrada", "nomeado": "entrada", "nomeada": "entrada",
          "designar": "entrada", "designa": "entrada", "designado": "entrada", "designada": "entrada",
          "reconduzir": "entrada", "reconduzido": "entrada", "reconduzida": "entrada",
          "exonerar": "saida", "exonerado": "saida", "exonerada": "saida",
          "dispensar": "saida", "dispensado": "saida", "dispensada": "saida"}
VERB_RX = re.compile(r"\b(" + "|".join(VERBOS) + r")\b")
ATO_RX = re.compile(r"\bcargo\s+(?:em\s+comissao\s+)?de\s+|\bfuncao\s+(?:comissionada\s+)?de\s+")
# o cargo tem vírgulas ("Instituto Federal de Educação, Ciência e Tecnologia do Pará"): corta-se no fim da
# frase ou nas cláusulas que costumam seguir o cargo no DOU, nunca na primeira vírgula.
FIM_RX = re.compile(r"[.;(]|\s+[-–]\s+|,\s*(?:codigo|cce|das-|fcpe|fce|ficando|a partir|em substitui|na vaga|em vaga|"
                    r"na forma|nos termos|pelo prazo|com mandato|sem prejuizo|do quadro|"
                    r"para (?:o|um) (?:periodo|mandato)|e )")
CONECTOR_FINAL = re.compile(r"(?:,\s*)?(?:para exercer(?:,?\s*interinamente,?)?\s+o?\s*|para ocupar\s+o?\s*|"
                            r"para\s+o?\s*|d[oa]s?\s+|n[oa]s?\s+|ao\s+|o\s+|,\s*)$")
# tratamento, posto e patente que o DOU põe antes do nome ("o Contra-Almirante FRANCISCO ANDRÉ BARROS CONDE")
HONORIFICO_RX = re.compile(r"^(?:o|a|os|as)\s+|^(?:senhor(?:a|es)?|sr[a]?\.?|doutor(?:a)?|dr[a]?\.?|servidor(?:a)?|"
                           r"professor(?:a)?|general[a-z\- ]*|contra-almirante|vice-almirante|almirante|"
                           r"brigadeiro[a-z\- ]*|coronel|tenente[a-z\- ]*|major[a-z\- ]*|capitao[a-z\- ]*|"
                           r"embaixador(?:a)?|delegad[oa]|desembargador(?:a)?|juiz[a]?|conselheir[oa]|bacharel|"
                           r"servidor(?:es|as)?|senhor(?:es|as)|militar(?:es)?)\s+")
CONECT_NOME = {"de", "da", "do", "das", "dos", "e", "del", "dell", "van", "von"}
NOME_OK = re.compile(r"^[a-z][a-z'\-\. ]{5,79}$")
NOME_VETO = re.compile(r"\b(cargo|portaria|decreto|resolve|ministeri|secretari|art|inciso|lei|anexo|processo|"
                       r"conselho|comissao|diretoria|assembleia|nivel|codigo|tabela|quadro|efeitos)\b")
QUALIF_PAPEL = re.compile(r"^(?:professor(?:a)?|servidor(?:a)?|analista|auditor(?:a)?|engenheir[oa]|tecnic[oa]|"
                          r"especialista|pesquisador(?:a)?|docente)\b[^,]{0,40}?\s+d[aeo]s?\s+", re.I)


def toks(s):
    """Termos significativos com radical grosseiro (gênero/plural), aplicado igual dos dois lados."""
    out = []
    for t in re.split(r"[^a-z0-9]+", fold(s or "")):
        if not t or t in STOP or len(t) < 2: continue
        out.append(re.sub(r"(coes|oes|as|os|es|a|o|s)$", "", t) if len(t) > 4 else t)
    return out


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", fold(s or "")).strip("-")[:110]


def pid(nome):
    """Mesmo identificador de pessoa que scripts/build_graph.py monta para as outras camadas."""
    return "br-p-" + slug(nome)


def titulo(nome):
    """DOU escreve em caixa alta; o grafo guarda em caixa de título (build_graph rebaixa as preposições)."""
    return " ".join(w.capitalize() if len(w) > 1 else w.lower() for w in (nome or "").split())


def iso(pubdate):
    return f"{pubdate[6:10]}-{pubdate[3:5]}-{pubdate[0:2]}" if re.match(r"\d\d/\d\d/\d{4}", pubdate or "") else None


# ---------------------------------------------------------------- busca e texto (cache em build/cache-dou)
def buscar(q, desde, ate, so_cache=False, max_pages=3):
    """Uma consulta de frase exata, todas as seções, do mais recente para o mais antigo. Cacheada."""
    f = BUSCA / f"{slug(q)}--{max_pages}.json"
    if f.exists():
        try: return json.load(open(f, encoding="utf-8"))
        except Exception: pass
    if so_cache: return []
    hits, vistos, pagina, cursor = [], set(), 1, {}
    while pagina <= max_pages:
        pag, total = posses._pagina(q, desde, ate, cursor)
        novos = [x for x in pag if x.get("urlTitle") not in vistos]
        if not novos: break
        for x in novos: vistos.add(x["urlTitle"]); hits.append(x)
        if pagina >= total: break
        u = pag[-1]
        cursor = {"currentPage": pagina, "newPage": pagina + 1, "score": u.get("score", 0),
                  "id": u.get("classPK"), "displayDate": u.get("displayDateSortable")}
        pagina += 1
    f.parent.mkdir(parents=True, exist_ok=True)
    json.dump(hits, open(f, "w", encoding="utf-8"), ensure_ascii=False)
    return hits


def texto_ato(url_title, so_cache=False):
    """Texto integral do ato. Reaproveita os textos que etl/dou.py e etl/posses.py já baixaram."""
    f = TEXTOS / (url_title[:150] + ".txt")
    if f.exists(): return f.read_text(encoding="utf-8")
    g = posses.CACHE / "textos" / (url_title[:150] + ".txt")
    if g.exists(): return g.read_text(encoding="utf-8")
    if so_cache: return ""
    h = posses.get("https://www.in.gov.br/web/dou/-/" + url_title)
    m = (re.search(r'<div[^>]*class="texto-dou"[^>]*>(.*?)<div class="rodape', h, re.S)
         or re.search(r'<p class="identifica">(.*?)<p class="assina">', h, re.S))
    t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", m.group(1) if m else h))).strip()
    if t: f.parent.mkdir(parents=True, exist_ok=True); f.write_text(t, encoding="utf-8")
    return t


# ---------------------------------------------------------------- extração: verbo → nome → cargo
def parse_entre(entre):
    """O que separa o verbo do cargo tem de ser só o nome (e, opcionalmente, a qualificação da pessoa).

    "NOMEAR, a partir de 16 de agosto de 2026, JOÃO CARLOS SALLES PIRES DA SILVA, Professor da Universidade
    Federal da Bahia, para exercer o " → ("JOÃO CARLOS SALLES PIRES DA SILVA", "Professor da Universidade
    Federal da Bahia"). Qualquer coisa fora desse molde devolve (None, None): nome ambíguo não se aceita.
    """
    if not entre or len(entre) > 300: return None, None
    m = CONECTOR_FINAL.search(fold(entre))
    if not m: return None, None                       # sem conector explícito o nome não governa o cargo
    e = entre[:m.start()].strip(" ,:;-")
    if not e: return None, None
    # O DOU intercala cláusulas entre o verbo e o nome ("EXONERAR, ex officio, a partir de 9 de dezembro de
    # 2025, por necessidade do serviço, o Contra-Almirante FRANCISCO ANDRÉ BARROS CONDE, do Comando da
    # Marinha, do cargo de ..."). Anda-se pelos trechos separados por vírgula: o primeiro que for um nome
    # de gente é a pessoa; os anteriores só podem ser cláusulas (minúsculas ou com número).
    segs = [s.strip(" ,:;-") for s in e.split(",")][:7]
    for i, s in enumerate(segs):
        if not s: continue
        n = nome_de_gente(s)
        if n: return n, ", ".join(x for x in segs[i + 1:] if x)
        if s[:1].isupper() and not re.search(r"\d", fold(s)): return None, None   # parece nome e não é: não arrisca
    return None, None


def nome_de_gente(seg):
    """O trecho é um nome de pessoa? Devolve o nome limpo ou None. Nome no DOU vem em CAIXA ALTA ou em
    Caixa de Título — "por necessidade do serviço" e "ex officio" são cláusulas, e é a maiúscula que
    separa uma coisa da outra."""
    nome = seg.strip(" ,:;-")
    while True:                                       # "o Contra-Almirante FULANO", "a Senhora FULANA"
        m = HONORIFICO_RX.match(fold(nome))
        if not m or m.end() >= len(nome): break
        nome = nome[m.end():].lstrip(" ,:;-")
    fn = fold(nome)
    if not NOME_OK.match(fn) or NOME_VETO.search(fn): return None
    if not (2 <= len(nome.split()) <= 9): return None
    if any(len(w) > 1 and not re.match(r"^[a-z'\-\.]+$", fold(w)) for w in nome.split()): return None
    fortes = [w for w in nome.split() if len(w) >= 3 and fold(w) not in CONECT_NOME]
    if len(fortes) < 2 or any(not w[0].isupper() for w in fortes): return None
    return nome


def eventos_do_ato(texto, hit):
    """Todos os pares verbo+nome+cargo de um ato. Um mesmo documento traz dezenas de portarias."""
    t = re.sub(r"\s+", " ", texto or "")
    ft = fold(t)
    data = iso(hit.get("pubDate"))
    if not data: return []
    out = []
    for m in ATO_RX.finditer(ft):
        ini = m.end()
        f2 = FIM_RX.search(ft[ini:ini + 220])
        cargo = t[ini:ini + (f2.start() if f2 else 220)].strip(" ,;.")
        if len(cargo) < 4: continue
        antes_ini = max(0, m.start() - 450)
        vs = list(VERB_RX.finditer(ft[antes_ini:m.start()]))
        if not vs: continue
        v = vs[-1]
        entre = t[antes_ini + v.end():m.start()]
        if RUIDO.search(fold(entre)) or RUIDO.search(fold(cargo)): continue
        nome, qualif = parse_entre(entre)
        if not nome: continue
        out.append({"data": data, "tipo": VERBOS[v.group(1)], "verbo": v.group(1), "nome": nome,
                    "qualif": qualif, "cargo": cargo, "interino": bool(INTERINO.search(fold(entre + " " + cargo))),
                    "hier": hit.get("hierarchyList") or [], "secao": hit.get("pubName"),
                    "ato": hit.get("title"), "url": "https://www.in.gov.br/web/dou/-/" + hit["urlTitle"]})
    return out


# ---------------------------------------------------------------- casamento cargo/órgão
def conjuntos(alvo, frase=None):
    """(termos do papel, termos do órgão) do cargo no grafo."""
    org = set(toks(alvo["org_nome"]))
    cargo = set(toks(frase or alvo["cargo_busca"]))
    return cargo - org, org


def casa_termos(alvo_set, ato_set, opc_falta=OPC_FALTA, opc_sobra=OPC_SOBRA):
    """Simetria: o que falta no ato só pode ser genérico, e o que sobra no ato também."""
    if (alvo_set - ato_set) - opc_falta: return False
    if (ato_set - alvo_set) - opc_sobra: return False
    return True


def casar(ev, alvo):
    """(confiança, critério) do evento contra o cargo do grafo, ou (None, motivo).

    O cargo do grafo é comparado nas duas formas: sem o nome do órgão pai ("Secretário de Acompanhamento e
    Gestão de Assuntos Estratégicos") e com ele ("... do Gabinete de Segurança Institucional da Presidência
    da República"), porque o DOU usa ora uma, ora outra. Basta uma casar.
    """
    fcargo = fold(ev["cargo"])
    if VETO_CARGO.search(fcargo): return None, "cargo do ato é vice/adjunto/substituto"
    ato_cargo = set(toks(ev["cargo"]))
    ref = re.match(r"(.+?)\s+d[ao]s?\s+referid[oa]\b", fcargo)
    ctx = fold(ev["cargo"] + " " + (ev["qualif"] or "") + " " + " ".join(ev["hier"]))
    # só siglas de verdade: "SE" (alias de Secretaria-Executiva) casaria com o "se" de qualquer frase
    siglas = [s for s in alvo["org_aliases"] if 3 <= len(s) <= 14 and sum(1 for ch in s if ch.isupper()) >= 3]
    sigla_ok = any(re.search(r"\b" + re.escape(fold(s)) + r"\b", ctx) for s in siglas)
    # a sigla do órgão colada ao nome no ato ("Companhia Docas do Pará CDP") não conta como termo sobrando
    sobra_ok = OPC_SOBRA | {t for s in siglas for t in toks(s)}
    motivo = None
    for frase in dict.fromkeys([alvo["cargo_busca"], alvo["cargo_nome"]]):
        papel, org = conjuntos(alvo, frase)
        if ref:
            # "Reitor da referida Universidade": o órgão está na qualificação ("Professor da UFBA")
            if not papel or set(toks(ref.group(1))) != papel:
                motivo = motivo or f"papel do ato ({ref.group(1)}) ≠ papel do cargo"
                continue
            qorg = QUALIF_PAPEL.sub("", ev["qualif"] or "").strip(" ,;.")
            if qorg and casa_termos(org, set(toks(qorg)), OPC_FALTA, sobra_ok):
                return ("media" if ev["interino"] else "alta"), f"papel casa e o órgão vem da qualificação no ato ({qorg[:70]})"
            if sigla_ok: return "media", "papel casa e a sigla do órgão aparece no ato"
            motivo = motivo or f"papel casa mas o órgão do ato ({qorg[:60] or '—'}) não é o do grafo"
            continue
        if not casa_termos(papel | org, ato_cargo, OPC_FALTA, sobra_ok):
            motivo = motivo or f"cargo do ato ({ev['cargo'][:70]}) não casa em todos os termos"
            continue
        if org <= ato_cargo or casa_termos(org, ato_cargo - papel, OPC_FALTA, sobra_ok):
            return ("media" if ev["interino"] else "alta"), "cargo e órgão do grafo aparecem por extenso no ato"
        if sigla_ok or casa_termos(org, set(toks(" ".join(ev["hier"]))), OPC_FALTA, sobra_ok):
            return "media", "cargo casa e o órgão vem da sigla ou da hierarquia do ato"
        return "media", "cargo casa por extenso; órgão não confirmado no ato"
    return None, motivo or "cargo do ato não casa com o do grafo"


def escolher(eventos, alvo):
    """Do mais novo para o mais antigo: quem saiu depois não entra. Devolve (evento, confiança, critério)."""
    fora = set()
    ordem = sorted(eventos, key=lambda e: (e["data"], 1 if e["tipo"] == "saida" else 0), reverse=True)
    motivos = []
    for ev in ordem:
        conf, crit = casar(ev, alvo)
        if not conf: motivos.append(crit); continue
        chave = fold(ev["nome"])
        if ev["tipo"] == "saida": fora.add(chave); continue
        if chave in fora: continue
        return ev, conf, crit
    return None, None, (motivos[0] if motivos else None)


# ---------------------------------------------------------------- alvos e consultas
TIPOS = {"instituicao_de_ensino": "reitoria", "empresa_publica": "estatal", "sociedade_economia_mista": "estatal",
         "autarquia": "autarquia", "fundacao": "fundacao"}


def alvos(graph):
    """Cargos de chefia do Executivo sem nenhum ocupante no grafo.

    Fora ficam os tribunais: presidente de tribunal é eleito pelos próprios desembargadores e a posse não
    sai como ato de nomeação no DOU — buscá-los aqui só traria falso positivo.
    """
    nodes = graph["nodes"]
    out = []
    for n in nodes.values():
        if n.get("type") != "dept_head" or (n.get("people") or []): continue
        if n.get("sector") != "executivo": continue
        org = nodes.get(n.get("head_of") or "", {})
        pai = nodes.get(org.get("parent") or "", {})
        cargo = n["name"]
        curto = cargo
        for p in (pai.get("name") or "", org.get("name") or ""):
            if p and len(p) > 6:
                curto = re.sub(r"\s+d[oa]s?\s+" + re.escape(p) + r"\s*$", "", curto).strip()
        if len(toks(curto)) < 2: curto = cargo
        out.append({"cargo_id": n["id"], "cargo_nome": cargo, "cargo_busca": curto,
                    "org_id": org.get("id"), "org_nome": org.get("name") or "",
                    "org_aliases": org.get("aliases") or [], "tipo": TIPOS.get(org.get("subtype") or "", "secretaria")})
    return sorted(out, key=lambda a: (a["tipo"], a["cargo_id"]))


def papel_frase(alvo):
    """O papel que encabeça o cargo, como frase ("Reitor", "Diretor-Geral", "Secretário-Executivo")."""
    c = alvo["cargo_busca"]
    m = re.match(r"([A-Za-zÀ-ÿ]+(?:-[A-Za-zÀ-ÿ]+)?)", c)
    return m.group(1) if m else c


def escada(alvo):
    """Consultas da mais específica para a mais ampla; as duas últimas são compartilhadas por papel."""
    qs = []
    # a vírgula do nome do órgão ("Fundação Jorge Duprat Figueiredo, de Segurança e Medicina do Trabalho")
    # não existe na frase do ato: tira-se para a consulta, o casamento depois é por termos.
    limpa = lambda s: re.sub(r"\s+", " ", re.sub(r"\s*,\s*", " ", s)).strip()
    # "Reitor da Fundação Universidade Federal de X" no grafo é "Reitor da Universidade Federal de X" no ato
    sem_f = lambda s: re.sub(r"\bFunda[çc][ãa]o\s+(?=Universidade|Instituto|Centro|Escola)", "", s)
    frases = dict.fromkeys([f(limpa(c)) for c in (alvo["cargo_busca"], alvo["cargo_nome"]) for f in (lambda x: x, sem_f)])
    for c in frases:
        qs += [(f"para exercer o cargo de {c}", 3, False), (f"cargo de {c}", 3, False)]
    p = papel_frase(alvo)
    # varredura por papel: compartilhada entre todos os cargos do mesmo papel (um acesso serve 69 reitorias)
    qs += [(f"cargo de {p} da referida", 12, True), (f"cargo de {p} do referido", 12, True)]
    return qs


# ---------------------------------------------------------------- execução
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", default="2018-01-01", help="reitoria e estatal têm mandato de 4 anos")
    ap.add_argument("--ate", default=None)
    ap.add_argument("--amostra", type=int, default=0, help="N cargos misturando reitoria, estatal e secretaria")
    ap.add_argument("--limite", type=int, default=0)
    ap.add_argument("--so-tipos", default=None, help="reitoria,estatal,secretaria,autarquia,fundacao")
    ap.add_argument("--max-atos", type=int, default=60, help="teto de textos de ato baixados por cargo")
    ap.add_argument("--pause", type=float, default=1.1, help="segundos entre consultas (≥1 por educação)")
    ap.add_argument("--so-cache", action="store_true")
    a = ap.parse_args()
    posses.PAUSE["s"] = max(1.0, a.pause)
    desde = datetime.date.fromisoformat(a.desde)
    ate = datetime.date.fromisoformat(a.ate) if a.ate else datetime.date.today()
    hoje = datetime.date.today().isoformat()

    graph = json.load(open(ROOT / "build" / "graph.br.json", encoding="utf-8"))
    lista = alvos(graph)
    total_alvo = len(lista)
    por_tipo_alvo = {}
    for x in lista: por_tipo_alvo[x["tipo"]] = por_tipo_alvo.get(x["tipo"], 0) + 1
    if a.so_tipos:
        aceita = {t.strip() for t in a.so_tipos.split(",")}
        lista = [x for x in lista if x["tipo"] in aceita]
    if a.amostra:                                   # round-robin entre os tipos, para a amostra ser mista
        baldes = {}
        for x in lista: baldes.setdefault(x["tipo"], []).append(x)
        mix = []
        while len(mix) < a.amostra and any(baldes.values()):
            for t in sorted(baldes):
                if baldes[t] and len(mix) < a.amostra: mix.append(baldes[t].pop(0))
        lista = mix
    if a.limite: lista = lista[:a.limite]
    print(f"{total_alvo} cargos sem ocupante ({por_tipo_alvo}); processando {len(lista)} "
          f"(janela {desde} a {ate})", file=sys.stderr, flush=True)

    cache_ev = {}                                   # urlTitle → eventos (um ato é lido uma vez só)
    positions, nao, detalhe = {}, [], []
    t0 = time.time()
    for i, alvo in enumerate(lista, 1):
        eventos, baixados, consultas, achou = [], 0, 0, None
        for q, pags, sweep in escada(alvo):
            hits = buscar(q, desde, ate, a.so_cache, pags)
            consultas += 1
            # a varredura por papel é lida inteira uma vez só e fica no cache para os demais cargos do papel
            teto = 10 ** 6 if sweep else a.max_atos
            for h in sorted(hits, key=lambda x: iso(x.get("pubDate")) or "", reverse=True):
                k = h.get("urlTitle")
                if not k: continue
                if k not in cache_ev:
                    trecho = re.sub(r"<[^>]+>", " ", html.unescape(h.get("content") or "")) + " " + (h.get("title") or "")
                    if not VERB_RX.search(fold(trecho)) and not re.search(r"decreto", fold(h.get("artType") or "")):
                        cache_ev[k] = []; continue
                    if baixados >= teto: continue
                    txt = texto_ato(k, a.so_cache)
                    baixados += 1
                    cache_ev[k] = eventos_do_ato(txt, h) if txt else []
                eventos.extend(cache_ev[k])
            ev, conf, crit = escolher(eventos, alvo)
            if ev: achou = (ev, conf, crit); break
        if not achou:
            nao.append(alvo["cargo_id"])
            detalhe.append({"cargo_id": alvo["cargo_id"], "cargo": alvo["cargo_nome"], "tipo": alvo["tipo"],
                            "consultas": consultas, "atos_lidos": baixados,
                            "motivo": (crit or "nenhum ato de nomeação citando o cargo")[:180]})
        else:
            ev, conf, crit = achou
            nome = titulo(ev["nome"])
            # mandato de reitoria e de diretoria de estatal é de 4 anos: ato muito antigo pode estar vencido
            vencido = (alvo["tipo"] != "secretaria"
                       and ev["data"] < (datetime.date.today() - datetime.timedelta(days=int(365.25 * 4.5))).isoformat())
            if vencido: conf = "media"
            positions[alvo["cargo_id"]] = [{
                "id": pid(nome), "name": nome, "started_at": ev["data"], "entry_mode": "nomeado",
                "acting": bool(ev["interino"]), "source": "dou",
                "source_url": ev["url"], "checked_at": hoje, "verified": False,
                "confianca": conf, "criterio": crit, "ato": f"{ev['ato']} ({ev['secao']}, {ev['data']})",
                "cargo_no_ato": ev["cargo"][:160],
                "note": (f"{ev['verbo'].upper()} publicado no DOU em {ev['data'][8:10]}/{ev['data'][5:7]}/{ev['data'][:4]}; "
                         f"cargo no ato: \"{ev['cargo'][:90]}\". Data = publicação do ato, não a posse."
                         + (" Nomeação interina/pro tempore." if ev["interino"] else "")
                         + (" É o ato mais recente do cargo no DOU, mas o mandato de quatro anos já venceu: "
                            "pode haver sucessor não publicado com esta redação." if vencido else ""))}]
        if i % 5 == 0 or i == len(lista):
            print(f"  {i}/{len(lista)} — {len(positions)} resolvidos, {len(nao)} sem ato "
                  f"({(time.time() - t0) / i:.1f}s/cargo)", file=sys.stderr, flush=True)
        if i % 10 == 0 or i == len(lista):
            gravar(positions, nao, detalhe, lista, total_alvo, por_tipo_alvo, desde, ate)
    gravar(positions, nao, detalhe, lista, total_alvo, por_tipo_alvo, desde, ate)
    print(f"resolvidos={len(positions)} sem ato={len(nao)} → {OUT}")


def gravar(positions, nao, detalhe, lista, total_alvo, por_tipo_alvo, desde, ate):
    tipo_de = {x["cargo_id"]: x["tipo"] for x in lista}
    por_conf, por_tipo = {}, {}
    for cid, ppl in positions.items():
        c = ppl[0]["confianca"]
        por_conf[c] = por_conf.get(c, 0) + 1
        t = tipo_de.get(cid, "?")
        por_tipo[t] = por_tipo.get(t, 0) + 1
    doc = {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "fonte": FONTE,
        "nota": ("Ocupante achado buscando o CARGO no DOU (o inverso de etl/posses.py, que busca o nome). "
                 "started_at = dia da PUBLICAÇÃO do ato de nomeação/designação/recondução, não o da posse. "
                 "Só entra quando o cargo citado no ato casa com o cargo do grafo em todos os termos "
                 "significativos; confiança alta = cargo e órgão casam, média = só o cargo casa (órgão vindo "
                 "da sigla ou da hierarquia do ato) ou a nomeação é interina. Ato de exoneração/dispensa "
                 "posterior descarta a pessoa. Em reitoria e estatal, ato anterior a quatro anos e meio "
                 "cai para média: é o mais recente do DOU, mas o mandato já venceu."),
        "janela": {"de": desde.isoformat(), "ate": ate.isoformat()},
        "positions": dict(sorted(positions.items())),
        "nao_encontrados": sorted(nao),
        "nao_encontrados_detalhe": detalhe,
        "resumo": {"cargos_alvo": total_alvo, "cargos_alvo_por_tipo": por_tipo_alvo,
                   "cargos_processados": len(lista), "resolvidos": len(positions),
                   "por_confianca": por_conf, "por_tipo": por_tipo, "sem_ato": len(nao)},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("# GERADO por etl/ocupantes_dou.py. Não edite à mão.\n")
        yaml.safe_dump(doc, f, allow_unicode=True, sort_keys=False, width=200)


if __name__ == "__main__": main()
