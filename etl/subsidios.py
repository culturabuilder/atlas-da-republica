#!/usr/bin/env python3
"""Quanto cada CARGO do grafo paga, segundo a lei → data/generated/subsidios.yaml.

Lê o curadoria em data/subsidios.yaml (famílias de cargos, subsídio mensal bruto, norma e benefícios),
casa cada família com os ids reais de build/graph.br.json (por id exato e por padrão glob, ex.: "*-reitor";
opcionalmente refinado por nome_padrao, regex sobre o nome do cargo) e grava um mapa cargo_id → subsídio.

É a resposta legal, não a folha: vale para todos os ocupantes do cargo, inclusive os que não aparecem na
folha nominal do Portal da Transparência (etl/remuneracao.py). Valor sempre BRUTO MENSAL, com a norma ao lado.
Benefícios indenizatórios nunca são somados ao subsídio.

Uso: .venv/bin/python etl/subsidios.py [--amostra] [--grafo build/graph.br.json]
  --amostra  não escreve nada; só valida e imprime uma amostra por família.
"""
import argparse
import datetime
import fnmatch
import json
import pathlib
import re
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
CURADO = ROOT / "data" / "subsidios.yaml"
SAIDA = ROOT / "data" / "generated" / "subsidios.yaml"
GRAFO = ROOT / "build" / "graph.br.json"
TIPOS = ("dept_head", "elected")
# Nós 'elected' que são instituições, não cargos: os cargos correspondentes são dept_head
# (br-deputado-federal, br-senador, br-presidente-da-camara-dos-deputados, br-presidente-do-senado-federal).
NAO_SAO_CARGOS = ("br-congresso-nacional", "br-camara-dos-deputados", "br-senado-federal")
CAMPOS_BENEFICIO = ("nome", "valor_mensal_ou_teto", "natureza", "papel", "periodicidade", "tipo_valor", "norma", "norma_url", "note")
NATUREZAS = ("indenizatoria", "remuneratoria")
# `papel` diz para onde o dinheiro vai e é o que o cálculo de custo usa; `tipo_valor` diz se o número
# publicado é valor fixo, limite máximo ou inexistente. Ver o cabeçalho de data/subsidios.yaml.
PAPEIS = ("componente_do_salario", "beneficio", "equipe", "custeio", "eventual")
PERIODICIDADES = ("mensal", "anual", "por_mandato", "eventual")
TIPOS_VALOR = ("fixo", "teto", "sem_valor")
CAMPOS_FAMILIA = ("familia", "cargos", "orgao_subtype", "nome_padrao", "excluir", "subsidio_mensal_bruto", "moeda",
                  "teto", "vigencia_desde", "norma", "norma_url", "checked_at", "observacao", "beneficios")


def carregar_cargos(caminho):
    """Todos os cargos do grafo: dept_head e cargos eletivos. Devolve {id: {node, subtype do órgão}}."""
    g = json.load(open(caminho, encoding="utf-8"))
    nodes = g["nodes"]
    out = {}
    for n in nodes.values():
        if n.get("type") not in TIPOS or n["id"] in NAO_SAO_CARGOS:
            continue
        orgao = nodes.get(n.get("head_of") or "") or {}
        out[n["id"]] = {"name": n["name"], "type": n["type"], "orgao": orgao.get("id"), "orgao_subtype": orgao.get("subtype")}
    return out


