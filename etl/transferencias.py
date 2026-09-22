#!/usr/bin/env python3
"""Transferências da União a estados e municípios → data/generated/transferencias.yaml

Fonte escolhida: os CSVs mensais "Transferências de Recursos" do Portal da Transparência
(https://portaldatransparencia.gov.br/download-de-dados/transferencias → arquivos
AAAAMM_Transferencias.zip em dadosabertos-download.cgu.gov.br). Cada linha traz órgão
SIAFI, unidade gestora, UF, município, tipo de transferência, modalidade de aplicação e
valor transferido no mês.

Por que esta fonte e não a API: /api-de-dados/transferencias exige uma chamada por
município × mês (5.570 × 12 ≈ 67 mil chamadas por exercício, paginadas) e o retorno não
quebra por órgão; o CSV mensal resolve órgão × UF × município em 12 arquivos por ano.

O que entra: linhas cuja modalidade de aplicação é transferência a Estados/DF (30, 31,
32, 35, 36) ou a Municípios (40, 41, 42, 45, 46); nas transferências constitucionais a
modalidade vem "Sem informação" e usa-se o tipo de favorecido (Administração Pública
Estadual ou do Distrito Federal / Municipal). Ficam de fora repasses a entidades privadas,
ao exterior e a organizações multigovernamentais.

Atenção: nas transferências constitucionais e royalties (FPM, FPE, cota-parte de impostos)
o Portal publica "Código Órgão SIAFI" = -1 (Sem informação). Elas entram em `por_uf` e nos
totais, mas não podem ser atribuídas a um órgão — `por_orgao` cobre as transferências
legais, voluntárias e específicas.

Uso: .venv/bin/python etl/transferencias.py [--amostra N]
     --amostra N processa só os N meses mais recentes de cada ano e grava em
     build/cache-transferencias/transferencias-amostra.yaml, sem tocar em data/generated/.
"""
import csv, io, json, re, sys, time, zipfile, pathlib, datetime, unicodedata, collections, urllib.request
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / "build" / "cache-transferencias"; CACHE.mkdir(parents=True, exist_ok=True)
OUT = ROOT / "data" / "generated" / "transferencias.yaml"
BASE = "https://dadosabertos-download.cgu.gov.br/PortalDaTransparencia/saida/transferencias"
FONTE = "Portal da Transparência — Transferências de Recursos, CSV mensal AAAAMM_Transferencias.zip"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh) atlas-da-republica/0.1"}
TODAY = datetime.date.today(); Y = TODAY.year
MOD_ESTADO = {"30", "31", "32", "35", "36"}
MOD_MUNICIPIO = {"40", "41", "42", "45", "46"}
FAV_ESTADO = "administracao publica estadual ou do distrito federal"
FAV_MUNICIPIO = "administracao publica municipal"
TOP_UFS = 8; TOP_MUNS = 12
THROTTLE = 20.0   # segundos entre downloads (o WAF da CGU bloqueia rajadas com captcha)
UF_COD = {"11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO", "21": "MA", "22": "PI",
          "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL", "28": "SE", "29": "BA", "31": "MG", "32": "ES",
          "33": "RJ", "35": "SP", "41": "PR", "42": "SC", "43": "RS", "50": "MS", "51": "MT", "52": "GO", "53": "DF"}


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s)).strip()


def money(s):
    s = (s or "").strip()
    if not s: return 0.0
    try: return float(s.replace(".", "").replace(",", "."))
    except ValueError: return 0.0


CONECTIVOS = {"de", "da", "do", "das", "dos", "e", "a", "o", "as", "os", "em", "para"}
def chave(s):
    """Nome sem conectivos: casa "Direitos Humanos e Cidadania" (SIAFI) com
    "Direitos Humanos e da Cidadania" (grafo)."""
    return " ".join(p for p in norm(s).split() if p not in CONECTIVOS)


def variantes(nome):
    """Formas do nome do órgão no CSV que valem tentar contra o grafo."""
    limpo = re.sub(r" - Unidades com v[íi]nculo direto$", "", nome or "")
    return [v for v in (nome, limpo, limpo.split(" - ")[0]) if v and len(v) > 4]


MINUSCULAS = {"de", "do", "da", "dos", "das", "e", "d"}
def titulo(s):
    """Os CSVs trazem o município em caixa alta e sem acento ("CRUZEIRO DO SUL")."""
    ps = [p.capitalize() for p in (s or "").strip().split()]
    return " ".join(p if i == 0 or p.lower() not in MINUSCULAS else p.lower() for i, p in enumerate(ps))


