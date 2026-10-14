#!/usr/bin/env python3
"""Data de posse e saída pelo cadastro de Pessoas Expostas Politicamente → data/generated/pep.yaml

O Portal da Transparência mantém a lista oficial de PEPs: quem ocupa função de poder no Executivo
federal, com data de início e de fim do exercício. Isso serve a duas coisas que o Atlas precisava:

1. A data de posse. O conector etl/posses.py caça essa data no texto do Diário Oficial, de 1 a 6
   consultas por pessoa mais o download dos atos — e, para 137 ocupantes, não acha nada e gasta 90
   minutos por semana tentando. O PEP responde numa chamada, com a função e o órgão para conferir.
2. Quem já saiu. Se o PEP registra fim de exercício e o Atlas ainda mostra a pessoa como ocupante
   atual, ou a pessoa saiu e não vimos, ou o cargo tem mais de uma cadeira. Vale olhar, não corrigir
   no escuro: o conector só aponta.

A guarda que torna isso seguro: o nome é só o primeiro filtro, e homônimo existe. Medido em
14/10/2026, de 40 ocupantes sem data: 14 com órgão confirmado, 2 recusados por divergência — um
deles um registro de "Deputado Federal / Câmara dos Deputados" para alguém que no Atlas dirige a ANS.
Aceitamos a data só quando o órgão do PEP casa com o órgão do cargo no grafo. Sem isso, a data
entraria errada e ninguém notaria.

Uso: .venv/bin/python etl/pep.py [--todos] [--segundos 600]
"""
import argparse, datetime, json, pathlib, sys, time, urllib.error, urllib.parse, urllib.request
import yaml
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from casar_orgao import casar, indices

ROOT = pathlib.Path(__file__).resolve().parent.parent
SAIDA = ROOT / "data" / "generated" / "pep.yaml"
API = "https://api.portaldatransparencia.gov.br/api-de-dados/peps"
TODAY = datetime.date.today()
PAUSA = 0.25


