#!/usr/bin/env python3
"""Orçamento por programa (e ação) de cada órgão → data/generated/programas.yaml

Fonte escolhida: os CSVs mensais "Despesas - Execução" do Portal da Transparência
(https://portaldatransparencia.gov.br/download-de-dados/despesas-execucao → arquivos
AAAAMM_Despesas.zip em dadosabertos-download.cgu.gov.br). Cada linha já vem agregada por
Órgão Superior × Órgão Subordinado × Unidade Orçamentária × Função × Subfunção ×
Programa Orçamentário × Ação × elemento, com Empenhado, Liquidado e Pago do mês.

Por que esta fonte e não as outras:
  (a) API do Portal da Transparência: não serve. /api-de-dados/despesas/por-orgao devolve
      só o total do órgão, sem programa; /api-de-dados/despesas/por-funcional-programatica
      aceita apenas funcao/subfuncao/programa/acao e NÃO aceita órgão (verificado no
      /v3/api-docs). Não existe endpoint que cruze órgão × programa.
  (b) CSVs anuais: o Portal não publica "{ano}_Despesas.zip" (404/403); publica um arquivo
      por mês. Somar os meses do exercício dá o acumulado do ano — é o que fazemos.
  (c) SIOP: traz o PLOA (dotação), não a execução, e a consulta pública exige sessão.

Os valores são de execução (empenhado/liquidado/pago), não de dotação. O mesmo órgão pode
aparecer duas vezes no grafo — como órgão superior (agregando as vinculadas, escopo
"órgão superior") e como órgão isolado —, seguindo o mesmo critério de etl/orcamento.py.

Uso: .venv/bin/python etl/programas.py [--amostra N]
     --amostra N processa só os N meses mais recentes de cada ano e grava em
     build/cache-programas/programas-amostra.yaml, sem tocar em data/generated/.
"""
import csv, io, json, re, sys, time, zipfile, pathlib, datetime, unicodedata, collections, urllib.request
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / "build" / "cache-programas"; CACHE.mkdir(parents=True, exist_ok=True)
OUT = ROOT / "data" / "generated" / "programas.yaml"
BASE = "https://dadosabertos-download.cgu.gov.br/PortalDaTransparencia/saida/despesas-execucao"
FONTE = "Portal da Transparência — Despesas (Execução), CSV mensal AAAAMM_Despesas.zip"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh) atlas-da-republica/0.1"}
TODAY = datetime.date.today(); Y = TODAY.year
TOP_PROGRAMAS = 12      # programas por órgão
TOP_ACOES = 4           # ações por programa
THROTTLE = 20.0         # segundos entre downloads (o WAF da CGU bloqueia rajadas com captcha)


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s)).strip()


CONECTIVOS = {"de", "da", "do", "das", "dos", "e", "a", "o", "as", "os", "em", "para"}
def chave(s):
    """Nome sem conectivos: casa "Direitos Humanos e Cidadania" (SIAFI) com
    "Direitos Humanos e da Cidadania" (grafo)."""
    return " ".join(p for p in norm(s).split() if p not in CONECTIVOS)


def variantes(nome):
    """Formas do nome do órgão no CSV que valem tentar contra o grafo."""
    limpo = re.sub(r" - Unidades com v[íi]nculo direto$", "", nome or "")
    saidas = [nome, limpo, limpo.split(" - ")[0]]   # "Banco Central do Brasil - Orçamento Fiscal..." → "Banco Central do Brasil"
    return [v for v in saidas if v and len(v) > 4]


def money(s):
    s = (s or "").strip()
    if not s: return 0.0
    try: return float(s.replace(".", "").replace(",", "."))
    except ValueError: return 0.0


def fetch(ym, max_age_h=24 * 7):
    """Baixa AAAAMM_Despesas.zip com cache em build/cache-programas/, throttle e retries."""
    name = f"{ym}_Despesas.zip"; p = CACHE / name
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
    """Meses possíveis do exercício (não vai além do mês corrente no ano corrente)."""
    ultimo = 12 if ano < Y else TODAY.month
    return [f"{ano}{m:02d}" for m in range(1, ultimo + 1)]