def casar(familia, cargos):
    """Ids do grafo que a família cobre.

    `cargos` do curado são ids exatos ou globs (ex.: "*-reitor"); `orgao_subtype` casa todo cargo que chefia
    um órgão daquele tipo (ex.: sociedade_economia_mista); `nome_padrao` (regex sobre o nome do cargo) refina;
    `excluir` tira ids do resultado.
    """
    padroes = familia.get("cargos") or []
    nomes = [re.compile(p) for p in (familia.get("nome_padrao") or [])]
    achados, erros = [], []
    for st in familia.get("orgao_subtype") or []:
        hit = sorted(i for i, c in cargos.items() if c["orgao_subtype"] == st)
        if not hit:
            erros.append(f"orgao_subtype sem nenhum cargo no grafo: {st!r}")
        achados += hit
    for p in padroes:
        if "*" in p or "?" in p:
            hit = sorted(i for i in cargos if fnmatch.fnmatchcase(i, p))
            if not hit:
                erros.append(f"padrão sem nenhum cargo no grafo: {p!r}")
            achados += hit
        else:
            if p not in cargos:
                erros.append(f"id inexistente no grafo: {p!r}")
            else:
                achados.append(p)
    if nomes:
        achados = [i for i in achados if any(rx.search(cargos[i]["name"]) for rx in nomes)]
    excluir = set(familia.get("excluir") or [])
    for e in excluir:
        if e not in cargos:
            erros.append(f"id em 'excluir' inexistente no grafo: {e!r}")
    achados = [i for i in achados if i not in excluir]
    return sorted(dict.fromkeys(achados)), erros


