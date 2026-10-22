#!/usr/bin/env python3
"""Conta registros com nome de pessoa num arquivo gerado (YAML ou JSON).

Existe por causa de 20/10/2026: o segundo escalão perdeu 29 cargos com ocupante — páginas oficiais que não
respondiam viravam cargo vago — e nenhuma guarda apitou, porque o número de POSIÇÕES não mudou (201 nos dois
dias) e o arquivo quase não encolheu em bytes. scripts/update.sh compara esta contagem com a do commit
anterior e devolve o arquivo quando a queda passa de 10%.

Os conectores guardam ocupante em formatos diferentes, então a contagem cobre os quatro que existem hoje:
  positions: lista de cargos (dirigentes, segundo escalão)    -> cargos com people
  positions: dicionário cargo -> ocupantes (ocupantes do DOU)  -> cargos com ocupante
  posses:    dicionário cargo -> posse (posses)                -> posses com pessoa
Só estas duas chaves entram, e de propósito: elas significam "cargo e quem o ocupa". Chaves soltas como
`people` aparecem em conector de outra natureza (equipe de gabinete, candidatura, comissão), onde a contagem
oscila por motivo legítimo — guardar por ela devolveria arquivo bom e congelaria dado, que é justamente o
estrago que esta guarda existe para evitar.

Uso:
  scripts/contar_ocupantes.py data/generated/segundo-escalao.yaml
  scripts/contar_ocupantes.py --git HEAD:data/generated/segundo-escalao.yaml
Imprime um número; sem nada contável no arquivo, imprime -1 (nada a comparar).
"""
import sys, json, subprocess

def _tem_gente(v):
    # `people` presente manda, mesmo vazio: é a diferença entre cargo ocupado e cargo vago. Sem essa chave,
    # vale o nome da pessoa — nunca v["name"], que nos cargos é o nome do CARGO e contaria vago como ocupado.
    if isinstance(v, dict):
        if "people" in v: return bool(v["people"])
        return bool(v.get("pessoa_nome") or v.get("pessoa_id"))
    return bool(v)

def conta(texto, nome):
    d = json.loads(texto) if nome.endswith(".json") else __import__("yaml").safe_load(texto)
    if not isinstance(d, dict): return -1
    total = achou = 0
    for chave in ("positions", "posses"):
        v = d.get(chave)
        if isinstance(v, list) and v:
            achou = 1; total += sum(1 for x in v if _tem_gente(x))
        elif isinstance(v, dict) and v:
            achou = 1; total += sum(1 for x in v.values() if _tem_gente(x))
    return total if achou and total else -1

def main():
    a = sys.argv[1:]
    try:
        if a[:1] == ["--git"]:
            r = subprocess.run(["git", "show", a[1]], capture_output=True, text=True)
            print(-1 if r.returncode != 0 else conta(r.stdout, a[1]))
        else:
            print(conta(open(a[0], encoding="utf-8").read(), a[0]))
    except Exception:
        print(-1)

if __name__ == "__main__": main()