def ler(path, acc):
    """Agrega um mês em acc (dicionários compartilhados entre meses)."""
    z = zipfile.ZipFile(path); nome = [n for n in z.namelist() if n.lower().endswith(".csv")][0]
    linhas = 0
    with z.open(nome) as f:
        rd = csv.DictReader(io.TextIOWrapper(f, encoding="latin1", newline=""), delimiter=";")
        campos = {norm(c): c for c in (rd.fieldnames or [])}
        def col(*alts):
            for a in alts:
                if norm(a) in campos: return campos[norm(a)]
            raise KeyError(alts[0])
        c_sup, c_sup_n = col("Código Órgão Superior"), col("Nome Órgão Superior")
        c_sub, c_sub_n = col("Código Órgão Subordinado"), col("Nome Órgão Subordinado")
        c_pro, c_pro_n = col("Código Programa Orçamentário"), col("Nome Programa Orçamentário")
        c_aca, c_aca_n = col("Código Ação"), col("Nome Ação")
        c_e = col("Valor Empenhado (R$)", "Valor Empenhado"); c_l = col("Valor Liquidado (R$)", "Valor Liquidado"); c_p = col("Valor Pago (R$)", "Valor Pago")
        for r in rd:
            linhas += 1
            sub = (r[c_sub] or "").strip(); sup = (r[c_sup] or "").strip()
            pro = (r[c_pro] or "").strip() or "SI"; aca = (r[c_aca] or "").strip() or "SI"
            e, l, pg = money(r[c_e]), money(r[c_l]), money(r[c_p])
            if not (e or l or pg): continue
            acc["sup_de"][sub] = sup
            acc["nome_org"].setdefault(sub, (r[c_sub_n] or "").strip())
            acc["nome_org"].setdefault(sup, (r[c_sup_n] or "").strip())
            acc["nome_pro"].setdefault(pro, (r[c_pro_n] or "").strip())
            acc["nome_aca"].setdefault(aca, (r[c_aca_n] or "").strip())
            v = acc["prog"][(sub, pro)]; v[0] += e; v[1] += l; v[2] += pg
            acc["acao"][(sub, pro, aca)] += pg
    return linhas


def coletar(ano, limite=None):
    """Devolve (acc, meses_lidos, meses_faltando) do exercício."""
    acc = {"prog": collections.defaultdict(lambda: [0.0, 0.0, 0.0]), "acao": collections.defaultdict(float),
           "sup_de": {}, "nome_org": {}, "nome_pro": {}, "nome_aca": {}}
    alvo = meses(ano)
    if limite: alvo = alvo[-limite:]
    lidos, faltando = [], []
    for ym in alvo:
        p = fetch(ym)
        if not p:
            faltando.append(ym); continue
        try:
            n = ler(p, acc); lidos.append(ym)
            print(f"  {ym}: {n:,} linhas", file=sys.stderr)
        except Exception as e:
            print(f"  {ym}: erro ao ler ({e})", file=sys.stderr); faltando.append(ym)
    return acc, lidos, faltando


def mapa_orgaos():
    """node_id → (escopo, codigo). Base: data/generated/orcamento.yaml (mesmo casamento de
    etl/orcamento.py); reserva: nome normalizado do nó contra o nome do órgão no CSV."""
    nodes = json.load(open(ROOT / "build" / "graph.br.json", encoding="utf-8"))["nodes"]
    por_node = {}
    orc = ROOT / "data" / "generated" / "orcamento.yaml"
    if orc.exists():
        d = (yaml.safe_load(open(orc, encoding="utf-8")) or {}).get("nodes") or {}
        for nid, anos in d.items():
            for _, v in sorted(anos.items(), reverse=True):
                if v.get("codigo"):
                    por_node[nid] = ("superior" if str(v.get("escopo", "")).startswith("órgão superior") else "orgao", str(v["codigo"]))
                    break
    por_nome = {}
    for n in nodes.values():
        if n["type"] in ("dept_head", "commission"): continue
        for a in [n["name"]] + list(n.get("aliases") or []):
            for k in (norm(a), chave(a)):
                if len(k) > 4: por_nome.setdefault(k, n["id"])
    return nodes, por_node, por_nome


