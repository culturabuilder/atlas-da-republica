#!/usr/bin/env python3
"""Contratos federais no PNCP → data/generated/contratos.yaml

O Atlas mostrava para onde o orçamento foi empenhado e quanto cada órgão gastou, mas não COM QUEM
cada órgão assinou contrato. Contrato é onde o dinheiro vira decisão, e faltava inteiro.

Fonte: Portal Nacional de Contratações Públicas (Lei 14.133/2021), API pública de consulta, sem
chave: https://pncp.gov.br/api/consulta/v1/contratos?dataInicial=&dataFinal=&pagina=

O que medi antes de escrever, porque a documentação promete mais do que entrega:

  - A API não filtra por esfera. São ~59 mil contratos por 10 dias no país, dos quais 5% a 14% são
    federais: é preciso paginar tudo e filtrar. Com tamanhoPagina=500 dá ~120 páginas por janela
    de 10 dias, o que cabe no tempo de um conector.
  - `emendaParlamentar` NÃO serve para amarrar emenda a contrato, e isso é o oposto do que a
    documentação sugere. O campo é um booleano: quando vem, vem `true`, sem número de emenda e sem
    nome de parlamentar. Em 3.000 contratos de duas janelas de setembro veio nulo em todos; numa
    janela de outubro veio `true` em 12 de 2.676. Diz que houve emenda em algum ponto daquele
    contrato, e nada mais. Quem quiser ligar emenda a contrato precisa de outra fonte.
  - `identificadorCipi` liga o contrato à obra no Obrasgov, mas é esparso e irregular: 51 de 1.500
    numa janela de setembro, 0 de 2.676 numa de outubro. Guardamos quando vem.
  - `orgaoEntidade.razaoSocial` é o nome no cadastro da Receita, que atrasa: 67 contratos de 2026
    da Receita Federal vêm sob "MINISTERIO DA ECONOMIA", extinto em 2022. Quem assinou de verdade
    está em `unidadeOrgao.nomeUnidade` ("Superintendência Regional da Receita Federal"). Por isso o
    casamento tenta a razão social e, quando ela falha ou aponta para órgão extinto, tenta a unidade.

O arquivo acumula: cada rodada soma a janela nova ao que já havia por órgão, e o mapa CNPJ -> nó
aprendido fica guardado, de modo que o casamento melhora sozinho a cada rodada.

Uso: .venv/bin/python etl/contratos.py [--dias 10] [--paginas 200]
"""
import argparse, collections, datetime, json, pathlib, sys, time, urllib.error, urllib.parse, urllib.request
import yaml
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from casar_orgao import EXTINTOS, casar, indices, nucleo

ROOT = pathlib.Path(__file__).resolve().parent.parent
SAIDA = ROOT / "data" / "generated" / "contratos.yaml"
API = "https://pncp.gov.br/api/consulta/v1/contratos"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh) atlas-da-republica/0.1", "Accept": "application/json"}
TODAY = datetime.date.today()
PAUSA = 0.4