def fetch(ym, max_age_h=24 * 7):
    name = f"{ym}_Transferencias.zip"; p = CACHE / name
    if p.exists() and p.stat().st_size > 1000:
        age = (datetime.datetime.now() - datetime.datetime.fromtimestamp(p.stat().st_mtime)).total_seconds()
        if int(ym[:4]) < Y or age < max_age_h * 3600: return p
    url = f"{BASE}/{name}"
    for i in range(5):
        try:
            print("GET", url, file=sys.stderr)
            data = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=900).read()
            if len(data) < 1000: raise IOError(f"arquivo curto ({len(data)} bytes)")
            p.write_bytes(data); time.sleep(THROTTLE); return p
        except Exception as e:
            print(f"  falhou ({e}); tentativa {i+1}/5", file=sys.stderr); time.sleep(30 * (i + 1))
    return None


def meses(ano):
    ultimo = 12 if ano < Y else TODAY.month
    return [f"{ano}{m:02d}" for m in range(1, ultimo + 1)]


def ler(path, acc):
    z = zipfile.ZipFile(path); nome = [n for n in z.namelist() if n.lower().endswith(".csv")][0]
    linhas = usadas = 0
    with z.open(nome) as f:
        rd = csv.DictReader(io.TextIOWrapper(f, encoding="latin1", newline=""), delimiter=";")
        campos = {norm(c): c for c in (rd.fieldnames or [])}
        def col(*alts):
            for a in alts:
                if norm(a) in campos: return campos[norm(a)]
            raise KeyError(alts[0])
        c_tipo = col("TIPO TRANSFERÊNCIA"); c_fav = col("TIPO FAVORECIDO"); c_uf = col("UF"); c_mun = col("NOME MUNICÍPIO")
        c_org = col("CÓDIGO ÓRGÃO SIAFI"); c_orgn = col("NOME ÓRGÃO"); c_mod = col("CÓDIGO MODALIDADE APLICAÇÃO DESPESA")
        c_val = col("VALOR TRANSFERIDO")
        for r in rd:
            linhas += 1
            mod = (r[c_mod] or "").strip(); fav = norm(r[c_fav])
            if mod in MOD_ESTADO: destino = "estado"
            elif mod in MOD_MUNICIPIO: destino = "municipio"
            elif fav == FAV_ESTADO: destino = "estado"
            elif fav == FAV_MUNICIPIO: destino = "municipio"
            else: continue
            uf = (r[c_uf] or "").strip().upper()
            if len(uf) != 2: continue
            v = money(r[c_val])
            if not v: continue
            usadas += 1
            mun = titulo(r[c_mun])
            tipo = (r[c_tipo] or "").strip()
            org = (r[c_org] or "").strip()
            if org and org != "-1": acc["nome_org"].setdefault(org, (r[c_orgn] or "").strip())
            acc["uf_tipo"][(uf, tipo)] += v
            acc["uf_destino"][(uf, destino)] += v
            if mun: acc["mun"][(mun, uf)] += v
            if org and org != "-1":
                acc["org"][org] += v
                acc["org_uf"][(org, uf)] += v
                if mun: acc["org_mun"][(org, mun, uf)] += v
            else:
                acc["sem_orgao"][tipo] += v
    return linhas, usadas


def coletar(ano, limite=None):
    acc = {"org": collections.defaultdict(float), "org_uf": collections.defaultdict(float),
           "org_mun": collections.defaultdict(float), "uf_tipo": collections.defaultdict(float),
           "uf_destino": collections.defaultdict(float), "mun": collections.defaultdict(float),
           "sem_orgao": collections.defaultdict(float), "nome_org": {}}
    alvo = meses(ano)
    if limite: alvo = alvo[-limite:]
    lidos, faltando = [], []
    for ym in alvo:
        p = fetch(ym)
        if not p:
            faltando.append(ym); continue
        try:
            n, u = ler(p, acc); lidos.append(ym)
            print(f"  {ym}: {n:,} linhas, {u:,} para entes federados", file=sys.stderr)
        except Exception as e:
            print(f"  {ym}: erro ao ler ({e})", file=sys.stderr); faltando.append(ym)
    return acc, lidos, faltando


def populacao_uf():
    """IBGE/SIDRA 6579 (mesma fonte de etl/arrecadacao.py), nível 3 = unidade da federação."""
    try:
        url = "https://apisidra.ibge.gov.br/values/t/6579/n3/all/v/9324/p/last%201?formato=json"
        d = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180))
        out = {}
        for r in d[1:]:
            sigla = UF_COD.get(str(r.get("D1C", ""))[:2])
            if sigla and r.get("V") not in (None, "...", "-"): out[sigla] = int(float(r["V"]))
        return out, d[1].get("D3N") if len(d) > 1 else None
    except Exception as e:
        print("população por UF falhou:", e, file=sys.stderr); return {}, None