def monta_orgao(subs, acc):
    """Agrega os programas de um conjunto de órgãos subordinados."""
    prog = collections.defaultdict(lambda: [0.0, 0.0, 0.0]); aca = collections.defaultdict(float)
    for (sub, pro), v in acc["prog"].items():
        if sub in subs:
            t = prog[pro]; t[0] += v[0]; t[1] += v[1]; t[2] += v[2]
    for (sub, pro, a), v in acc["acao"].items():
        if sub in subs: aca[(pro, a)] += v
    if not prog: return None
    ordem = sorted(prog.items(), key=lambda kv: -kv[1][2])
    top, resto = ordem[:TOP_PROGRAMAS], ordem[TOP_PROGRAMAS:]
    lista = []
    for pro, v in top:
        acoes = sorted(((a, w) for (p2, a), w in aca.items() if p2 == pro), key=lambda kv: -kv[1])[:TOP_ACOES]
        lista.append({"codigo": pro, "nome": acc["nome_pro"].get(pro, ""), "empenhado": round(v[0], 2),
                      "liquidado": round(v[1], 2), "pago": round(v[2], 2),
                      "acoes_top": [{"codigo": a, "nome": acc["nome_aca"].get(a, ""), "pago": round(w, 2)} for a, w in acoes if w]})
    out = {"total_empenhado": round(sum(v[0] for v in prog.values()), 2),
           "total_liquidado": round(sum(v[1] for v in prog.values()), 2),
           "total_pago": round(sum(v[2] for v in prog.values()), 2),
           "programas_total": len(prog), "programas": lista}
    if resto:
        out["outros"] = {"programas": len(resto), "empenhado": round(sum(v[0] for _, v in resto), 2),
                         "pago": round(sum(v[2] for _, v in resto), 2)}
    return out


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

    nodes, por_node, por_nome = mapa_orgaos()
    acc0 = dados[anos[0]][0]
    # subordinados conhecidos e seus superiores (união dos dois exercícios)
    sup_de = {}
    for ano in anos: sup_de.update(dados[ano][0]["sup_de"])

    # node_id → conjunto de órgãos subordinados
    subs_por_node = {}
    for nid, (escopo, cod) in por_node.items():
        if nid not in nodes: continue
        subs = {s for s, sup in sup_de.items() if sup == cod} if escopo == "superior" else {cod}
        if escopo == "superior": subs.add(cod)
        if subs: subs_por_node[nid] = (escopo, cod, subs)
    # reserva por nome normalizado, só para órgãos ainda não cobertos
    cobertos = {s for _, _, subs in subs_por_node.values() for s in subs}
    nomes_org = {}
    for ano in anos: nomes_org.update(dados[ano][0]["nome_org"])
    reserva = 0
    for sub, nome in nomes_org.items():
        if sub in cobertos or not nome or sub not in sup_de: continue  # só órgãos subordinados
        nid = next((por_nome.get(norm(v)) or por_nome.get(chave(v)) for v in variantes(nome)
                    if por_nome.get(norm(v)) or por_nome.get(chave(v))), None)
        if nid and nid in nodes and nid not in subs_por_node:
            # se esse código também é órgão superior de outros, o nó agrega as vinculadas
            filhos = {s for s, sup in sup_de.items() if sup == sub}
            escopo = "superior" if len(filhos) > 1 else "orgao"
            subs = (filhos | {sub}) if escopo == "superior" else {sub}
            subs_por_node[nid] = (escopo, sub, subs); cobertos |= subs; reserva += 1

    orgaos = {}
    for nid, (escopo, cod, subs) in sorted(subs_por_node.items()):
        atual = monta_orgao(subs, dados[anos[0]][0])
        if not atual: continue
        atual["ano"] = anos[0]; atual["escopo"] = "órgão superior (inclui vinculadas)" if escopo == "superior" else "órgão"
        atual["codigo"] = cod; atual["orgaos_siafi"] = len(subs)
        ant = monta_orgao(subs, dados[anos[1]][0]) if len(anos) > 1 else None
        if ant: ant["ano"] = anos[1]; atual["anterior"] = ant
        orgaos[nid] = atual

    # maiores programas da União no exercício corrente
    tot_prog = collections.defaultdict(lambda: [0.0, 0.0])
    org_prog = collections.defaultdict(lambda: collections.defaultdict(float))
    for (sub, pro), v in acc0["prog"].items():
        t = tot_prog[pro]; t[0] += v[0]; t[1] += v[2]
        org_prog[pro][sup_de.get(sub, sub)] += v[2]
    maiores = []
    for pro, v in sorted(tot_prog.items(), key=lambda kv: -kv[1][1])[:25]:
        tops = sorted(org_prog[pro].items(), key=lambda kv: -kv[1])[:3]
        maiores.append({"codigo": pro, "nome": acc0["nome_pro"].get(pro, ""), "empenhado": round(v[0], 2), "pago": round(v[1], 2),
                        "orgaos_top": [{"codigo": c, "nome": nomes_org.get(c, ""), "pago": round(w, 2)} for c, w in tops]})

    # órgãos do CSV que não casaram com nenhum nó do grafo
    pago_sub = collections.defaultdict(float)
    for (sub, _), v in acc0["prog"].items(): pago_sub[sub] += v[2]
    nao_casados = [{"codigo": s, "nome": nomes_org.get(s, ""), "pago": round(v, 2)}
                   for s, v in sorted(pago_sub.items(), key=lambda kv: -kv[1]) if s not in cobertos][:40]

    total_uniao = {str(ano): {"empenhado": round(sum(v[0] for v in dados[ano][0]["prog"].values()), 2),
                              "liquidado": round(sum(v[1] for v in dados[ano][0]["prog"].values()), 2),
                              "pago": round(sum(v[2] for v in dados[ano][0]["prog"].values()), 2),
                              "meses": dados[ano][1], "meses_faltando": dados[ano][2]} for ano in anos}
    resumo = {"orgaos_no_grafo_com_codigo": len(por_node), "orgaos_casados": len(orgaos),
              "casados_por_nome": reserva, "orgaos_siafi_no_csv": len(pago_sub),
              "orgaos_siafi_sem_no": sum(1 for s in pago_sub if s not in cobertos),
              "pago_sem_no_pct": round(100 * sum(v for s, v in pago_sub.items() if s not in cobertos) / (sum(pago_sub.values()) or 1), 2),
              "total_uniao": total_uniao, "amostra": bool(amostra),
              "criterio": "programa = Programa Orçamentário do SIAFI; valores acumulados somando os CSVs mensais do exercício"}

    out = {"generated_at": TODAY.isoformat(), "fonte": FONTE,
           "fonte_url": "https://portaldatransparencia.gov.br/download-de-dados/despesas-execucao",
           "ano": anos[0], "ano_anterior": anos[1], "anos": anos,
           "orgaos": orgaos, "maiores_programas": maiores, "nao_casados": nao_casados, "resumo": resumo}

    txt = "# GERADO por etl/programas.py. Não edite à mão.\n" + yaml.dump(out, allow_unicode=True, sort_keys=False, width=120)
    destino = (CACHE / "programas-amostra.yaml") if amostra else OUT
    destino.write_text(txt, encoding="utf-8")
    print(f"programas: {len(orgaos)} órgãos casados de {len(por_node)} com código ({reserva} por nome); "
          f"{resumo['orgaos_siafi_sem_no']} órgãos SIAFI sem nó ({resumo['pago_sem_no_pct']}% do pago)")
    for ano in anos:
        t = total_uniao[str(ano)]
        print(f"  {ano}: R$ {t['empenhado']/1e9:,.1f} bi empenhados, R$ {t['pago']/1e9:,.1f} bi pagos em {len(t['meses'])} meses" + (f" (faltam {t['meses_faltando']})" if t["meses_faltando"] else ""))
    for m in maiores[:6]:
        print(f"  programa {m['codigo']} {m['nome'][:48]:48} R$ {m['pago']/1e9:,.1f} bi pagos")
    print("gravado em", destino)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"AVISO: etl/programas.py falhou ({e}); {OUT} não foi alterado.", file=sys.stderr)
        sys.exit(0)