def pagina(de, ate, n, tam=500, tentativas=3):
    url = f"{API}?dataInicial={de}&dataFinal={ate}&pagina={n}&tamanhoPagina={tam}"
    for t in range(tentativas):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 404: return None          # além da última página
            if t == tentativas - 1: raise
        except Exception:
            if t == tentativas - 1: raise
        time.sleep(2 * (t + 1))
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=int, default=10, help="janela, em dias, até hoje")
    ap.add_argument("--paginas", type=int, default=200, help="teto de páginas por rodada")
    ap.add_argument("--segundos", type=int, default=600, help="orçamento de tempo")
    a = ap.parse_args()

    graf = ROOT / "build" / "graph.br.json"
    if not graf.exists(): sys.exit(2)
    N = json.load(open(graf, encoding="utf-8"))["nodes"]
    idx = indices(N)

    anterior = {}
    if SAIDA.exists():
        try: anterior = yaml.safe_load(SAIDA.read_text(encoding="utf-8")) or {}
        except Exception: anterior = {}
    # CNPJ -> nó, aprendido nas rodadas anteriores: o cadastro da Receita atrasa, o CNPJ não muda
    cnpj_no = dict(anterior.get("cnpj_no") or {})

    de = (TODAY - datetime.timedelta(days=a.dias)).strftime("%Y%m%d")
    ate = TODAY.strftime("%Y%m%d")
    print(f"janela {de} a {ate}", file=sys.stderr)

    def resolver(c):
        o = c.get("orgaoEntidade") or {}
        cnpj = (o.get("cnpj") or "").strip()
        if cnpj and cnpj_no.get(cnpj): return cnpj_no[cnpj], "cnpj conhecido"
        nid, como = casar(o.get("razaoSocial") or "", idx)
        if not nid:
            # a razão social é o nome no cadastro da Receita e atrasa; a unidade diz quem assinou
            uni = (c.get("unidadeOrgao") or {}).get("nomeUnidade") or ""
            nid2, _ = casar(uni, idx)
            if nid2: nid, como = nid2, "unidade"
        if nid and cnpj: cnpj_no[cnpj] = nid
        return nid, como

    por_no = collections.defaultdict(lambda: {"n": 0, "valor": 0.0, "fornecedores": collections.Counter(),
                                              "valor_forn": collections.Counter(), "recentes": []})
    nao_casados = collections.Counter()
    vistos = set()
    t0 = time.time()
    total_fed = 0; total_geral = 0; paginas = 0; com_cipi = 0; com_emenda = 0
    n = 1
    while paginas < a.paginas and time.time() - t0 < a.segundos:
        try: d = pagina(de, ate, n)
        except Exception as e:
            print(f"  página {n} falhou: {e}", file=sys.stderr); break
        if not d or not (d.get("data") or []): break
        paginas += 1
        for c in d["data"]:
            total_geral += 1
            o = c.get("orgaoEntidade") or {}
            if (o.get("esferaId") or "") != "F": continue
            ident = c.get("numeroControlePNCP") or ""
            if ident in vistos: continue
            vistos.add(ident)
            total_fed += 1
            if c.get("identificadorCipi"): com_cipi += 1
            if c.get("emendaParlamentar"): com_emenda += 1
            nid, _ = resolver(c)
            if not nid:
                nao_casados[(o.get("razaoSocial") or "")[:60]] += 1; continue
            v = float(c.get("valorGlobal") or c.get("valorInicial") or 0)
            g = por_no[nid]
            g["n"] += 1; g["valor"] += v
            forn = (c.get("nomeRazaoSocialFornecedor") or "").strip()
            if forn:
                g["fornecedores"][forn] += 1; g["valor_forn"][forn] += v
            g["recentes"].append({"objeto": (c.get("objetoContrato") or "").strip()[:150],
                                  "fornecedor": forn, "cnpj_fornecedor": (c.get("niFornecedor") or "")[:14],
                                  "valor": round(v, 2), "assinado": c.get("dataAssinatura"),
                                  "vigencia_fim": c.get("dataVigenciaFim"),
                                  "id": ident, **({"cipi": c.get("identificadorCipi")} if c.get("identificadorCipi") else {})})
        if n >= (d.get("totalPaginas") or 0): break
        n += 1
        time.sleep(PAUSA)
    print(f"{paginas} páginas · {total_geral} contratos lidos · {total_fed} federais · {len(por_no)} órgãos casados", file=sys.stderr)
    if not total_fed:
        sys.exit("nenhum contrato federal na janela; arquivo anterior mantido")

    # soma à rodada anterior, por órgão, sem duplicar contrato
    ant_org = (anterior.get("orgaos") or {})
    saida_org = {}
    for nid in set(list(por_no)) | set(ant_org):
        novo = por_no.get(nid)
        velho = ant_org.get(nid) or {}
        rec = {x["id"]: x for x in (velho.get("recentes") or [])}
        if novo:
            for x in novo["recentes"]: rec[x["id"]] = x
        recentes = sorted(rec.values(), key=lambda x: x.get("assinado") or "", reverse=True)[:40]
        forn = collections.Counter({f["fornecedor"]: 0 for f in recentes if f.get("fornecedor")})
        valf = collections.Counter()
        for x in rec.values():
            if x.get("fornecedor"):
                forn[x["fornecedor"]] += 1; valf[x["fornecedor"]] += x.get("valor") or 0
        saida_org[nid] = {"nome": (N.get(nid) or {}).get("name"),
                          "contratos": len(rec), "valor": round(sum((x.get("valor") or 0) for x in rec.values()), 2),
                          "fornecedores_top": [{"nome": f, "n": forn[f], "valor": round(valf[f], 2)} for f, _ in valf.most_common(8)],
                          "recentes": recentes}
    saida_org = dict(sorted(saida_org.items(), key=lambda kv: -(kv[1]["valor"] or 0)))

    janelas = list(anterior.get("janelas") or [])
    janelas.append({"de": f"{de[:4]}-{de[4:6]}-{de[6:]}", "ate": f"{ate[:4]}-{ate[4:6]}-{ate[6:]}",
                    "federais": total_fed, "paginas": paginas, "lido_em": TODAY.isoformat()})
    out = {"generated_at": TODAY.isoformat(),
           "fonte": "Portal Nacional de Contratações Públicas (PNCP), API pública de consulta, Lei 14.133/2021",
           "nota": ("Contratos de esfera federal publicados no PNCP. O arquivo acumula: cada rodada acrescenta a janela "
                    "nova ao que já havia por órgão. A API não filtra por esfera e não preenche o campo de emenda "
                    "parlamentar, então não é possível amarrar emenda a contrato por esta fonte. Não é o total de "
                    "contratos da União: é o que foi publicado no PNCP nas janelas já lidas."),
           "janela_atual": {"de": f"{de[:4]}-{de[4:6]}-{de[6:]}", "ate": f"{ate[:4]}-{ate[4:6]}-{ate[6:]}"},
           "janelas": janelas[-30:],
           "resumo": {"orgaos": len(saida_org),
                      "contratos": sum(v["contratos"] for v in saida_org.values()),
                      "valor": round(sum(v["valor"] for v in saida_org.values()), 2),
                      "federais_nesta_janela": total_fed, "lidos_nesta_janela": total_geral,
                      "com_identificador_de_obra": com_cipi, "com_emenda_parlamentar": com_emenda},
           "orgaos": saida_org,
           "cnpj_no": dict(sorted(cnpj_no.items())),
           "nao_casados": [{"orgao": o, "n": q} for o, q in nao_casados.most_common(30)]}
    ant_tot = ((anterior.get("resumo") or {}).get("contratos") or 0)
    if ant_tot and out["resumo"]["contratos"] < ant_tot:
        sys.exit(f"ABORTADO: sairiam {out['resumo']['contratos']} contratos contra {ant_tot} do arquivo atual")
    SAIDA.write_text("# GERADO por etl/contratos.py. Não edite à mão.\n" +
                     yaml.dump(out, allow_unicode=True, sort_keys=False, width=150), encoding="utf-8")
    r = out["resumo"]
    print(f"contratos federais: {r['contratos']} acumulados em {r['orgaos']} órgãos · R$ {r['valor']/1e6:.1f} mi")
    print(f"nesta janela: {total_fed} federais de {total_geral} lidos · com identificador de obra: {com_cipi} · com emenda: {com_emenda}")
    print(f"CNPJ→nó aprendidos: {len(cnpj_no)}")
    for nid, v in list(saida_org.items())[:6]:
        print(f"   R$ {v['valor']/1e6:>8.1f} mi · {v['contratos']:>3} contratos · {(v['nome'] or nid)[:44]}")


if __name__ == "__main__": main()
