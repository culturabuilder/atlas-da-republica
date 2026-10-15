#!/usr/bin/env python3
"""Arquivo gerado que parou de ser atualizado — inclusive o que ninguém está olhando.

O painel de frescor do site usa o mapa BLOCOS de scripts/build_graph.py, que é escrito à mão: arquivo
que ninguém lembrou de pôr lá envelhece em silêncio. Foi o caso de posses.yaml, que ficou 15 dias com
o dado de 28/09/2026 enquanto o conector estourava o tempo toda segunda-feira — e nem o painel nem o
eval diziam nada, porque um olhava só o mapa e o outro só o status da última rodada.

Esta checagem varre data/generated inteiro e cobra o generated_at de cada arquivo. O que legitimamente
não tem data está em SEM_DATA, com o motivo.

Uso: .venv/bin/python scripts/checar_frescor.py     (sai 1 se algo passou do prazo)
"""
import datetime, json, pathlib, sys
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
DIR = ROOT / "data" / "generated"

# arquivo -> por que não tem generated_at
SEM_DATA = {
    "historico-qids.yaml": "mapa de QIDs do Wikidata, cresce por acréscimo",
    "nascimentos.yaml": "mapa de datas de nascimento, cresce por acréscimo",
    "ocupantes.yaml": "mapa de ocupantes consolidado de outros arquivos",
    "ocupantes-sabatinas.yaml": "mapa derivado das sabatinas",
    "wikidata-map.yaml": "mapa de casamento com o Wikidata",
    "wikipedia.yaml": "mapa de verbetes",
    "tenures.json": "série de mandatos, derivada do grafo",
}
# prazo em dias: o que muda todo dia, o que é semanal, e o que é arquivo fechado de eleição
PRAZO = {
    "posses.yaml": 9, "ocupantes-dou.yaml": 9, "segundo-escalao.yaml": 9,
    "dirigentes.yaml": 9, "agendas.yaml": 9,
    "candidaturas.yaml": None, "doadores-2022.yaml": None, "votos-2022.yaml": None,
    "patrimonio.yaml": None,          # depende de zip do TSE baixado à mão
    "resumos.yaml": 30,               # só muda quando há item novo para resumir
    "portal-cce.yaml": 30, "sabatinas.yaml": 20, "subsidios.yaml": 30,
    "teto.yaml": 40, "remuneracao.yaml": 40,   # folha mensal
    "sancoes.yaml": 4, "recebidos.yaml": 4, "contratos.yaml": 4, "pep.yaml": 9, "falabr.yaml": 9,
    "novidades.yaml": 45,   # só muda quando há mudança no projeto; semana sem mexer é normal
}
PADRAO = 3

def main():
    hoje = datetime.date.today()
    ruim = avisos = 0
    for p in sorted(DIR.glob("*")):
        if p.suffix not in (".yaml", ".json") or p.name.startswith("_"): continue
        if p.name in SEM_DATA: continue
        try:
            d = json.load(open(p, encoding="utf-8")) if p.suffix == ".json" else yaml.safe_load(p.read_text(encoding="utf-8"))
            g = str((d or {}).get("generated_at") or (d or {}).get("updated_at") or "")[:10]
        except Exception as e:
            print(f"   ERRO {p.name}: ilegível ({str(e)[:50]})"); ruim += 1; continue
        if not g:
            # Três conectores (sabatinas, comissoes, parlamentares) passaram a gravar a data em
            # 13/10/2026; até cada um rodar uma vez, o arquivo antigo ainda vem sem ela. O build já
            # não inventa a data pelo mtime, então o site diz "sem data registrada" enquanto isso.
            print(f"   ERRO {p.name}: sem data dentro do arquivo — o conector precisa gravar generated_at"); ruim += 1; continue
        try: dias = (hoje - datetime.date.fromisoformat(g)).days
        except ValueError:
            print(f"   ERRO {p.name}: generated_at ilegível ({g!r})"); ruim += 1; continue
        prazo = PRAZO.get(p.name, PADRAO)
        if prazo is None:
            if dias > 400: print(f"   !    {p.name}: {dias} dias (fonte fechada; só muda em ano de eleição ou por arquivo à mão)"); avisos += 1
            continue
        if dias > prazo:
            print(f"   ERRO {p.name}: {dias} dias sem atualizar (prazo {prazo}), gerado em {g}"); ruim += 1
    if not ruim: print(f"   ok   todo arquivo gerado dentro do prazo{f' ({avisos} aviso(s) de fonte fechada)' if avisos else ''}")
    return 1 if ruim else 0

if __name__ == "__main__": sys.exit(main())
