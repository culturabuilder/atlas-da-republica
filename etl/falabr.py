#!/usr/bin/env python3
"""Pedidos de acesso à informação por órgão → data/generated/falabr.yaml

O Atlas mostra o que cada órgão faz, quanto gasta e quem o chefia. Não mostrava uma coisa que o
cidadão sente na pele: quando alguém pergunta algo a este órgão, ele responde?

Fonte: Fala.BR, o sistema da Lei de Acesso à Informação (Lei 12.527/2011), em dados abertos da CGU:
https://dadosabertos-download.cgu.gov.br/FalaBR/Arquivos_FalaBR_Filtrado/Arquivos_csv_2026.zip
Um zip de 77 MB por ano, que abre em 520 MB de CSV em UTF-16, atualizado a cada poucos dias.

O que fica medido por órgão: quantos pedidos recebeu, quantos negou de todo, quantos concedeu em
parte, quantos disse não ter a informação ou não ser da sua competência, quantas vezes prorrogou o
prazo, e quantos recursos o cidadão teve de abrir para insistir. A taxa de negativa é o que mais
separa um órgão do outro: medido em 14/10/2026 sobre 63 mil pedidos de 2026, vai de 9,8% na Anvisa
a 30,8% no Ministério da Fazenda.

Duas armadilhas de atribuição, tratadas aqui:

  - Recurso de instância CGU tem a própria CGU como `OrgaoDestinatario` — são 1.503 recursos que, se
    atribuídos pelo destinatário, fariam a CGU parecer o órgão mais recorrido do governo. O órgão
    reclamado está em `OrgaoPedido`, e é esse que usamos.
  - "Informação inexistente" e "não tem competência" não são negativa de acesso: são contados
    separadamente, porque somá-los à negativa inflaria a opacidade de quem só recebeu pedido errado.

Uso: .venv/bin/python etl/falabr.py [--ano 2026]
"""
import argparse, collections, csv, datetime, io, json, pathlib, sys, urllib.error, urllib.request, zipfile
import yaml
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from casar_orgao import casar, indices

ROOT = pathlib.Path(__file__).resolve().parent.parent
SAIDA = ROOT / "data" / "generated" / "falabr.yaml"
CACHE = ROOT / "build" / "cache-falabr"; CACHE.mkdir(parents=True, exist_ok=True)
BASE = "https://dadosabertos-download.cgu.gov.br/FalaBR/Arquivos_FalaBR_Filtrado"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh) atlas-da-republica/0.1"}
TODAY = datetime.date.today()

# decisão -> como contamos. Negativa é só o que nega acesso ao que o órgão tem.
NEGA = {"Acesso Negado": "negado", "Acesso Parcialmente Concedido": "parcial"}
NAO_E_NEGATIVA = {"Informação Inexistente": "inexistente",
                  "Órgão não tem competência para responder sobre o assunto": "sem_competencia",
                  "Não se trata de solicitação de informação": "fora_da_lai",
                  "Pergunta Duplicada/Repetida": "duplicada"}


def baixar(ano, max_idade_h=24 * 6):
    nome = f"Arquivos_csv_{ano}.zip"
    p = CACHE / nome
    if p.exists() and p.stat().st_size > 1_000_000:
        idade = (datetime.datetime.now() - datetime.datetime.fromtimestamp(p.stat().st_mtime)).total_seconds()
        if idade < max_idade_h * 3600: return p
    url = f"{BASE}/{nome}"
    print("GET", url, file=sys.stderr)
    try:
        dados = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=900).read()
    except Exception as e:
        print(f"  falhou ({e})", file=sys.stderr)
        return p if p.exists() else None
    if len(dados) < 1_000_000:
        print(f"  arquivo curto ({len(dados)} bytes)", file=sys.stderr)
        return p if p.exists() else None
    p.write_bytes(dados); return p


