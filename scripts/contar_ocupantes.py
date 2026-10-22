#!/usr/bin/env python3
"""Conta cargos com ocupante num arquivo gerado (YAML ou JSON).

Existe por causa de 20/10/2026: o segundo escalão perdeu 29 cargos com ocupante — páginas oficiais que não
respondiam viravam cargo vago — e nenhuma guarda apitou, porque o número de POSIÇÕES não mudou (201 nos dois
dias) e o arquivo quase não encolheu em bytes. scripts/update.sh compara esta contagem com a do commit
anterior e devolve o arquivo quando a queda passa de 10%.

Uso:
  scripts/contar_ocupantes.py data/generated/segundo-escalao.yaml
  scripts/contar_ocupantes.py --git HEAD:data/generated/segundo-escalao.yaml
Imprime um número; sem posições no arquivo, imprime -1 (nada a comparar).
"""
import sys, json, subprocess

def conta(texto, nome):
    if nome.endswith(".json"):
        d = json.loads(texto)
    else:
        import yaml
        d = yaml.safe_load(texto)
    if not isinstance(d, dict): return -1
    pos = d.get("positions")
    if not isinstance(pos, list) or not pos: return -1
    return sum(1 for p in pos if isinstance(p, dict) and p.get("people"))

def main():
    a = sys.argv[1:]
    try:
        if a[:1] == ["--git"]:
            r = subprocess.run(["git", "show", a[1]], capture_output=True, text=True)
            if r.returncode != 0: print(-1); return
            print(conta(r.stdout, a[1]))
        else:
            print(conta(open(a[0], encoding="utf-8").read(), a[0]))
    except Exception:
        print(-1)

if __name__ == "__main__": main()
