#!/usr/bin/env python3
"""Casos de casamento de órgão que já foram conferidos à mão, e precisam continuar valendo.

Cada linha aqui saiu de uma conferência real contra os dados: nome que uma fonte escreve de um jeito
e que tem de chegar ao nó certo, ou nome que NÃO pode casar com nenhum. A segunda lista é a que
protege o projeto: linkar errado é pior do que não linkar — uma demissão pendurada no ministério de
outra pessoa, ou um deputado aparecendo como relator na comissão errada, derruba a confiança que o
Atlas inteiro depende de ter.

Uso: .venv/bin/python scripts/checar_casamento.py     (sai 1 se algum caso regredir)
"""
import json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "etl"))
import casar_orgao as C

DEVE_CASAR = [
    ("MGI - MIN GESTAO E INOV EM SERV PUBLICOS", "br-ministerio-da-gestao", "sigla antes do travessão"),
    ("MIN.DA GEST.E DA INOVACAO EM SERVICOS PUBLICO", "br-ministerio-da-gestao", "abreviação do SIAPE"),
    ("COMANDO DO EXERCITO", "br-exercito-brasileiro", "nome administrativo da mesma força"),
    ("DEPARTAMENTO DE POLÍCIA FEDERAL", "br-policia-federal", "prefixo administrativo"),
    ("DEPARTAMENTO NACIONAL DE INFRA-ESTRUTURA DE TRANSPORTES", "br-dnit", "grafia com hífen, anterior a 2009"),
    ("FUNDAÇÃO NACIONAL DO ÍNDIO", "br-funai", "nome anterior a 2023"),
    ("SUPERINTENDÊNCIA REGIONAL DE POLÍCIA FEDERAL EM SÃO PAULO", "br-policia-federal", "unidade regional sob o órgão nacional"),
    ("BANCO DO BRASIL SA", "br-banco-do-brasil", "forma jurídica no fim do nome"),
    ("INSTITUTO NACIONAL DO SEGURO SOCIAL", "br-inss", "nome por extenso"),
    ("Ministério da Agricultura, Pecuária e Abastecimento", "br-ministerio-da-agricultura-e-pecuaria", "nome anterior do ministério"),
    ("Empresa Brasil de Comunicação S.A. - EBC", "br-empresa-brasil-de-comunicacao", "sigla depois do travessão"),
    ("ICMBio", "br-icmbio", "sigla sozinha, caixa mista"),
]
NAO_PODE_CASAR = [
    ("MINISTÉRIO DA ECONOMIA", "extinto em 2022 e dividido em quatro: não é o ministério de ninguém hoje"),
    ("MINISTÉRIO DO TRABALHO E PREVIDÊNCIA", "extinto em 2023 e dividido em dois"),
    ("MINISTÉRIO DA INFRAESTRUTURA", "dividido em Transportes e Portos e Aeroportos"),
    ("JUSTICA FEDERAL", "designa o conjunto, não um órgão"),
    ("SEÇÃO DE BENEFÍCIOS", "unidade interna, sem o órgão no nome"),
    ("DELEGACIA 02", "unidade interna, sem o órgão no nome"),
    ("COMANDO DA AERONAUTICA", "a Força Aérea não é nó do Atlas; casar com outra força seria errado"),
    ("ITAU UNIBANCO S.A.", "empresa privada"),
    ("MATTOS FILHO, VEIGA FILHO, MARREY JR. E QUIROGA ADVOGADOS", "escritório de advocacia"),
]

def main():
    g = ROOT / "build" / "graph.br.json"
    if not g.exists():
        print("   !    build/graph.br.json não existe; rode scripts/build_graph.py antes"); return 0
    idx = C.indices(json.load(open(g, encoding="utf-8"))["nodes"])
    ruim = 0
    for nome, esperado, por_que in DEVE_CASAR:
        nid, como = C.casar(nome, idx)
        if nid != esperado:
            print(f"   ERRO {nome[:52]!r} deu {nid or '—'} [{como}], esperado {esperado} ({por_que})"); ruim += 1
    for nome, por_que in NAO_PODE_CASAR:
        nid, _ = C.casar(nome, idx)
        if nid is not None:
            print(f"   ERRO {nome[:52]!r} casou com {nid}, e não devia: {por_que}"); ruim += 1
    if not ruim:
        print(f"   ok   casamento de órgão: {len(DEVE_CASAR)} casos certos e {len(NAO_PODE_CASAR)} recusas, todos mantidos")
    return 1 if ruim else 0

if __name__ == "__main__": sys.exit(main())