def linhas(zip_path, marca):
    z = zipfile.ZipFile(zip_path)
    nomes = [n for n in z.namelist() if marca in n and n.lower().endswith(".csv")]
    if not nomes: return
    with z.open(nomes[0]) as f:
        # UTF-16 com BOM, como a CGU publica; errors=replace porque há linha com byte solto
        for r in csv.DictReader(io.TextIOWrapper(f, encoding="utf-16", errors="replace", newline=""), delimiter=";"):
            yield r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ano", type=int, default=TODAY.year)
    a = ap.parse_args()
    graf = ROOT / "build" / "graph.br.json"
    if not graf.exists(): sys.exit(2)
    N = json.load(open(graf, encoding="utf-8"))["nodes"]
    idx = indices(N)

    p = baixar(a.ano)
    if not p: sys.exit(2)

    org = collections.defaultdict(lambda: {"pedidos": 0, "negado": 0, "parcial": 0, "concedido": 0,
                                           "inexistente": 0, "sem_competencia": 0, "fora_da_lai": 0,
                                           "duplicada": 0, "outra": 0, "prorrogados": 0,
                                           "motivos": collections.Counter(), "recursos": 0,
                                           "assuntos": collections.Counter()})
    total = 0
    for r in linhas(p, "_Pedidos_csv_"):
        if (r.get("Esfera") or "").strip() != "Federal": continue
        nome = (r.get("OrgaoDestinatario") or "").strip()
        if not nome: continue
        total += 1
        g = org[nome]; g["pedidos"] += 1
        d = (r.get("Decisao") or "").strip()
        if d in NEGA: g[NEGA[d]] += 1
        elif d in NAO_E_NEGATIVA: g[NAO_E_NEGATIVA[d]] += 1
        elif d == "Acesso Concedido": g["concedido"] += 1
        else: g["outra"] += 1
        if (r.get("FoiProrrogado") or "").strip().lower() == "sim": g["prorrogados"] += 1
        m = (r.get("MotivoNegativaAcesso") or "").strip()
        if m: g["motivos"][m[:70]] += 1
        s = (r.get("AssuntoPedido") or "").strip()
        if s: g["assuntos"][s[:46]] += 1

    # recurso vai para o órgão reclamado (OrgaoPedido), não para quem julga
    rec_total = 0
    for r in linhas(p, "_Recursos_csv_"):
        nome = (r.get("OrgaoPedido") or r.get("OrgaoDestinatario") or "").strip()
        if not nome: continue
        rec_total += 1
        org[nome]["recursos"] += 1

    saida = {}
    nao_casados = collections.Counter()
    for nome, g in org.items():
        nid, _ = casar(nome, idx)
        if not nid: nao_casados[nome] = g["pedidos"]
        neg = g["negado"] + g["parcial"]
        # a taxa olha só o que o órgão decidiu sobre informação que lhe cabia
        base = g["concedido"] + g["negado"] + g["parcial"]
        saida[nome] = {"node": nid, "pedidos": g["pedidos"],
                       "concedido": g["concedido"], "negado": g["negado"], "parcial": g["parcial"],
                       "inexistente": g["inexistente"], "sem_competencia": g["sem_competencia"],
                       "fora_da_lai": g["fora_da_lai"], "duplicada": g["duplicada"], "outra": g["outra"],
                       "prorrogados": g["prorrogados"], "recursos": g["recursos"],
                       "decididos": base,
                       "pct_negado_ou_parcial": round(100 * neg / base, 1) if base >= 20 else None,
                       "pct_prorrogado": round(100 * g["prorrogados"] / g["pedidos"], 1) if g["pedidos"] >= 20 else None,
                       "motivos_top": [{"motivo": k, "n": v} for k, v in g["motivos"].most_common(4)],
                       "assuntos_top": [{"assunto": k, "n": v} for k, v in g["assuntos"].most_common(4)]}
    saida = dict(sorted(saida.items(), key=lambda kv: -kv[1]["pedidos"]))
    com_taxa = [v for v in saida.values() if v["pct_negado_ou_parcial"] is not None]
    geral_base = sum(v["decididos"] for v in saida.values())
    geral_neg = sum(v["negado"] + v["parcial"] for v in saida.values())

    out = {"generated_at": TODAY.isoformat(), "ano": a.ano,
           "fonte": "Fala.BR (Lei 12.527/2011), dados abertos da Controladoria-Geral da União",
           "nota": ("Pedidos de acesso à informação de esfera federal registrados no ano. A taxa de negativa olha só "
                    "os pedidos que o órgão decidiu sobre informação que lhe cabia: 'informação inexistente' e 'não "
                    "tem competência' são contados à parte, porque somá-los inflaria a opacidade de quem apenas "
                    "recebeu pedido endereçado errado. Recurso é atribuído ao órgão reclamado, não a quem julga. "
                    "Taxa só é calculada com 20 decisões ou mais."),
           "resumo": {"pedidos": total, "orgaos": len(saida), "orgaos_casados": sum(1 for v in saida.values() if v["node"]),
                      "recursos": rec_total, "decididos": geral_base,
                      "pct_negado_ou_parcial_geral": round(100 * geral_neg / geral_base, 1) if geral_base else None,
                      "orgaos_com_taxa": len(com_taxa)},
           "mais_negam": sorted([{"orgao": k, **{x: v[x] for x in ("node", "pedidos", "decididos", "pct_negado_ou_parcial", "recursos")}}
                                 for k, v in saida.items() if v["pct_negado_ou_parcial"] is not None],
                                key=lambda x: -x["pct_negado_ou_parcial"])[:20],
           "orgaos": saida,
           "nao_casados": [{"orgao": k, "pedidos": v} for k, v in nao_casados.most_common(25)]}
    SAIDA.write_text("# GERADO por etl/falabr.py. Não edite à mão.\n" +
                     yaml.dump(out, allow_unicode=True, sort_keys=False, width=150), encoding="utf-8")
    r = out["resumo"]
    print(f"Fala.BR {a.ano}: {r['pedidos']:,} pedidos em {r['orgaos']} órgãos ({r['orgaos_casados']} casados) · "
          f"{r['recursos']:,} recursos · {r['pct_negado_ou_parcial_geral']}% negado ou parcial no conjunto")
    print("maiores taxas de negativa (com 20+ decisões):")
    for x in out["mais_negam"][:6]:
        print(f"   {x['pct_negado_ou_parcial']:>5.1f}% · {x['decididos']:>5} decididos · {x['orgao'][:50]}")


if __name__ == "__main__": main()