def validar_familia(f, i):
    """Erros editoriais do curado: sem norma não há valor; benefício sem natureza não entra."""
    erros = []
    quem = f.get("familia") or f"#{i}"
    if not f.get("familia"):
        erros.append(f"família #{i} sem chave 'familia'")
    for k in f:
        if k not in CAMPOS_FAMILIA:
            erros.append(f"{quem}: campo desconhecido {k!r}")
    if not f.get("cargos") and not f.get("orgao_subtype"):
        erros.append(f"{quem}: sem 'cargos' nem 'orgao_subtype'")
    if f.get("subsidio_mensal_bruto") is not None:
        if not f.get("norma") or not f.get("norma_url"):
            erros.append(f"{quem}: tem valor mas não tem norma/norma_url")
        if not f.get("vigencia_desde"):
            erros.append(f"{quem}: tem valor mas não tem vigencia_desde")
        if not isinstance(f["subsidio_mensal_bruto"], (int, float)):
            erros.append(f"{quem}: subsidio_mensal_bruto não é número")
    elif not f.get("observacao"):
        erros.append(f"{quem}: sem valor e sem observacao explicando por quê")
    if f.get("moeda", "BRL") != "BRL":
        erros.append(f"{quem}: moeda diferente de BRL")
    if not f.get("checked_at"):
        erros.append(f"{quem}: sem checked_at")
    for b in f.get("beneficios") or []:
        nome = b.get("nome") or "(sem nome)"
        if b.get("natureza") not in NATUREZAS:
            erros.append(f"{quem}/{nome}: natureza deve ser {' ou '.join(NATUREZAS)}")
        if b.get("papel") not in PAPEIS:
            erros.append(f"{quem}/{nome}: papel deve ser um de {', '.join(PAPEIS)}")
        if b.get("periodicidade") not in PERIODICIDADES:
            erros.append(f"{quem}/{nome}: periodicidade deve ser uma de {', '.join(PERIODICIDADES)}")
        if b.get("tipo_valor") not in TIPOS_VALOR:
            erros.append(f"{quem}/{nome}: tipo_valor deve ser um de {', '.join(TIPOS_VALOR)}")
        if (b.get("tipo_valor") == "sem_valor") != (b.get("valor_mensal_ou_teto") is None):
            erros.append(f"{quem}/{nome}: tipo_valor 'sem_valor' e valor_mensal_ou_teto têm de concordar")
        if not b.get("norma"):
            erros.append(f"{quem}/{nome}: benefício sem norma")
        for k in b:
            if k not in CAMPOS_BENEFICIO:
                erros.append(f"{quem}/{nome}: campo desconhecido {k!r}")
    return erros


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--amostra", action="store_true", help="valida e imprime uma amostra; não escreve arquivo")
    ap.add_argument("--grafo", default=str(GRAFO))
    a = ap.parse_args()

    if not CURADO.exists():
        sys.exit(f"subsídios: {CURADO} não existe")
    curado = yaml.safe_load(CURADO.read_text(encoding="utf-8")) or {}
    familias = curado.get("familias") or []
    if not familias:
        sys.exit("subsídios: data/subsidios.yaml sem 'familias'")
    cargos = carregar_cargos(a.grafo)
    print(f"grafo: {len(cargos)} cargos (dept_head + eletivos); curado: {len(familias)} famílias")

    erros, out, dono = [], {}, {}
    hoje = datetime.date.today().isoformat()
    for i, f in enumerate(familias, 1):
        erros += validar_familia(f, i)
        ids, e = casar(f, cargos)
        erros += [f"{f.get('familia', i)}: {x}" for x in e]
        if not ids:
            erros.append(f"{f.get('familia', i)}: nenhum cargo do grafo casou com esta família")
        for cid in ids:
            if cid in dono:
                erros.append(f"cargo {cid} casou com duas famílias: {dono[cid]!r} e {f.get('familia')!r}")
                continue
            dono[cid] = f.get("familia")
            out[cid] = {
                "nome": cargos[cid]["name"],
                "subsidio_mensal_bruto": f.get("subsidio_mensal_bruto"),
                "moeda": "BRL",
                "vigencia_desde": f.get("vigencia_desde"),
                "norma": f.get("norma"),
                "norma_url": f.get("norma_url"),
                "beneficios": [dict(b) for b in (f.get("beneficios") or [])],
                "familia": f.get("familia"),
                "checked_at": f.get("checked_at"),
            }
            if f.get("observacao"):
                out[cid]["observacao"] = f["observacao"]
            if f.get("teto"):
                out[cid]["teto"] = True

    if erros:
        for x in erros:
            print("  ERRO:", x, file=sys.stderr)
        sys.exit(f"subsídios: {len(erros)} erro(s) no curado; nada foi escrito")

    sem_valor = [c for c, v in out.items() if v["subsidio_mensal_bruto"] is None]
    sem_familia = sorted(set(cargos) - set(out))
    dados = {
        "generated_at": hoje,
        "cargos": dict(sorted(out.items())),
        "resumo": {
            "familias": len(familias),
            "cargos_cobertos": len(out),
            "cargos_sem_valor": len(sem_valor),
            "cargos_no_grafo": len(cargos),
            "cargos_sem_familia": len(sem_familia),
        },
    }

    print(f"cobertos {len(out)}/{len(cargos)} cargos; com valor {len(out) - len(sem_valor)}; sem valor {len(sem_valor)}; sem família {len(sem_familia)}")
    for f in familias:
        ids, _ = casar(f, cargos)
        ids = [i for i in ids if dono.get(i) == f.get("familia")]
        v = f.get("subsidio_mensal_bruto")
        print(f"  {f.get('familia'):<42} {len(ids):>4} cargos  {('R$ %0.2f' % v) if v is not None else 'sem valor':>16}  ex.: {ids[0] if ids else '-'}")
    if sem_familia:
        print(f"  sem família ({len(sem_familia)}): " + ", ".join(sem_familia[:8]) + (" …" if len(sem_familia) > 8 else ""))

    if a.amostra:
        print("\n--amostra: nada foi escrito. Amostra:")
        for f in familias:
            ids, _ = casar(f, cargos)
            ids = [i for i in ids if dono.get(i) == f.get("familia")]
            if not ids:
                continue
            cid = ids[0]
            v = out[cid]
            print(f"\n  {cid}  ({v['nome']})")
            print(f"    subsídio bruto mensal: {('R$ %0.2f' % v['subsidio_mensal_bruto']) if v['subsidio_mensal_bruto'] is not None else 'não fixado em norma localizada'}"
                  + (" (teto, não valor fixo)" if v.get("teto") else ""))
            print(f"    norma: {v['norma']}")
            for b in v["beneficios"][:3]:
                print(f"    benefício [{b.get('natureza')}] {b.get('nome')}: {b.get('valor_mensal_ou_teto')} — {b.get('norma')}")
        return

    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(
        "# GERADO por etl/subsidios.py. Não edite à mão.\n"
        + yaml.dump(dados, allow_unicode=True, sort_keys=False, width=140),
        encoding="utf-8",
    )
    print(f"escrito {SAIDA.relative_to(ROOT)} ({SAIDA.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
