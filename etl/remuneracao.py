#!/usr/bin/env python3
"""Remuneração mensal, por pessoa, dos ocupantes de cargos do grafo → data/generated/remuneracao.yaml.

Fontes nominais:
  • Executivo federal (e essenciais à Justiça que estão no SIAPE): Portal da Transparência, download mensal
    "Servidores civis (SIAPE)" — mesmo arquivo usado por etl/teto.py. Cadastro (nome, cargo, função, órgão de
    exercício e de lotação) + Remuneração (básica bruta, gratificação natalina, férias, eventuais, abate-teto,
    verbas indenizatórias, líquido após deduções obrigatórias).
  • Senado Federal: folha mensal nominal da API administrativa de dados abertos
    (/servidores/remuneracoes/{ano}/{mes}/csv) — ela traz os senadores, com subsídio, auxílios e líquido.
  • Câmara dos Deputados: NÃO há fonte nominal. O relatório consolidado mensal da Câmara é pseudonimizado
    ("Deputado 11530"), e a consulta nominal cobre apenas servidores. Nada é inventado para deputados.

Casamento (nunca aceita ambiguidade; em caso de dúvida não grava):
  1. nome_completo        — nome normalizado sem acentos/preposições, servidor único na folha (confiança alta)
  2. nome_sem_sufixo      — idem, ignorando Filho/Júnior/Neto etc. (alta)
  3. primeiro_ultimo      — primeiro nome + último sobrenome, único DENTRO do órgão do ocupante (média)
  4. subsequencia_orgao   — tokens do nome do ocupante contidos, em ordem, no nome da folha, único no órgão (média)
  Qualquer nível pode ser desempatado pelo órgão (sufixo "+orgao" no critério), via SIORG/hierarquia do grafo
  casada com o órgão de exercício/lotação e o órgão superior da folha.

Uso: .venv/bin/python etl/remuneracao.py [--mes AAAAMM] [--debug]
"""
import csv, io, sys, zipfile, pathlib, datetime, argparse, re, unicodedata, json, collections, urllib.request, time

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / "build" / "cache-teto"
CACHE_SEN = ROOT / "build" / "cache-gabinetes"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh) atlas-da-republica/0.1", "Accept": "text/csv,application/json"}
SEN_API = "https://adm.senado.gov.br/adm-dadosabertos/api/v1"
SIAPE_URL = "https://portaldatransparencia.gov.br/servidores/"
FONTE_SIAPE = "Portal da Transparência, remuneração de servidores civis (SIAPE)"
FONTE_SENADO = "Senado Federal, folha de pagamento mensal (API administrativa de dados abertos)"
SUBSIDIO = 46366.19  # subsídio de ministro do STF = teto = subsídio de parlamentar (Lei 14.520/2023)
# empresas estatais e entidades com folha própria não entram no SIAPE
FORA_DO_SIAPE = {"empresa_publica", "sociedade_economia_mista"}
# entidades que, quando estão no SIAPE, aparecem como órgão próprio na folha
ENTIDADES_COM_FOLHA = {"autarquia", "fundacao", "agencia_reguladora", "orgao_autonomo", "instituicao_de_ensino"}

PREP = {"de", "da", "do", "das", "dos", "e", "del", "di", "du", "la", "van", "von", "y", "d",
        "em", "no", "na", "nos", "nas", "a", "ao", "aos", "as"}
SUF = {"filho", "filha", "junior", "jr", "neto", "neta", "netto", "sobrinho", "segundo", "terceiro"}
# sobrenomes frequentes demais para servirem de chave, mesmo dentro de um órgão
SOBRENOMES_COMUNS = {
    "silva", "santos", "souza", "sousa", "oliveira", "pereira", "lima", "costa", "ferreira", "rodrigues", "almeida",
    "nascimento", "carvalho", "gomes", "martins", "araujo", "ribeiro", "alves", "monteiro", "barbosa", "rocha",
    "dias", "moraes", "morais", "freitas", "cardoso", "teixeira", "correa", "cavalcante", "cavalcanti", "melo",
    "mello", "castro", "campos", "barros", "moura", "azevedo", "fernandes", "vieira", "machado", "pinto", "ramos",
    "borges", "medeiros", "nunes", "marques", "reis", "batista", "freire", "andrade", "mendes", "miranda", "cruz",
    "leite", "duarte", "santana", "xavier", "figueiredo", "rezende", "resende", "soares", "guimaraes", "coelho",
    "lopes", "neves", "farias", "goncalves", "menezes", "junior", "filho", "neto", "brito", "maia", "pinheiro"}


def money(s):
    return float(str(s or "0").replace(".", "").replace(",", ".") or 0)


def norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())).strip()


def toks(s):
    return [t for t in norm(s).split() if t and t not in PREP]


def kfull(s):
    return " ".join(toks(s))


def kbase(s):
    t = toks(s)
    while len(t) > 2 and t[-1] in SUF:
        t.pop()
    return " ".join(t)


def kfl(s):
    t = kbase(s).split()
    return t[0] + " " + t[-1] if len(t) >= 2 else ""


def subseq(small, big):
    """tokens de `small` aparecem, em ordem, em `big` (prefixo de 4+ letras, ou inicial)."""
    i = 0
    for b in big:
        if i >= len(small):
            break
        s = small[i]
        if b == s or (len(s) >= 4 and b.startswith(s)) or (len(b) >= 4 and s.startswith(b)) or (len(s) == 1 and b.startswith(s)):
            i += 1
    return i == len(small)


# ---------------------------------------------------------------- grafo
def carrega_grafo():
    g = json.load(open(ROOT / "build" / "graph.br.json", encoding="utf-8"))
    N = g["nodes"]
    dept = {n["id"]: n for n in N.values() if n["type"] == "department"}
    chain_cache = {}

    def chain(did):
        if did in chain_cache:
            return chain_cache[did]
        out, cur, seen = [], did, set()
        while cur and cur in dept and cur not in seen:
            seen.add(cur)
            out.append(cur)
            cur = dept[cur].get("parent")
        chain_cache[did] = out
        return out

    occ = []
    for n in N.values():
        if n["type"] not in ("dept_head", "elected"):
            continue
        for h in n.get("people") or []:
            if not (h.get("id") and h.get("name")):
                continue
            occ.append({"pid": h["id"], "nome": h.get("full_name") or h["name"], "curto": h["name"], "node": n["id"],
                        "node_name": n["name"], "dept": n.get("head_of"), "setor": n.get("sector") or "executivo"})
    # um ocupante pode ocupar dois cargos (a folha é da pessoa, não do cargo): fica o que tem órgão
    vistos = {}
    for o in occ:
        cur = vistos.get(o["pid"])
        if cur is None or (not cur["dept"] and o["dept"]):
            vistos[o["pid"]] = o
    return N, dept, chain, list(vistos.values())


def indice_orgaos(dept):
    """nome normalizado de órgão → id do nó de departamento (nome + apelidos)."""
    ix = {}
    for d in dept.values():
        for k in [d["name"]] + list(d.get("aliases") or []):
            ix.setdefault(kfull(k), d["id"])
    return ix


def casa_orgao(nome, ix, dept):
    """casa o nome de órgão da folha (abreviado/caixa alta) com um nó do grafo."""
    k = kfull(re.sub(r"^fun[cç][aã]o ", "", nome or "", flags=re.I))
    if k in ix:
        return ix[k]
    a = k.split()
    if len(a) < 2:
        return None
    hits = {}
    for d in dept.values():
        for cand in [d["name"]] + list(d.get("aliases") or []):
            b = kfull(cand).split()
            if len(b) < len(a):
                continue
            i = 0
            for t in b:
                if i < len(a) and t.startswith(a[i]) and len(a[i]) >= 3:
                    i += 1
            if i == len(a):
                hits[d["id"]] = min(hits.get(d["id"], 99), len(b))
    if not hits:
        return None
    # "MIN DESENV ASSIS SOCI FAMIL COMBATE FOME" casa com o ministério e com sua secretaria-executiva:
    # fica o nome mais curto (o órgão em si); empate continua sendo ambiguidade e não casa
    menor = min(hits.values())
    curtos = [k for k, v in hits.items() if v == menor]
    return curtos[0] if len(curtos) == 1 else None