def mapa_orgaos():
    """código SIAFI do órgão → node_id. Base: data/generated/orcamento.yaml (mesmo casamento
    de etl/orcamento.py); reserva: nome normalizado do órgão contra nome/aliases do nó."""
    nodes = json.load(open(ROOT / "build" / "graph.br.json", encoding="utf-8"))["nodes"]
    por_cod = {}
    orc = ROOT / "data" / "generated" / "orcamento.yaml"
    if orc.exists():
        d = (yaml.safe_load(open(orc, encoding="utf-8")) or {}).get("nodes") or {}
        for nid, anos in d.items():
            for _, v in sorted(anos.items(), reverse=True):
                if v.get("codigo"): por_cod.setdefault(str(v["codigo"]), nid); break
    por_nome = {}
    for n in nodes.values():
        if n["type"] in ("dept_head", "commission"): continue
        for a in [n["name"]] + list(n.get("aliases") or []):
            for k in (norm(a), chave(a)):
                if len(k) > 4: por_nome.setdefault(k, n["id"])
    return nodes, por_cod, por_nome


def main():
    amostra = None
    if "--amostra" in sys.argv:
        i = sys.argv.index("--amostra")
        amostra = int(sys.argv[i + 1]) if len(sys.argv) > i + 1 else 2
    anos = [Y, Y - 1]
    dados = {}
    for ano in anos:
        print(f"exercício {ano}", file=sys.stderr)
        acc, lidos, faltando = coletar(ano, amostra)
        if not lidos:
            print(f"AVISO: nenhum mês de {ano} pôde ser baixado/lido — nada será gravado.", file=sys.stderr)
            return 1
        if faltando and not amostra and len(faltando) > 2:
            print(f"AVISO: {len(faltando)} meses de {ano} faltando ({faltando}) — nada será gravado.", file=sys.stderr)
            return 1
        dados[ano] = (acc, lidos, faltando)

    nodes, por_cod, por_nome = mapa_orgaos()
    nomes_org = {}
    for ano in anos: nomes_org.update(dados[ano][0]["nome_org"])

    # código SIAFI → node. Exato; senão pelo nome; senão pelo órgão superior (2 dígitos + 000).
    cod_node = {}; via = collections.Counter()
    for cod, nome in nomes_org.items():
        nid = por_cod.get(cod)
        if nid: cod_node[cod] = nid; via["codigo"] += 1; continue
        nid = next((por_nome.get(norm(v)) or por_nome.get(chave(v)) for v in variantes(nome)
                    if por_nome.get(norm(v)) or por_nome.get(chave(v))), None)
        if nid: cod_node[cod] = nid; via["nome"] += 1; continue
        sup = cod[:2] + "000" if len(cod) == 5 else None
        nid = por_cod.get(sup) if sup else None
        if nid: cod_node[cod] = nid; via["orgao_superior"] += 1

    por_orgao = {}
    for ano in anos:
        acc = dados[ano][0]
        tot = collections.defaultdict(float); ufs = collections.defaultdict(float); muns = collections.defaultdict(float)
        for cod, v in acc["org"].items():
            nid = cod_node.get(cod)
            if nid: tot[nid] += v
        for (cod, uf), v in acc["org_uf"].items():
            nid = cod_node.get(cod)
            if nid: ufs[(nid, uf)] += v
        for (cod, mun, uf), v in acc["org_mun"].items():
            nid = cod_node.get(cod)
            if nid: muns[(nid, mun, uf)] += v
        for nid, v in tot.items():
            if v <= 0: continue
            tu = sorted(((u, w) for (n2, u), w in ufs.items() if n2 == nid), key=lambda kv: -kv[1])[:TOP_UFS]
            tm = sorted(((m, u, w) for (n2, m, u), w in muns.items() if n2 == nid), key=lambda kv: -kv[2])[:TOP_MUNS]
            e = por_orgao.setdefault(nid, {})
            e[str(ano)] = {"total": round(v, 2),
                           "municipios_atendidos": sum(1 for (n2, _, _) in muns if n2 == nid),
                           "top_ufs": [{"uf": u, "valor": round(w, 2)} for u, w in tu],
                           "top_municipios": [{"municipio": m, "uf": u, "valor": round(w, 2)} for m, u, w in tm]}

    pop, pop_ano = populacao_uf()
    por_uf = {}
    for ano in anos:
        acc = dados[ano][0]
        for (uf, tipo), v in acc["uf_tipo"].items():
            e = por_uf.setdefault(uf, {}).setdefault(str(ano), {"total": 0.0, "por_tipo": {}, "a_estado": 0.0, "a_municipios": 0.0})
            e["total"] += v; e["por_tipo"][tipo] = round(e["por_tipo"].get(tipo, 0.0) + v, 2)
        for (uf, destino), v in acc["uf_destino"].items():
            e = por_uf.get(uf, {}).get(str(ano))
            if e: e["a_estado" if destino == "estado" else "a_municipios"] += v
    for uf, anos_d in por_uf.items():
        for ano, e in anos_d.items():
            e["total"] = round(e["total"], 2); e["a_estado"] = round(e["a_estado"], 2); e["a_municipios"] = round(e["a_municipios"], 2)
            if pop.get(uf):
                e["populacao"] = pop[uf]; e["por_habitante"] = round(e["total"] / pop[uf], 2)
    por_uf = dict(sorted(por_uf.items(), key=lambda kv: -kv[1].get(str(anos[0]), {}).get("total", 0)))

    acc0 = dados[anos[0]][0]
    top_mun = sorted(acc0["mun"].items(), key=lambda kv: -kv[1])[:20]
    top_uf_hab = sorted(((uf, e[str(anos[0])]["por_habitante"]) for uf, e in por_uf.items()
                         if str(anos[0]) in e and "por_habitante" in e[str(anos[0])]), key=lambda kv: -kv[1])[:10]
    sem_no = sorted(((c, v) for c, v in acc0["org"].items() if c not in cod_node), key=lambda kv: -kv[1])[:30]
    tot_ano = {str(ano): {"total": round(sum(dados[ano][0]["uf_tipo"].values()), 2),
                          "com_orgao": round(sum(dados[ano][0]["org"].values()), 2),
                          "sem_orgao": {k: round(v, 2) for k, v in sorted(dados[ano][0]["sem_orgao"].items(), key=lambda kv: -kv[1])},
                          "meses": dados[ano][1], "meses_faltando": dados[ano][2]} for ano in anos}

    resumo = {"orgaos_casados": len(set(cod_node.values())), "codigos_siafi_no_csv": len(nomes_org),
              "codigos_casados": len(cod_node), "casamento_por": dict(via),
              "codigos_sem_no": [{"codigo": c, "nome": nomes_org.get(c, ""), "valor": round(v, 2)} for c, v in sem_no],
              "total_por_ano": tot_ano, "populacao_ibge": pop_ano,
              "maiores_municipios": [{"municipio": m, "uf": u, "valor": round(v, 2)} for (m, u), v in top_mun],
              "maiores_por_habitante": [{"uf": u, "por_habitante": v} for u, v in top_uf_hab],
              "amostra": bool(amostra),
              "criterio": "modalidade de aplicação 30/31/32/35/36 (Estados e DF) e 40/41/42/45/46 (Municípios); "
                          "nas constitucionais, sem modalidade, usa-se o tipo de favorecido"}

    out = {"generated_at": TODAY.isoformat(), "fonte": FONTE,
           "fonte_url": "https://portaldatransparencia.gov.br/download-de-dados/transferencias",
           "anos": anos, "por_orgao": dict(sorted(por_orgao.items())), "por_uf": por_uf, "resumo": resumo}

    txt = "# GERADO por etl/transferencias.py. Não edite à mão.\n" + yaml.dump(out, allow_unicode=True, sort_keys=False, width=120)
    destino = (CACHE / "transferencias-amostra.yaml") if amostra else OUT
    destino.write_text(txt, encoding="utf-8")
    print(f"transferências: {len(por_orgao)} órgãos casados de {len(nomes_org)} códigos SIAFI no CSV ({dict(via)})")
    for ano in anos:
        t = tot_ano[str(ano)]
        print(f"  {ano}: R$ {t['total']/1e9:,.1f} bi a estados e municípios em {len(t['meses'])} meses; "
              f"R$ {t['com_orgao']/1e9:,.1f} bi com órgão identificado" + (f" (faltam {t['meses_faltando']})" if t["meses_faltando"] else ""))
    maiores = sorted(por_orgao.items(), key=lambda kv: -kv[1].get(str(anos[0]), {}).get("total", 0))[:6]
    for nid, e in maiores:
        print(f"  {nodes.get(nid, {}).get('name', nid)[:46]:46} R$ {e[str(anos[0])]['total']/1e9:,.1f} bi")
    for uf, v in list(por_uf.items())[:5]:
        d = v.get(str(anos[0]), {})
        print(f"  {uf}: R$ {d.get('total', 0)/1e9:,.1f} bi" + (f" · R$ {d['por_habitante']:,.0f}/hab" if "por_habitante" in d else ""))
    print("gravado em", destino)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"AVISO: etl/transferencias.py falhou ({e}); {OUT} não foi alterado.", file=sys.stderr)
        sys.exit(0)
