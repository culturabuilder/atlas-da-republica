#!/usr/bin/env python3
"""Confere que todo pacote externo importado por etl/ e scripts/ está em requirements.txt.

O conector de renúncias falhou em silêncio por semanas no GitHub Actions porque importa openpyxl
e o job instalava só três pacotes. Erro de importação sai em zero segundo e some no meio do log.
Esta checagem roda antes de tudo, custa milissegundos e falha alto.

Uso: .venv/bin/python scripts/checar_dependencias.py
"""
import ast, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
# nome no requirements → nome do módulo importado
APELIDO = {"pyyaml": "yaml", "pillow": "PIL", "beautifulsoup4": "bs4", "python-dateutil": "dateutil"}


def externos():
    padrao = set(sys.stdlib_module_names)
    locais = {p.stem for p in (ROOT / "etl").glob("*.py")} | {p.stem for p in (ROOT / "scripts").glob("*.py")}
    achados = {}
    for f in sorted(list((ROOT / "etl").glob("*.py")) + list((ROOT / "scripts").glob("*.py"))):
        try:
            arvore = ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError as e:
            print(f"erro de sintaxe em {f.name}: {e}", file=sys.stderr); sys.exit(2)
        for n in ast.walk(arvore):
            if isinstance(n, ast.Import):
                for a in n.names: achados.setdefault(a.name.split(".")[0], set()).add(f.name)
            elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
                achados.setdefault(n.module.split(".")[0], set()).add(f.name)
    return {m: v for m, v in achados.items() if m not in padrao and m not in locais}


def declarados():
    p = ROOT / "requirements.txt"
    if not p.exists(): return set()
    nomes = set()
    for ln in p.read_text(encoding="utf-8").splitlines():
        ln = ln.split("#")[0].strip()
        if not ln: continue
        base = ln.split("==")[0].split(">=")[0].split("[")[0].strip().lower()
        nomes.add(APELIDO.get(base, base))
    return nomes


def main():
    usados, tenho = externos(), declarados()
    falta = {m: v for m, v in usados.items() if m not in tenho}
    sem_instalar = []
    for m in usados:
        try: __import__(m)
        except ImportError: sem_instalar.append(m)
    if falta:
        for m, v in sorted(falta.items()):
            print(f"FALTA em requirements.txt: {m} (importado por {', '.join(sorted(v))})", file=sys.stderr)
    if sem_instalar:
        print(f"NÃO INSTALADO neste ambiente: {', '.join(sorted(sem_instalar))}", file=sys.stderr)
    if falta or sem_instalar: sys.exit(1)
    print(f"   dependências: {len(usados)} pacotes externos, todos declarados e instalados")


if __name__ == "__main__":
    main()