# ---------------------------------------------------------------- SIAPE
def le_siapé(zpath, quer_keys, quer_firsts, quer_lasts, orgs_relevantes, ix_org, dept):
    """varre o Cadastro guardando só linhas que podem interessar; devolve índices e o mapa órgão→nó."""
    z = zipfile.ZipFile(zpath)
    cad = [x for x in z.namelist() if x.endswith("Cadastro.csv")][0]
    full, base, fl, porg = collections.defaultdict(list), collections.defaultdict(list), collections.defaultdict(list), collections.defaultdict(list)
    org_node, org_nome, total = {}, {}, 0
    with z.open(cad) as f:
        r = csv.reader(io.TextIOWrapper(f, encoding="latin1"), delimiter=";")
        head = next(r)
        ix = {h: i for i, h in enumerate(head)}
        for row in r:
            try:
                nome = row[ix["NOME"]]
                sid = row[ix["Id_SERVIDOR_PORTAL"]]
            except IndexError:
                continue
            total += 1
            kf, kb = kfull(nome), kbase(nome)
            t = kb.split()
            k3 = (t[0] + " " + t[-1]) if len(t) >= 2 else ""
            hit_key = kf in quer_keys or kb in quer_keys or (k3 and k3 in quer_keys)
            cods = [row[ix[c]] for c in ("COD_ORG_EXERCICIO", "COD_ORGSUP_EXERCICIO", "COD_ORG_LOTACAO", "COD_ORGSUP_LOTACAO") if c in ix]
            hit_org = bool(orgs_relevantes & set(cods)) and t and (t[0] in quer_firsts or t[-1] in quer_lasts)
            if not (hit_key or hit_org):
                continue
            for c, nm in ((row[ix["COD_ORG_EXERCICIO"]], row[ix["ORG_EXERCICIO"]]), (row[ix["COD_ORGSUP_EXERCICIO"]], row[ix["ORGSUP_EXERCICIO"]]),
                          (row[ix["COD_ORG_LOTACAO"]], row[ix["ORG_LOTACAO"]]), (row[ix["COD_ORGSUP_LOTACAO"]], row[ix["ORGSUP_LOTACAO"]])):
                org_nome.setdefault(c, nm)
            rec = {"sid": sid, "nome": nome, "toks": t, "cargo": row[ix["DESCRICAO_CARGO"]], "funcao": row[ix["FUNCAO"]],
                   "orgao": row[ix["ORG_EXERCICIO"]], "orgsup": row[ix["ORGSUP_EXERCICIO"]], "vinculo": row[ix["TIPO_VINCULO"]],
                   "uorg": row[ix["UORG_EXERCICIO"]], "cods": cods}
            if hit_key:
                full[kf].append(rec)
                base[kb].append(rec)
                if k3:
                    fl[k3].append(rec)
            for c in set(cods) & orgs_relevantes:
                if len(porg[c]) < 60000:
                    porg[c].append(rec)
    for c, nm in org_nome.items():
        org_node[c] = casa_orgao(nm, ix_org, dept)
    return z, full, base, fl, porg, org_node, org_nome, total


def le_remuneracao_siape(z, sids):
    rem = [x for x in z.namelist() if x.endswith("Remuneracao.csv")][0]
    out = {}
    with z.open(rem) as f:
        r = csv.reader(io.TextIOWrapper(f, encoding="latin1"), delimiter=";")
        head = next(r)
        ix = {h: i for i, h in enumerate(head)}
        i_ind = next((i for h, i in ix.items() if h.startswith("TOTAL DE VERBAS INDENIZATÓRIAS (R$)")), None)
        i_civ = next((i for h, i in ix.items() if h.startswith("VERBAS INDENIZATÓRIAS REGISTRADAS EM SISTEMAS DE PESSOAL - CIVIL (R$)")), None)
        for row in r:
            sid = row[ix["Id_SERVIDOR_PORTAL"]]
            if sid not in sids:
                continue
            basica = money(row[ix["REMUNERAÇÃO BÁSICA BRUTA (R$)"]])
            natal = money(row[ix["GRATIFICAÇÃO NATALINA (R$)"]])
            ferias = money(row[ix["FÉRIAS (R$)"]])
            event = money(row[ix["OUTRAS REMUNERAÇÕES EVENTUAIS (R$)"]])
            # no arquivo o abate-teto vem negativo (é um corte); guarda-se a magnitude
            abate = abs(money(row[ix["ABATE-TETO (R$)"]])) + abs(money(row[ix["ABATE-TETO DA GRATIFICAÇÃO NATALINA (R$)"]]))
            ind = money(row[i_ind]) if i_ind is not None else (money(row[i_civ]) if i_civ is not None else 0.0)
            liq = money(row[ix["REMUNERAÇÃO APÓS DEDUÇÕES OBRIGATÓRIAS (R$)"]])
            a = out.setdefault(sid, {"basica": 0.0, "natalina": 0.0, "ferias": 0.0, "eventuais": 0.0, "abate": 0.0, "ind": 0.0, "liquido": 0.0})
            a["basica"] += basica; a["natalina"] += natal; a["ferias"] += ferias; a["eventuais"] += event
            a["abate"] += abate; a["ind"] += ind; a["liquido"] += liq
    return out


