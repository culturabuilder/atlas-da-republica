#!/usr/bin/env python3
"""Conector em que uma fonte de apoio pode derrubar a saída inteira.

Em 03/10/2026 a série de juros do Banco Central não respondeu e levou com ela o conector da
arrecadação — a receita do Portal da Transparência e os índices do IBGE tinham vindo normais, mas o
número que abre a home ficou um dia atrás. O defeito não é a fonte cair: é uma fonte periférica,
de outra instituição, poder destruir uma saída que já estava pronta.

Esta checagem acha o padrão por análise do código, não a olho: função que faz rede sem try nenhum,
chamada crua dentro do main. Quem está em ABORTAR_E_CORRETO foi examinado e abortar é o certo ali —
é a fonte única do conector, e sem ela não existe saída nenhuma para gravar.

Uso: .venv/bin/python scripts/checar_fontes.py     (sai 1 se aparecer caso novo)
"""
import ast, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# conector -> por que abortar sem guarda é aceitável ali
ABORTAR_E_CORRETO = {
    "emendas.py": "o zip de emendas da CGU é a fonte única; sem ele não há o que gravar",
    "gabinetes.py": "a folha da Câmara é a fonte única",
    "parlamentares.py": "Câmara e Senado são as duas fontes únicas da lista de parlamentares",
    "renuncias.py": "o demonstrativo de renúncias da Receita é a fonte única",
    "segundo_escalao.py": "o SIORG completo (227 MB) é a fonte única",
    "siorg.py": "o SIORG é a fonte única",
    "viagens.py": "o zip de viagens do Portal da Transparência é a fonte única",
}

def funcoes_sem_guarda(tree):
    """Funções que chamam urlopen fora de qualquer try, e quem as chama cruamente."""
    corpos = {n.name: n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    def conta(nd, alvos):
        """(nuas, guardadas) de chamadas a `alvos` (ou urlopen, se alvos é None) no corpo de nd."""
        r = [0, 0]
        class W(ast.NodeVisitor):
            def __init__(self): self.t = 0
            def visit_Try(self, n):
                self.t += 1
                for c in n.body: self.visit(c)
                self.t -= 1
                for g in n.handlers + n.orelse + n.finalbody: self.visit(g)
            def visit_Call(self, n):
                f = n.func
                bate = ((isinstance(f, ast.Attribute) and f.attr == "urlopen") or (isinstance(f, ast.Name) and f.id == "urlopen")) if alvos is None \
                       else (isinstance(f, ast.Name) and f.id in alvos)
                if bate: r[1 if self.t else 0] += 1
                self.generic_visit(n)
        w = W()
        for c in nd.body: w.visit(c)
        return r
    perigosas = {nm for nm, nd in corpos.items() if conta(nd, None)[0]}
    for _ in range(4):
        novas = {nm for nm, nd in corpos.items() if nm not in perigosas and conta(nd, perigosas)[0]}
        if not novas: break
        perigosas |= novas
    return corpos, perigosas

def main():
    achados = {}
    for f in sorted((ROOT / "etl").glob("*.py")):
        corpos, perigosas = funcoes_sem_guarda(ast.parse(f.read_text(encoding="utf-8")))
        m = corpos.get("main")
        if not m: continue
        fora = []
        class M(ast.NodeVisitor):
            def __init__(self): self.t = 0
            def visit_Try(self, n):
                self.t += 1
                for c in n.body: self.visit(c)
                self.t -= 1
                for g in n.handlers + n.orelse + n.finalbody: self.visit(g)
            def visit_Call(self, n):
                fn = n.func
                if self.t == 0:
                    if isinstance(fn, ast.Name) and fn.id in perigosas and fn.id != "main": fora.append((n.lineno, fn.id))
                    elif isinstance(fn, ast.Attribute) and fn.attr == "urlopen": fora.append((n.lineno, "urlopen"))
                self.generic_visit(n)
        mm = M()
        for c in m.body: mm.visit(c)
        if fora: achados[f.name] = fora

    novos = {k: v for k, v in achados.items() if k not in ABORTAR_E_CORRETO}
    for nome, fora in sorted(achados.items()):
        alvos = ", ".join(sorted({a for _, a in fora}))
        linhas = ", ".join(str(l) for l, _ in fora)
        if nome in ABORTAR_E_CORRETO:
            print(f"   ok   {nome}: {alvos} (linha {linhas}) — {ABORTAR_E_CORRETO[nome]}")
        else:
            print(f"   ERRO {nome}: {alvos} (linha {linhas}) sem guarda no main")
            print(f"        se a fonte for de apoio, faça o conector seguir sem ela; se for única, declare em ABORTAR_E_CORRETO")
    if not novos:
        print(f"   ok   nenhuma fonte de apoio pode derrubar conector ({len(achados)} casos declarados)")
    # conector que saiu da lista também é notícia: a declaração ficou obsoleta
    sobrando = [k for k in ABORTAR_E_CORRETO if k not in achados]
    for k in sobrando: print(f"   !    {k} está em ABORTAR_E_CORRETO mas não tem mais chamada crua; pode sair da lista")
    return 1 if novos else 0

if __name__ == "__main__": sys.exit(main())
