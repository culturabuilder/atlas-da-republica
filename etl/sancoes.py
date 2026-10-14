#!/usr/bin/env python3
"""Punições registradas pela CGU → data/generated/sancoes.yaml

Quatro cadastros públicos, baixados do Portal da Transparência em ZIP diário, sem chave:

  CEAF  — servidores federais expulsos (demissão, cassação de aposentadoria, destituição)
  CEIS  — empresas impedidas de contratar com o poder público
  CNEP  — empresas punidas pela Lei Anticorrupção (Lei 12.846/2013), com valor de multa
  Leniência — acordos em que a empresa confessou e negociou

Decisões que valem registrar:

1. O Atlas é federal. CEIS e CNEP trazem sanção estadual e municipal (no CEIS, 15 mil das 23 mil
   linhas): entram só as de esfera FEDERAL, e o arquivo diz quantas ficaram de fora.
2. O CPF NÃO é publicado. A própria CGU já o entrega mascarado ("***.158.407-**"), e CPF exposto no
   Brasil é risco de fraude sem ganho para o leitor. Nome, cargo, órgão, data e fundamento bastam
   para conferir na fonte.
3. Órgão extinto não é casado com o sucessor de hoje. O Ministério da Economia existiu de 2019 a
   2022 e foi dividido em Fazenda, Gestão, MDIC e Planejamento: pendurar uma demissão de 2020 na
   Fazenda de hoje seria atribuir a ela um fato que não é dela. Esses casos estão em NAO_CASAR, com
   o motivo, e aparecem no total sem página de órgão.
4. Órgão que só mudou de nome é casado, porque é a mesma pessoa jurídica. Os casos estão em
   NOMES_ANTIGOS, um por um, para ninguém ter de adivinhar.

Uso: .venv/bin/python etl/sancoes.py [--data AAAAMMDD]
"""
import argparse, csv, collections, datetime, io, json, pathlib, re, sys, urllib.error, urllib.request, zipfile
import yaml
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from casar_orgao import EXTINTOS, casar, indices

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "generated"
CACHE = ROOT / "build" / "cache-sancoes"; CACHE.mkdir(parents=True, exist_ok=True)
SAIDA = DATA / "sancoes.yaml"
BASE = "https://portaldatransparencia.gov.br/download-de-dados"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh) atlas-da-republica/0.1"}
TODAY = datetime.date.today()

CADASTROS = {"ceaf": "Expulsoes", "ceis": "CEIS", "cnep": "CNEP", "acordos-leniencia": "Acordos"}


def baixar(cadastro, data):
    nome = f"{data}_{cadastro}.zip"
    p = CACHE / nome
    if p.exists() and p.stat().st_size > 2000: return p
    url = f"{BASE}/{cadastro}/{data}"
    try:
        dados = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=600).read()
    except urllib.error.HTTPError as e:
        print(f"  {cadastro} {data}: HTTP {e.code}", file=sys.stderr); return None
    except Exception as e:
        print(f"  {cadastro} {data}: {e}", file=sys.stderr); return None
    if len(dados) < 2000:
        print(f"  {cadastro} {data}: arquivo curto ({len(dados)} bytes)", file=sys.stderr); return None
    p.write_bytes(dados); return p


def ler_csv(zip_path, marca):
    z = zipfile.ZipFile(zip_path)
    nomes = [n for n in z.namelist() if n.lower().endswith(".csv") and marca.lower() in n.lower()]
    if not nomes: nomes = [n for n in z.namelist() if n.lower().endswith(".csv")]
    with z.open(nomes[0]) as f:
        return list(csv.DictReader(io.TextIOWrapper(f, encoding="latin1"), delimiter=";"))


def dia(s):
    s = (s or "").strip()
    try: return datetime.datetime.strptime(s, "%d/%m/%Y").date().isoformat()
    except ValueError: return None


def dinheiro(s):
    try: return float((s or "0").replace(".", "").replace(",", "."))
    except ValueError: return 0.0