# ---------------------------------------------------------------- Senado
def folha_senado(hoje):
    """CSV nominal da folha do Senado (reaproveita o cache de etl/gabinetes_senado.py). → (linhas, 'AAAAMM')"""
    CACHE_SEN.mkdir(parents=True, exist_ok=True)
    d = hoje.replace(day=1) - datetime.timedelta(days=1)
    for _ in range(5):
        p = CACHE_SEN / f"sen_rem_{d.year}{d.month:02d}.csv"
        txt = p.read_text(encoding="utf-8") if p.exists() else None
        if txt is None:
            try:
                url = f"{SEN_API}/servidores/remuneracoes/{d.year}/{d.month}/csv"
                print("GET", url, file=sys.stderr)
                txt = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180).read().decode("utf-8", "ignore")
                p.write_text(txt, encoding="utf-8")
            except Exception as e:
                print("folha do Senado indisponível:", e, file=sys.stderr)
                txt = ""
            time.sleep(0.5)
        if txt and txt.count("\n") > 100:
            return list(csv.DictReader(io.StringIO(txt), delimiter=";")), f"{d.year}{d.month:02d}"
        d = d.replace(day=1) - datetime.timedelta(days=1)
    return [], None


def rec_senado(rows, mes):
    """agrega as linhas (Normal + Suplementar) de uma mesma pessoa na folha do Senado."""
    g = {"basica": 0.0, "pessoais": 0.0, "funcao": 0.0, "natalina": 0.0, "eventuais": 0.0, "abono": 0.0,
         "abate": 0.0, "liquido": 0.0, "ind": 0.0}
    for r in rows:
        g["basica"] += money(r.get("REMUNERAÇÃO BÁSICA"))
        g["pessoais"] += money(r.get("VANTAGENS PESSOAIS"))
        g["funcao"] += money(r.get("FUNÇÃO COMISSIONADA"))
        g["natalina"] += money(r.get("GRATIFICAÇÃO NATALINA"))
        g["eventuais"] += money(r.get("HORAS EXTRAS")) + money(r.get("OUTRAS EVENTUAIS"))
        g["abono"] += money(r.get("ABONO PERMANÊNCIA"))
        g["abate"] += abs(money(r.get("REVERSÃO TETO CONSTITUCIONAL")))
        g["liquido"] += money(r.get("REMUNERAÇÃO LÍQUIDA"))
        g["ind"] += money(r.get("VANTAGENS INDENIZATÓRIAS")) + money(r.get("AUXÍLIOS")) + money(r.get("DIÁRIAS"))
    bruto = g["basica"] + g["pessoais"] + g["funcao"] + g["natalina"] + g["eventuais"] + g["abono"]
    return {"mes": mes, "bruto": round(bruto, 2), "abate_teto": round(g["abate"], 2),
            "bruto_apos_abate": round(bruto - g["abate"], 2), "liquido": round(g["liquido"], 2),
            "componentes": {"basica": round(g["basica"], 2), "gratificacoes": round(g["natalina"], 2), "funcao": round(g["funcao"], 2),
                            "eventuais": round(g["eventuais"], 2), "indenizatorias": round(g["ind"], 2),
                            "vantagens_pessoais": round(g["pessoais"], 2), "abono_permanencia": round(g["abono"], 2)},
            # campos legados (o build e a web leem estes nomes)
            "bruta": round(g["basica"], 2), "liquida": round(g["liquido"], 2), "indenizatorias": round(g["ind"], 2),
            "gratificacao_natalina": round(g["natalina"], 2), "ferias": 0.0, "eventuais": round(g["eventuais"], 2)}