def chave():
    k = (__import__("os").environ.get("PORTAL_TRANSPARENCIA_KEY") or "").strip()
    if k: return k
    env = ROOT / ".env"
    if env.exists():
        for ln in env.read_text(encoding="utf-8").splitlines():
            if ln.startswith("PORTAL_TRANSPARENCIA_KEY="):
                return ln.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def consultar(nome, k, tentativas=2):
    url = API + "?" + urllib.parse.urlencode({"nome": nome, "pagina": 1})
    for t in range(tentativas):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"chave-api-dados": k}), timeout=45) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (404, 400): return []
            if t == tentativas - 1: return None
        except Exception:
            if t == tentativas - 1: return None
        time.sleep(2)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--todos", action="store_true", help="consultar também quem já tem data de posse, para checar saída")
    ap.add_argument("--segundos", type=int, default=600)
    a = ap.parse_args()
    k = chave()
    if not k: sys.exit("sem PORTAL_TRANSPARENCIA_KEY no ambiente nem no .env")
    graf = ROOT / "build" / "graph.br.json"
    if not graf.exists(): sys.exit(2)
    G = json.load(open(graf, encoding="utf-8")); nodes = G["nodes"]; idx = indices(nodes)

    anterior = {}
    if SAIDA.exists():
        try: anterior = yaml.safe_load(SAIDA.read_text(encoding="utf-8")) or {}
        except Exception: anterior = {}
    ja = dict(anterior.get("posses") or {})
    sem_registro = {str(x): str(y)[:10] for x, y in (anterior.get("sem_registro") or {}).items()}

    alvos = []
    for n in nodes.values():
        if n.get("type") != "dept_head": continue
        for p in (n.get("people") or []):
            if p.get("entry_mode") == "eleito": continue
            if p.get("started_at") and not a.todos: continue
            alvos.append({"pessoa": p["id"], "nome": p["name"], "cargo": n["id"], "cargo_nome": n["name"],
                          "orgao": n.get("head_of"), "tinha_data": bool(p.get("started_at"))})
    # quem já foi respondido e quem já foi procurado sem registro recente não se repete
    corte = (TODAY - datetime.timedelta(days=45)).isoformat()
    antes = len(alvos)
    alvos = [x for x in alvos if x["pessoa"] not in ja and not (sem_registro.get(x["pessoa"], "") > corte)]
    if antes != len(alvos): print(f"{antes - len(alvos)} já resolvidos ou procurados há menos de 45 dias", file=sys.stderr)
    print(f"{len(alvos)} ocupantes a consultar", file=sys.stderr)

    posses = dict(ja); recusados = []; saidas = []; sem = dict(sem_registro)
    t0 = time.time(); consultados = 0
    for x in alvos:
        if time.time() - t0 > a.segundos:
            print(f"orçamento esgotado após {consultados} consultas; o resto fica para a próxima rodada", file=sys.stderr); break
        d = consultar(x["nome"], k)
        consultados += 1
        if d is None: continue                      # erro de rede: não marca como sem registro
        if not d:
            sem[x["pessoa"]] = TODAY.isoformat(); continue
        # Todos os registros daquele órgão, não o primeiro que aparece. Mercadante tem dois no BNDES:
        # um fecha em 27/02/2026 e outro ABRE no mesmo dia — renovação, não saída. Pegar o primeiro
        # fazia o conector anunciar que o presidente do BNDES tinha saído sete meses antes.
        do_orgao = []
        for r in d:
            nid, _ = casar((r.get("nome_orgao") or "").strip(), idx)
            if nid and nid == x["orgao"]: do_orgao.append(r)
        casou = None
        if do_orgao:
            do_orgao.sort(key=lambda r: (r.get("dt_inicio_exercicio") or ""))
            abertos = [r for r in do_orgao if not (r.get("dt_fim_exercicio") or "").strip()]
            casou = abertos[-1] if abertos else do_orgao[-1]
        if not casou:
            # o nome existe no PEP mas em outro órgão: homônimo, ou cargo anterior da mesma pessoa
            r = d[0]
            recusados.append({"pessoa": x["pessoa"], "nome": x["nome"], "cargo": x["cargo"],
                              "pep_orgao": (r.get("nome_orgao") or "").strip(),
                              "pep_funcao": (r.get("descricao_funcao") or "").strip(),
                              "motivo": "órgão do PEP não é o órgão do cargo no Atlas"})
            sem[x["pessoa"]] = TODAY.isoformat()
            continue
        ini = (casou.get("dt_inicio_exercicio") or "").strip()[:10]
        fim = (casou.get("dt_fim_exercicio") or "").strip()[:10]
        # A posse é o começo da permanência ATUAL, não do registro administrativo mais recente: com a
        # renovação do mesmo dia, o registro aberto de Mercadante começa em 2026, mas ele preside o
        # BNDES desde 20/01/2023. Registros encostados (até 31 dias de intervalo) são a mesma passagem;
        # um intervalo maior é saída e volta, e aí a data certa é a da volta.
        if ini:
            cadeia = ini
            for r in reversed(do_orgao):
                i2 = (r.get("dt_inicio_exercicio") or "").strip()[:10]
                f2 = (r.get("dt_fim_exercicio") or "").strip()[:10]
                if not (i2 and f2) or f2 > cadeia: continue
                if (datetime.date.fromisoformat(cadeia) - datetime.date.fromisoformat(f2)).days <= 31:
                    cadeia = i2
            ini = cadeia
        if ini and not x["tinha_data"]:
            posses[x["pessoa"]] = {"inicio": ini, "cargo": x["cargo"],
                                   "funcao_pep": (casou.get("descricao_funcao") or "").strip(),
                                   "orgao_pep": (casou.get("nome_orgao") or "").strip(), "em": TODAY.isoformat()}
        if fim and fim < TODAY.isoformat():
            saidas.append({"pessoa": x["pessoa"], "nome": x["nome"], "cargo": x["cargo"], "cargo_nome": x["cargo_nome"],
                           "fim_exercicio": fim, "funcao_pep": (casou.get("descricao_funcao") or "").strip()})
        time.sleep(PAUSA)

    out = {"generated_at": TODAY.isoformat(),
           "fonte": "Portal da Transparência, cadastro de Pessoas Expostas Politicamente (/api-de-dados/peps)",
           "nota": ("Data de início e fim de exercício de quem ocupa função de poder no Executivo federal. A data só é "
                    "aceita quando o órgão do registro no PEP casa com o órgão do cargo no Atlas: o nome sozinho não "
                    "basta, porque homônimo existe e a data entraria no cargo errado. O que não casa fica em "
                    "'recusados', para conferência humana, e não é usado."),
           "resumo": {"consultados_nesta_rodada": consultados, "posses_conhecidas": len(posses),
                      "novas_nesta_rodada": len(posses) - len(ja), "recusados": len(recusados),
                      "ja_sairam_segundo_o_pep": len(saidas), "sem_registro": len(sem)},
           "posses": dict(sorted(posses.items())),
           "ja_sairam": sorted(saidas, key=lambda x: x["fim_exercicio"], reverse=True),
           "recusados": recusados,
           "sem_registro": dict(sorted(sem.items()))}
    if len(posses) < len(ja):
        sys.exit(f"ABORTADO: sairiam {len(posses)} posses contra {len(ja)} do arquivo atual")
    SAIDA.write_text("# GERADO por etl/pep.py. Não edite à mão.\n" +
                     yaml.dump(out, allow_unicode=True, sort_keys=False, width=140), encoding="utf-8")
    r = out["resumo"]
    print(f"PEP: {r['consultados_nesta_rodada']} consultas · {r['novas_nesta_rodada']} datas novas · "
          f"{r['posses_conhecidas']} conhecidas · {r['recusados']} recusados por órgão divergente · "
          f"{r['ja_sairam_segundo_o_pep']} com fim de exercício já passado")
    for s in out["ja_sairam"][:5]: print(f"   saiu em {s['fim_exercicio']}: {s['nome'][:30]} — {s['cargo_nome'][:40]}")
    for s in recusados[:3]: print(f"   recusado: {s['nome'][:26]} · PEP diz {s['pep_orgao'][:26]} / {s['pep_funcao'][:18]}")


if __name__ == "__main__": main()