def achar_data(preferida=None):
    """O Portal publica um arquivo por dia; procura o mais recente que exista."""
    if preferida: return preferida
    for d in range(0, 8):
        data = (TODAY - datetime.timedelta(days=d)).strftime("%Y%m%d")
        if baixar("ceaf", data): return data
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=None, help="AAAAMMDD do arquivo no Portal; por padrão procura o mais recente")
    a = ap.parse_args()

    graf = ROOT / "build" / "graph.br.json"
    if not graf.exists(): sys.exit(2)
    N = json.load(open(graf, encoding="utf-8"))["nodes"]
    idx = indices(N)
    nome_no = {i: n.get("name") for i, n in N.items()}

    data = achar_data(a.data)
    if not data: sys.exit("nenhum arquivo do Portal da Transparência disponível nos últimos 8 dias")
    print(f"arquivos de {data[:4]}-{data[4:6]}-{data[6:]}", file=sys.stderr)

    brutos = {}
    for cad, marca in CADASTROS.items():
        p = baixar(cad, data)
        if not p: continue
        try: brutos[cad] = ler_csv(p, marca)
        except Exception as e: print(f"  {cad}: erro ao ler ({e})", file=sys.stderr)
    if "ceaf" not in brutos: sys.exit("CEAF indisponível; arquivo anterior mantido")

    nao_casados = collections.Counter()
    motivos = {}

    def resolver(orgao):
        nid, como = casar(orgao, idx)
        if not nid:
            nao_casados[orgao or "(sem nome)"] += 1
            motivos[orgao or "(sem nome)"] = como
        return nid, como

    # ---- CEAF: pessoas. Nome, cargo, órgão, data e fundamento; nunca o CPF.
    ceaf_pessoas, ceaf_org = [], collections.defaultdict(lambda: {"n": 0, "cat": collections.Counter()})
    for r in brutos["ceaf"]:
        if (r.get("ESFERA ÓRGÃO SANCIONADOR") or "").strip().upper() not in ("FEDERAL", ""): continue
        orgao = (r.get("ÓRGÃO DE LOTAÇÃO") or "").strip()
        if orgao.lower().startswith("sem informa"): orgao = ""
        nid, _ = resolver(orgao) if orgao else (None, "sem nome")
        cat = (r.get("CATEGORIA DA SANÇÃO") or "").strip()
        cargo = (r.get("CARGO EFETIVO") or "").strip()
        func = (r.get("FUNÇÃO OU CARGO DE CONFIANÇA") or "").strip()
        reg = {"nome": (r.get("NOME DO SANCIONADO") or "").strip(), "categoria": cat,
               "cargo": "" if cargo.lower().startswith("sem informa") else cargo,
               "funcao": "" if func.lower().startswith("sem informa") else func,
               "orgao": orgao, "node": nid,
               "data": dia(r.get("DATA PUBLICAÇÃO")) or dia(r.get("DATA INÍCIO SANÇÃO")),
               "fundamento": re.sub(r"\s+", " ", (r.get("FUNDAMENTAÇÃO LEGAL") or "").strip())[:180],
               "processo": (r.get("NÚMERO DO PROCESSO") or "").strip(),
               "publicacao": re.sub(r"\s+", " ", (r.get("PUBLICAÇÃO") or "").strip())[:90]}
        ceaf_pessoas.append(reg)
        if nid:
            ceaf_org[nid]["n"] += 1; ceaf_org[nid]["cat"][cat] += 1
    ceaf_pessoas.sort(key=lambda x: (x["data"] or "", x["nome"]), reverse=True)

    # ---- empresas: CEIS, CNEP, leniência. Só esfera federal.
    def empresas(cad, com_multa=False):
        rows = brutos.get(cad) or []
        fora = sum(1 for r in rows if (r.get("ESFERA ÓRGÃO SANCIONADOR") or "").strip().upper() not in ("FEDERAL", ""))
        fed = [r for r in rows if (r.get("ESFERA ÓRGÃO SANCIONADOR") or "").strip().upper() in ("FEDERAL", "")]
        por_cat = collections.Counter((r.get("CATEGORIA DA SANÇÃO") or "").strip() for r in fed)
        por_org = collections.defaultdict(lambda: {"n": 0, "multa": 0.0})
        itens = []
        for r in fed:
            orgao = (r.get("ÓRGÃO SANCIONADOR") or "").strip()
            nid, _ = resolver(orgao) if orgao else (None, "sem nome")
            multa = dinheiro(r.get("VALOR DA MULTA")) if com_multa else 0.0
            if nid:
                por_org[nid]["n"] += 1; por_org[nid]["multa"] += multa
            itens.append({"nome": (r.get("RAZÃO SOCIAL - CADASTRO RECEITA") or r.get("NOME DO SANCIONADO") or "").strip(),
                          "cnpj": re.sub(r"\D", "", r.get("CPF OU CNPJ DO SANCIONADO") or "")[:14],
                          "categoria": (r.get("CATEGORIA DA SANÇÃO") or "").strip(),
                          "orgao": orgao, "node": nid, "data": dia(r.get("DATA PUBLICAÇÃO")),
                          "fim": dia(r.get("DATA FINAL SANÇÃO")),
                          **({"multa": round(multa, 2)} if com_multa else {})})
        # A lista inteira de empresas (8.666 no CEIS) custaria 2,3 MB num arquivo que vai para o git
        # todo dia, e nada no site a consome: as telas usam o agregado por órgão. Guardamos as 200
        # mais recentes, que é o bastante para conferir a leitura por amostra, e o total verdadeiro.
        itens.sort(key=lambda x: x.get("data") or "", reverse=True)
        return {"total": len(fed), "fora_do_escopo_federal": fora, "por_categoria": dict(por_cat.most_common()),
                "por_orgao": {k: {"n": v["n"], **({"multa": round(v["multa"], 2)} if com_multa else {})} for k, v in por_org.items()},
                "amostra_recente": itens[:200]}

    ceis = empresas("ceis")
    cnep = empresas("cnep", com_multa=True)

    lenien = []
    efeitos = collections.defaultdict(list)
    for p in (CACHE / f"{data}_Acordos.zip",):
        if not p.exists(): continue
        try:
            for r in ler_csv(p, "Efeitos"):
                efeitos[(r.get("ID DO ACORDO") or "").strip()].append(re.sub(r"\s+", " ", (r.get("EFEITO DO ACORDO DE LENIENCIA") or "").strip()))
        except Exception: pass
    for r in (brutos.get("acordos-leniencia") or []):
        ident = (r.get("ID DO ACORDO") or "").strip()
        lenien.append({"id": ident,
                       "nome": (r.get("RAZÃO SOCIAL  CADASTRO RECEITA") or r.get("RAZÃO SOCIAL - CADASTRO RECEITA") or "").strip(),
                       "situacao": (r.get("SITUAÇÃO DO ACORDO DE LENIÊNICA") or "").strip(),
                       "inicio": dia(r.get("DATA DE INÍCIO DO ACORDO")), "fim": dia(r.get("DATA DE FIM DO ACORDO")),
                       "processo": (r.get("NÚMERO DO PROCESSO") or "").strip(),
                       "efeitos": sorted(set(efeitos.get(ident) or []))[:6]})
    lenien.sort(key=lambda x: x["inicio"] or "", reverse=True)

    por_ano = collections.Counter((p["data"] or "")[:4] for p in ceaf_pessoas if p["data"])
    por_cat = collections.Counter(p["categoria"] for p in ceaf_pessoas)
    out = {
        "generated_at": TODAY.isoformat(),
        "data_do_arquivo": f"{data[:4]}-{data[4:6]}-{data[6:]}",
        "fonte": "Controladoria-Geral da União, via Portal da Transparência (CEAF, CEIS, CNEP e acordos de leniência)",
        "nota": ("Registro oficial de punições já aplicadas e publicadas em diário oficial. O CPF não é publicado aqui: "
                 "a própria CGU o entrega mascarado. Sanção estadual e municipal fica fora, porque o Atlas é federal. "
                 "Órgão extinto sem sucessor único não é atribuído a nenhum órgão de hoje."),
        "ceaf": {"total": len(ceaf_pessoas), "por_categoria": dict(por_cat.most_common()),
                 "por_ano": dict(sorted(por_ano.items())),
                 "orgaos_casados": len(ceaf_org),
                 "por_orgao": {k: {"n": v["n"], "nome": nome_no.get(k), "por_categoria": dict(v["cat"].most_common())}
                               for k, v in sorted(ceaf_org.items(), key=lambda kv: -kv[1]["n"])},
                 "pessoas": ceaf_pessoas},
        "ceis": ceis, "cnep": cnep,
        "leniencia": {"total": len(lenien), "acordos": lenien},
        "orgaos_nao_casados": {"entidades": len(nao_casados), "registros": sum(nao_casados.values()),
                               "extintos_declarados": dict(EXTINTOS),
                               "maiores": [{"orgao": o, "n": n, "motivo": motivos.get(o)} for o, n in nao_casados.most_common(40)]},
    }
    SAIDA.write_text("# GERADO por etl/sancoes.py. Não edite à mão.\n" +
                     yaml.dump(out, allow_unicode=True, sort_keys=False, width=150), encoding="utf-8")
    print(f"CEAF: {len(ceaf_pessoas)} servidores expulsos, {len(ceaf_org)} órgãos casados · {dict(por_cat.most_common(3))}")
    print(f"CEIS: {ceis['total']} federais ({ceis['fora_do_escopo_federal']} fora do escopo) · CNEP: {cnep['total']} ({cnep['fora_do_escopo_federal']} fora) · leniência: {len(lenien)}")
    print(f"órgãos não casados: {len(nao_casados)} entidades, {sum(nao_casados.values())} registros")
    for x in out["orgaos_nao_casados"]["maiores"][:5]: print(f"   {x['n']:>4}  {x['orgao'][:52]}  [{x['motivo']}]")


if __name__ == "__main__": main()