# ---------------------------------------------------------------- casamento
def casa(o, full, base, fl, porg, org_ok):
    """devolve (registros da folha, criterio, confianca) ou (None, None, motivo)."""
    kf, kb, k3 = kfull(o["nome"]), kbase(o["nome"]), kfl(o["nome"])
    for nivel, cands in (("nome_completo", full.get(kf) or []), ("nome_sem_sufixo", base.get(kb) or [])):
        if not cands:
            continue
        sids = {c["sid"] for c in cands}
        if len(sids) == 1:
            bate = any(org_ok(c, o) for c in cands)
            return cands, nivel + ("+orgao" if bate else ""), "alta"
        no_org = [c for c in cands if org_ok(c, o)]
        sids2 = {c["sid"] for c in no_org}
        if len(sids2) == 1:
            return no_org, nivel + "+orgao", "alta"
        return None, None, ("homônimos na folha (%d servidores) sem desempate por órgão" % len(sids))
    # primeiro nome + último sobrenome, só aceito se único dentro do órgão e se o nome do grafo
    # couber, em ordem, dentro do nome da folha (impede "João Carlos Salles" casar com "João Lucas Silva Salles")
    alvo0 = kbase(o["nome"]).split()
    cands = [c for c in (fl.get(k3) or []) if subseq(alvo0, c["toks"]) and org_ok(c, o)] if k3 else []
    if len({c["sid"] for c in cands}) == 1:
        return cands, "primeiro_ultimo+orgao", "media"
    if not o["dept"] and k3:  # ocupante sem órgão no grafo (ex.: Vice-Presidente): exige unicidade na folha inteira
        todos = [c for c in (fl.get(k3) or []) if subseq(alvo0, c["toks"])]
        if len({c["sid"] for c in todos}) == 1:
            return todos, "primeiro_ultimo_unico", "media"
    fora = len(fl.get(k3) or [])
    # tokens do nome contidos em ordem no nome da folha, dentro do órgão do ocupante
    alvo = kbase(o["nome"]).split()
    pool_org = o["_pool"](o)
    if len(alvo) >= 2:
        pool = {}
        for c in pool_org:
            if subseq(alvo, c["toks"]):
                pool.setdefault(c["sid"], []).append(c)
        if len(pool) == 1:
            return list(pool.values())[0], "subsequencia_no_orgao", "media"
        if len(pool) > 1:
            return None, None, "vários servidores compatíveis no órgão (%d) sem desempate" % len(pool)
    if cands:
        return None, None, "homônimos no órgão sem desempate"
    if fora:
        return None, None, "só há homônimo por primeiro+último sobrenome fora do órgão (%d)" % fora
    return None, None, "ausente na folha"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mes")
    ap.add_argument("--debug", action="store_true")
    a = ap.parse_args()
    hoje = datetime.date.today()
    m = a.mes or (hoje.replace(day=1) - datetime.timedelta(days=45)).strftime("%Y%m")
    zpath = CACHE / f"{m}_Servidores_SIAPE.zip"

    N, dept, chain, occ = carrega_grafo()
    ix_org = indice_orgaos(dept)
    setores = collections.Counter(o["setor"] for o in occ)

    # ---------- alvos do SIAPE: Executivo + essenciais à Justiça (AGU/DPU estão no SIAPE)
    alvo = [o for o in occ if o["setor"] in ("executivo", "essenciais")]
    quer_keys, quer_firsts, quer_lasts = set(), set(), set()
    for o in alvo:
        quer_keys |= {kfull(o["nome"]), kbase(o["nome"]), kfl(o["nome"])}
        t = kbase(o["nome"]).split()
        if t:
            quer_firsts.add(t[0])
            if len(t[-1]) >= 5 and t[-1] not in SOBRENOMES_COMUNS:
                quer_lasts.add(t[-1])
    quer_keys.discard("")

    people, criterios, confs, fora_lista = {}, collections.Counter(), collections.Counter(), []
    antes = collections.Counter()
    depois = collections.Counter()
    total_setor = collections.Counter(o["setor"] for o in occ)
    mes_siape = None

    if not zpath.exists():
        print(f"remuneração: {zpath.name} ausente (etl/teto.py baixa); pulando o Executivo", file=sys.stderr)
    else:
        mes_siape = m
        # órgãos relevantes: códigos SIAFI cujo nó do grafo está na cadeia de algum ocupante
        cadeias = {o["pid"]: set(chain(o["dept"])) if o["dept"] else set() for o in alvo}
        nos_relevantes = set()
        for s in cadeias.values():
            nos_relevantes |= s
        # 1ª passada: precisa do mapa código→nó, que só sai lendo os nomes de órgão. Lê o Cadastro uma vez
        # com um conjunto de órgãos relevantes vazio e outra com ele preenchido seria caro; em vez disso,
        # mantém-se toda linha cujo primeiro nome interessa E cujo órgão casa com algum nó relevante,
        # resolvido a partir dos códigos vistos no próprio arquivo (pré-mapa pelos nomes de órgão).
        pre = {}
        zz = zipfile.ZipFile(zpath)
        cadn = [x for x in zz.namelist() if x.endswith("Cadastro.csv")][0]
        with zz.open(cadn) as f:
            r = csv.reader(io.TextIOWrapper(f, encoding="latin1"), delimiter=";")
            head = next(r)
            ixh = {h: i for i, h in enumerate(head)}
            for row in r:
                try:
                    for c, nm in ((row[ixh["COD_ORG_EXERCICIO"]], row[ixh["ORG_EXERCICIO"]]), (row[ixh["COD_ORGSUP_EXERCICIO"]], row[ixh["ORGSUP_EXERCICIO"]]),
                                  (row[ixh["COD_ORG_LOTACAO"]], row[ixh["ORG_LOTACAO"]]), (row[ixh["COD_ORGSUP_LOTACAO"]], row[ixh["ORGSUP_LOTACAO"]])):
                        pre.setdefault(c, nm)
                except IndexError:
                    continue
        org_node_pre = {c: casa_orgao(nm, ix_org, dept) for c, nm in pre.items()}
        orgs_relevantes = {c for c, nid in org_node_pre.items() if nid and (nid in nos_relevantes or bool(set(chain(nid)) & nos_relevantes))}

        nos_na_folha = {nid for nid in org_node_pre.values() if nid}
        z, full, base, fl, porg, org_node, org_nome, total_folha = le_siapé(zpath, quer_keys, quer_firsts, quer_lasts, orgs_relevantes, ix_org, dept)
        org_node = {**org_node_pre, **{k: v for k, v in org_node.items() if v}}

        def proprio(o):
            """órgão mais específico da cadeia do ocupante que tem folha própria no SIAPE."""
            return next((nid for nid in chain(o["dept"] or "") if nid in nos_na_folha), None)

        def org_ok(c, o):
            """o órgão da folha bate com o do ocupante? aceita o próprio órgão e os subordinados a ele;
            um ancestral (o ministério) só vale quando a unidade do ocupante não tem folha própria."""
            if not o["dept"]:
                return False
            base_no = proprio(o)
            for cod in c["cods"]:
                nid = org_node.get(cod)
                if not nid:
                    continue
                if nid == o["dept"] or o["dept"] in set(chain(nid)):
                    return True
                if base_no and nid == base_no:
                    return True
            return False

        # baseline (regra antiga: nome completo idêntico e um único servidor)
        for o in alvo:
            cands = full.get(kfull(o["nome"])) or []
            if len({c["sid"] for c in cands}) == 1:
                antes[o["setor"]] += 1

        pool_cache = {}

        def pool_do_orgao(o):
            """linhas da folha do órgão do ocupante: o próprio órgão e os subordinados quando ele tem folha
            própria; senão, só as linhas do ministério/órgão ancestral mais próximo que tem folha."""
            if not o["dept"]:
                return []
            if o["dept"] in pool_cache:
                return pool_cache[o["dept"]]
            proprio_no = o["dept"] if o["dept"] in nos_na_folha else None
            base_no = proprio_no or proprio(o)
            pool, vistos = [], set()
            for cod, rows in porg.items():
                nid = org_node.get(cod)
                if not nid or not base_no:
                    continue
                if nid == base_no or (proprio_no and base_no in set(chain(nid))):
                    for rec in rows:
                        if id(rec) not in vistos:
                            vistos.add(id(rec))
                            pool.append(rec)
            pool_cache[o["dept"]] = pool
            return pool

        achados = []
        for o in alvo:
            o["_pool"] = pool_do_orgao
            recs, crit, conf = casa(o, full, base, fl, porg, org_ok)
            if recs:
                achados.append((o, recs, crit, conf))
            else:
                d = dept.get(o["dept"] or "", {})
                motivo = conf
                if d.get("subtype") in FORA_DO_SIAPE:
                    motivo = "órgão fora do SIAPE (%s com folha própria)" % d.get("subtype", "").replace("_", " ")
                elif o["dept"] and not (set(chain(o["dept"])) & nos_na_folha):
                    motivo = "órgão não consta do arquivo do SIAPE (folha própria ou fora do Executivo civil)"
                elif o["dept"] and o["dept"] not in nos_na_folha and d.get("subtype") in ENTIDADES_COM_FOLHA:
                    motivo = "a entidade não aparece como órgão na folha do SIAPE (folha própria)"
                fora_lista.append({"id": o["pid"], "nome": o["nome"], "cargo": o["node_name"], "setor": o["setor"], "motivo": motivo})

        sids = {c["sid"] for _, recs, _, _ in achados for c in recs}
        val = le_remuneracao_siape(z, sids)
        for o, recs, crit, conf in achados:
            ag = {"basica": 0.0, "natalina": 0.0, "ferias": 0.0, "eventuais": 0.0, "abate": 0.0, "ind": 0.0, "liquido": 0.0}
            for sid in {c["sid"] for c in recs}:
                v = val.get(sid)
                if not v:
                    continue
                for k in ag:
                    ag[k] += v[k]
            if not any(ag.values()):
                fora_lista.append({"id": o["pid"], "nome": o["nome"], "cargo": o["node_name"], "setor": o["setor"],
                                   "motivo": "no cadastro do SIAPE mas sem linha de remuneração no mês"})
                continue
            c0 = recs[0]
            bruto = ag["basica"] + ag["natalina"] + ag["ferias"] + ag["eventuais"]
            people[o["pid"]] = {
                "mes": m, "bruto": round(bruto, 2), "abate_teto": round(ag["abate"], 2),
                "bruto_apos_abate": round(bruto - ag["abate"], 2), "liquido": round(ag["liquido"], 2),
                "componentes": {"basica": round(ag["basica"], 2), "gratificacoes": round(ag["natalina"], 2), "funcao": None,
                                "eventuais": round(ag["eventuais"] + ag["ferias"], 2), "indenizatorias": round(ag["ind"], 2)},
                "orgao": c0["orgao"], "orgao_superior": c0["orgsup"], "cargo_na_folha": c0["cargo"], "funcao_na_folha": c0["funcao"],
                "vinculo": c0["vinculo"], "criterio": crit, "confianca": conf, "nome_na_folha": c0["nome"],
                "fonte": FONTE_SIAPE, "fonte_url": SIAPE_URL + c0["sid"],
                "position": o["node"], "position_name": o["node_name"],
                # campos legados
                "bruta": round(ag["basica"], 2), "liquida": round(ag["liquido"], 2), "indenizatorias": round(ag["ind"], 2),
                "gratificacao_natalina": round(ag["natalina"], 2), "ferias": round(ag["ferias"], 2), "eventuais": round(ag["eventuais"], 2),
                "cargo": c0["cargo"], "funcao": c0["funcao"]}
            criterios[crit] += 1
            confs[conf] += 1
            depois[o["setor"]] += 1
        if a.debug:
            print(f"SIAPE: {total_folha} linhas no cadastro; {len(orgs_relevantes)} órgãos relevantes", file=sys.stderr)

    # ---------- Senado: a folha do Senado é nominal e traz os senadores
    sen_rows, mes_sen = folha_senado(hoje)
    sen_pid = set()
    if sen_rows:
        idx = collections.defaultdict(list)
        for r in sen_rows:
            idx[kfull(r["NOME"])].append(r)
        idxb = collections.defaultdict(list)
        for r in sen_rows:
            idxb[kbase(r["NOME"])].append(r)
        # pool dos parlamentares: linhas cuja remuneração básica é exatamente o subsídio
        pool_sub = collections.defaultdict(list)
        for r in sen_rows:
            if abs(money(r.get("REMUNERAÇÃO BÁSICA")) - SUBSIDIO) < 0.01:
                pool_sub[kfull(r["NOME"])].append(r)
        legis = [o for o in occ if o["setor"] == "legislativo"]
        senadores = [o for o in legis if o["node"] in ("br-senador", "br-presidente-do-senado-federal")]
        for o in senadores:
            rows, crit, conf = None, None, None
            for nivel, ii in (("nome_completo", idx), ("nome_sem_sufixo", idxb)):
                k = kfull(o["nome"]) if nivel == "nome_completo" else kbase(o["nome"])
                c = ii.get(k) or []
                if c:
                    rows, crit, conf = c, nivel, "alta"
                    break
            if rows is None:
                alvo_t = kbase(o["nome"]).split()
                hits = {k: v for k, v in pool_sub.items() if subseq(alvo_t, k.split())}
                if len(hits) == 1:
                    nome_folha = list(hits)[0]
                    rows, crit, conf = (idx.get(nome_folha) or list(hits.values())[0]), "subsequencia_subsidio", "media"
            if rows is None:
                fora_lista.append({"id": o["pid"], "nome": o["nome"], "cargo": o["node_name"], "setor": "legislativo",
                                   "motivo": "ausente na folha do Senado no mês (licença/afastamento ou nome divergente)"})
                continue
            rec = rec_senado(rows, mes_sen)
            rec.update({"orgao": "Senado Federal", "orgao_superior": "Senado Federal", "cargo_na_folha": "Senador da República",
                        "funcao_na_folha": None, "vinculo": "Parlamentar", "criterio": crit, "confianca": conf,
                        "nome_na_folha": (rows[0]["NOME"] or "").title(), "fonte": FONTE_SENADO,
                        "fonte_url": f"{SEN_API}/servidores/remuneracoes/{mes_sen[:4]}/{int(mes_sen[4:])}/csv",
                        "cargo": "Senador da República", "funcao": "", "position": o["node"], "position_name": o["node_name"]})
            people[o["pid"]] = rec
            criterios[crit] += 1
            confs[conf] += 1
            depois["legislativo"] += 1
            sen_pid.add(o["pid"])
        vistos_legis = sen_pid | {o["pid"] for o in senadores}
        for o in legis:
            if o["pid"] in vistos_legis:
                continue
            if o["node"] in ("br-deputado-federal", "br-presidente-da-camara-dos-deputados"):
                continue  # contados em resumo.parlamentares; a Câmara não publica folha nominal
            fora_lista.append({"id": o["pid"], "nome": o["nome"], "cargo": o["node_name"], "setor": "legislativo", "motivo": "sem fonte nominal"})

    deputados = sum(1 for o in occ if o["setor"] == "legislativo" and o["node"] in ("br-deputado-federal", "br-presidente-da-camara-dos-deputados"))
    n_sen = sum(1 for o in occ if o["node"] in ("br-senador", "br-presidente-do-senado-federal"))
    parlamentares_nota = (
        f"Senado: folha mensal nominal do Senado Federal cobre {depois['legislativo']} de {n_sen} senadores "
        f"({mes_sen or 'sem mês'}). Câmara: sem fonte nominal — o relatório consolidado da Câmara é pseudonimizado "
        f"('Deputado 11530') e a consulta nominal só cobre servidores; o subsídio do cargo vem de data/subsidios.yaml "
        f"({deputados} deputados sem registro individual).")

    setor_stat = {}
    for s in ("executivo", "essenciais", "legislativo", "judiciario"):
        if not total_setor.get(s):
            continue
        setor_stat[s] = {"ocupantes": total_setor[s], "antes": antes.get(s, 0), "depois": depois.get(s, 0),
                         "pct_antes": round(100 * antes.get(s, 0) / total_setor[s], 1),
                         "pct_depois": round(100 * depois.get(s, 0) / total_setor[s], 1)}
    motivos = collections.Counter(re.sub(r"\(\d+[^)]*\)", "(...)", f["motivo"]) for f in fora_lista)

    data = {
        "generated_at": hoje.isoformat(), "mes": mes_siape or m, "mes_senado": mes_sen,
        "fonte": FONTE_SIAPE, "fonte_senado": FONTE_SENADO,
        "resumo": {
            "ocupantes_no_grafo": len(occ),
            "com_remuneracao": len(people),
            "por_setor": setor_stat,
            "por_criterio": dict(criterios.most_common()),
            "por_confianca": dict(confs.most_common()),
            "sem_remuneracao": {"total": len(fora_lista), "por_motivo": dict(motivos.most_common())},
            "parlamentares": parlamentares_nota,
            "judiciario": ("sem fonte nominal aqui: o SIAPE não cobre o Judiciário nem o Ministério Público — cada tribunal "
                           "e cada ramo do MPU publica a própria folha; o subsídio do cargo vem de data/subsidios.yaml"),
            "criterios": {
                "nome_completo": "nome normalizado (sem acentos e preposições) idêntico e um único servidor na folha",
                "nome_sem_sufixo": "idem, ignorando Filho/Júnior/Neto",
                "primeiro_ultimo_unico": "primeiro nome + último sobrenome, único na folha inteira; só para ocupante sem órgão no grafo",
                "primeiro_ultimo+orgao": "primeiro nome + último sobrenome, único dentro do órgão do ocupante",
                "subsequencia_no_orgao": "tokens do nome do ocupante contidos em ordem no nome da folha, único no órgão",
                "subsequencia_subsidio": "idem, dentro das linhas da folha do Senado cuja básica é o subsídio",
                "+orgao": "o órgão do ocupante no grafo bate com o órgão de exercício/lotação na folha"}},
        "people": people,
        "nao_encontrados": sorted(fora_lista, key=lambda f: (f["setor"], f["nome"])),
        "nota": ("Remuneração do mês publicada pelo Portal da Transparência (Executivo, SIAPE) e pelo Senado Federal; a folha do "
                 "SIAPE sai com cerca de dois meses de atraso. 'bruto' soma remuneração básica, gratificação natalina, férias e "
                 "eventuais; 'liquido' é a remuneração após deduções obrigatórias. Verbas indenizatórias não são salário e ficam "
                 "fora do teto por lei, por isso entram em componentes.indenizatorias e não no bruto. O SIAPE não discrimina, no "
                 "download mensal, quanto do bruto é função ou gratificação (componentes.funcao fica nulo); a folha do Senado "
                 "discrimina. Casamentos ambíguos não são gravados: veja criterio e confianca em cada registro."),
    }
    (ROOT / "data" / "generated" / "remuneracao.yaml").write_text(
        "# GERADO por etl/remuneracao.py. Não edite à mão.\n" + yaml.dump(data, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")

    print(f"remuneração {m}: {len(people)} ocupantes com folha (antes {sum(antes.values())}) de {len(occ)} no grafo")
    for s, v in setor_stat.items():
        print(f"   {s:12} {v['depois']:4}/{v['ocupantes']:<4} ({v['pct_depois']}%)  antes {v['antes']} ({v['pct_antes']}%)")
    print("   critérios:", dict(criterios.most_common()))
    print("   confiança:", dict(confs.most_common()))
    print("   sem remuneração:", len(fora_lista), dict(motivos.most_common(6)))
    print("  ", parlamentares_nota)


if __name__ == "__main__":
    main()
