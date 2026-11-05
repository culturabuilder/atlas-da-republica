#!/usr/bin/env python3
"""Superior Tribunal de Justiça → data/generated/stj.yaml

Por que existe: medido em 29/10/2026, 63% dos órgãos do Judiciário no Atlas não tinham nenhum dado
aberto — o pior número da página /quem-publica/. O STJ é o maior tribunal do país que publica dados
abertos em CKAN, e publica justamente o que o Atlas já sabe mostrar do Executivo:

  penalidades-fornecedores   empresa punida pelo tribunal, com CNPJ, motivo e ato — a mesma forma
                             das sanções da CGU (etl/sancoes.py)
  diarias-e-passagens        viagens pagas, como etl/viagens.py faz no Executivo

Fora de escopo por tamanho: `acervo-em-tramitacao` é um .json.gz de 76 MB por dia, para um número de
manchete; e `folha-de-pagamento-de-pessoal`, que hoje devolve HTTP 500 na própria fonte.

Privacidade: o bloco das viagens é agregado por cargo, nunca por pessoa — são servidores de
execução, não ocupantes de cargo mapeado, e é a mesma regra que o Atlas aplica ao cartão corporativo
e às diárias do Executivo. As penalidades nomeiam EMPRESA, como as sanções da CGU já fazem.

Fonte: https://dadosabertos.web.stj.jus.br (CKAN). Os ids de recurso mudam quando o tribunal
republica, então nada de URL fixa: pergunta-se ao CKAN qual é o recurso de cada conjunto.

Uso: .venv/bin/python etl/stj.py [--debug]
"""
import argparse, collections, csv, datetime, io, json, pathlib, re, sys, unicodedata, urllib.error, urllib.request
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "generated" / "stj.yaml"
CACHE = ROOT / "build" / "cache-stj"; CACHE.mkdir(parents=True, exist_ok=True)
CKAN = "https://dadosabertos.web.stj.jus.br/api/3/action"
NODE = "br-superior-tribunal-de-justica"
UA = {"User-Agent": "Mozilla/5.0 (compatible) atlas-da-republica/0.1 (+https://atlasdarepublica.org)",
      "Accept": "application/json, text/csv, */*"}
TODAY = datetime.date.today()


def pega(url, timeout=120):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def recurso(pacote, casa):
    """URL e data do recurso de um pacote CKAN cujo nome casa com `casa` (regex), ignorando dicionário."""
    d = json.loads(pega(f"{CKAN}/package_show?id={pacote}", 60))["result"]
    melhor = None
    for r in d.get("resources") or []:
        nome = f"{r.get('name') or ''} {r.get('url') or ''}"
        if re.search(r"(?i)dicion", nome): continue
        if not re.search(casa, nome, re.I): continue
        data = str(r.get("last_modified") or r.get("created") or "")[:10]
        if not melhor or data > melhor[1]: melhor = (r.get("url"), data)
    return melhor or (None, None)


def tabela(url, nome):
    """Lê um CSV do STJ com cache em disco; devolve lista de dicionários."""
    p = CACHE / nome
    try:
        b = pega(url)
        p.write_bytes(b)
    except Exception as e:
        if not p.exists(): raise
        print(f"  {nome}: fonte falhou ({type(e).__name__}); usando a cópia em disco", file=sys.stderr)
        b = p.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "latin1"):
        try: t = b.decode(enc); break
        except UnicodeDecodeError: continue
    primeira = t.splitlines()[0] if t else ""
    sep = ";" if primeira.count(";") >= primeira.count(",") else ","
    return list(csv.DictReader(io.StringIO(t), delimiter=sep))


def dinheiro(s):
    s = str(s or "").strip().replace("R$", "").replace(" ", "")
    if not s: return 0.0
    if "," in s: s = s.replace(".", "").replace(",", ".")
    try: return float(s)
    except ValueError: return 0.0


def so_digitos(s): return re.sub(r"\D", "", str(s or ""))


def tipo_penalidade(s):
    """Agrupa o texto livre do tribunal nas quatro formas da Lei 14.133/2021 e da 8.666/1993."""
    t = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    if "advert" in t: return "advertência"
    if "multa" in t: return "multa"
    if "impedimento" in t or "suspens" in t: return "suspensão ou impedimento de licitar"
    if "declara" in t or "inidon" in t: return "declaração de inidoneidade"
    if "rescis" in t: return "rescisão contratual"
    return "outra"


def penalidades():
    url, data = recurso("penalidades-fornecedores", r"penalidade")
    if not url: return None
    rows = tabela(url, "penalidades.csv")
    por_tipo = collections.Counter(); empresas = set(); itens = []
    vigentes = 0
    for r in rows:
        tp = tipo_penalidade(r.get("penalizacao"))
        por_tipo[tp] += 1
        cnpj = so_digitos(r.get("CPF_CNPJ") or r.get("cpf_cnpj"))
        if cnpj: empresas.add(cnpj)
        fim = (r.get("data_fim_penalidade") or "").strip()
        if fim and fim >= TODAY.isoformat(): vigentes += 1
        itens.append({"empresa": (r.get("fornecedor_nome_razao_social") or "").strip()[:120],
                      "cnpj": cnpj or None, "tipo": tp,
                      "penalizacao": (r.get("penalizacao") or "").strip()[:120],
                      "motivo": (r.get("desc_motivo_penalizacao") or "").strip()[:220],
                      "ato": (r.get("ato_sancionador") or "").strip()[:140],
                      "data": (r.get("data_aplicacao") or "").strip()[:10],
                      "fim": fim[:10] or None})
    itens.sort(key=lambda x: x["data"] or "", reverse=True)
    return {"total": len(rows), "empresas": len(empresas), "vigentes_hoje": vigentes,
            "por_tipo": dict(por_tipo.most_common()), "ultimas": itens[:12],
            "desde": min((x["data"] for x in itens if x["data"]), default=None),
            "arquivo_de": data, "fonte": "STJ, dados abertos — Penalidades a fornecedores",
            "fonte_url": "https://dadosabertos.web.stj.jus.br/dataset/penalidades-fornecedores"}


def viagens():
    url, data = recurso("diarias-e-passagens", r"di[aá]ria")
    if not url: return None
    rows = tabela(url, "diarias.csv")
    # Usar os valores PAGOS que o arquivo já traz. A primeira versão recalculava diária unitária ×
    # quantidade, o que ignorava a passagem aérea e, pior, somava dólar como se fosse real: a coluna
    # Moeda é U$ nas viagens ao exterior (a primeira linha do arquivo é uma delas). Dava R$ 8,70 mi;
    # somando as colunas de valor pago, conferido à mão sobre as 2.004 linhas, são R$ 11,59 mi
    # (8,78 de diária + 2,80 de passagem). Valor errado publicado é pior que valor ausente.
    por_cargo = collections.Counter(); gasto_cargo = collections.Counter()
    diarias = passagens = 0.0; viagens_n = 0
    destinos = collections.Counter(); anos = collections.Counter()
    quem = collections.Counter(); gasto_quem = collections.Counter()
    exterior = 0; gasto_exterior = 0.0
    for r in rows:
        viagens_n += 1
        d = dinheiro(r.get("Valor_Pago_Diarias")); pa = dinheiro(r.get("Valor_Pago_Passagens_Aereas"))
        diarias += d; passagens += pa
        cargo = (r.get("Cargo_Funcao_Atribuicao") or "").split("/")[0].strip()[:60] or "não informado"
        por_cargo[cargo] += 1; gasto_cargo[cargo] += d + pa
        # o próprio arquivo classifica, em vez de eu adivinhar pela sigla do destino
        k = (r.get("Magistrado_OU_Servidor") or "não informado").strip()
        quem[k] += 1; gasto_quem[k] += d + pa
        if re.search(r"(?i)internacional", r.get("Nacional_OU_Internacional") or ""):
            exterior += 1; gasto_exterior += d + pa
        destinos[(r.get("Destino_Cidade") or r.get("Destino_Pais") or "não informado").strip()[:40]] += 1
        ano = (r.get("Data_Ida") or "")[:4]
        if ano.isdigit(): anos[ano] += 1
    total = diarias + passagens
    return {"viagens": viagens_n, "total": round(total, 2), "diarias": round(diarias, 2), "passagens": round(passagens, 2),
            "ao_exterior": exterior, "gasto_exterior": round(gasto_exterior, 2),
            "por_quem": [{"quem": k, "viagens": n, "gasto": round(gasto_quem[k], 2)} for k, n in quem.most_common()],
            "por_cargo": [{"cargo": c, "viagens": n, "gasto": round(gasto_cargo[c], 2)} for c, n in por_cargo.most_common(8)],
            "destinos_top": [{"destino": d_, "viagens": n} for d_, n in destinos.most_common(8)],
            "por_ano": dict(sorted(anos.items())), "arquivo_de": data,
            "fonte": "STJ, dados abertos — Diárias e Passagens",
            "fonte_url": "https://dadosabertos.web.stj.jus.br/dataset/diarias-e-passagens",
            "nota": ("Valores pagos informados pelo próprio tribunal, em reais, somando diária e passagem aérea. "
                     "Agregado por cargo e por magistrado/servidor, nunca por pessoa: são em grande parte servidores "
                     "de execução, não ocupantes de cargo mapeado.")}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--debug", action="store_true"); a = ap.parse_args()
    blocos, falhas = {}, []
    for nome, fn in (("penalidades", penalidades), ("viagens", viagens)):
        try:
            v = fn()
            if v: blocos[nome] = v
            else: falhas.append(f"{nome}: recurso não encontrado no CKAN")
        except Exception as e:
            falhas.append(f"{nome}: {type(e).__name__} {str(e)[:70]}")
            if a.debug: raise
    if not blocos:
        # Nada lido: manter o arquivo anterior é melhor que publicar menos do que já havia.
        print("STJ: nenhum conjunto pôde ser lido; mantendo o gerado anterior. " + "; ".join(falhas), file=sys.stderr)
        return 1 if OUT.exists() else 0
    out = {"generated_at": TODAY.isoformat(), "node": NODE,
           "fonte": "Superior Tribunal de Justiça, portal de dados abertos (CKAN)",
           "fonte_url": "https://dadosabertos.web.stj.jus.br",
           "nota": ("O que o próprio tribunal publica em formato aberto. Não inclui processos: o acervo em "
                    "tramitação é um arquivo de 76 MB por dia, e a folha de pagamento devolve erro na fonte."),
           "falhas": falhas, **blocos}
    OUT.write_text("# GERADO por etl/stj.py. Não edite à mão.\n" + yaml.dump(out, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    pen, vg = blocos.get("penalidades") or {}, blocos.get("viagens") or {}
    print(f"STJ: penalidades {pen.get('total', 0)} a {pen.get('empresas', 0)} empresas "
          f"({pen.get('vigentes_hoje', 0)} vigentes, arquivo de {pen.get('arquivo_de')}) · "
          f"viagens {vg.get('viagens', 0)}, R$ {(vg.get('total') or 0)/1e6:.1f} mi, arquivo de {vg.get('arquivo_de')}"
          + (f" · falhas: {'; '.join(falhas)}" if falhas else ""))
    return 0


if __name__ == "__main__": sys.exit(main())
