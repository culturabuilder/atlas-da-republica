#!/usr/bin/env python3
"""O que mudou no Atlas → data/generated/novidades.yaml

Um projeto que se atualiza todo dia precisa de um lugar dizendo o que mudou, e esse lugar apodrece
se for escrito à mão. Aqui ele sai do histórico do git, que já registra cada mudança em português:
a primeira linha do commit é a manchete, e o primeiro parágrafo é a explicação.

Por que um arquivo acumulado em vez de ler o git na hora de construir o site: o checkout do GitHub
Actions é raso (profundidade 1), então no servidor que publica não existe histórico. Este script roda
onde o histórico existe, acrescenta o que falta e nunca remove o que já estava — assim a área não
perde o passado quando o histórico local for cortado.

O que NÃO entra: os commits automáticos de dado ("dados: atualização automática"), que são 28 dos 181
e não dizem nada ao leitor. O que mudou nesses está no painel de frescor da metodologia.

Uso: .venv/bin/python scripts/novidades.py [--todos]
"""
import argparse, datetime, pathlib, re, subprocess, sys
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
SAIDA = ROOT / "data" / "generated" / "novidades.yaml"
AUTOMATICO = re.compile(r"^(dados: atualização automática|Merge |Revert )")

# área tocada -> rótulo que o leitor entende. Um commit pode ter mais de um.
def areas(arquivos, novos):
    """No máximo dois rótulos, do que mais interessa ao leitor para o que menos: uma lista de quatro
    rótulos em cada item vira ruído e deixa de orientar."""
    r = []
    if any(f.startswith("etl/") and f.endswith(".py") for f in novos): r.append("fonte nova")
    if any(f.startswith("web/") for f in arquivos): r.append("tela")
    if "fonte nova" not in r and any(f.startswith("etl/") for f in arquivos): r.append("coleta")
    if any(f.startswith("data/") and not f.startswith("data/generated/") for f in arquivos): r.append("dado curado")
    if any(re.match(r"scripts/(checar_|eval\.sh)", f) for f in arquivos): r.append("verificação")
    if any(f.startswith("scripts/") for f in arquivos): r.append("método")
    if any(f.startswith(".github/") for f in arquivos): r.append("publicação")
    return (r or ["projeto"])[:2]


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def primeiro_paragrafo(corpo):
    """A explicação para o leitor: o parágrafo de abertura, sem a parte técnica que vem depois."""
    corpo = re.sub(r"\n(Co-Authored-By|Co-authored-by):.*", "", corpo, flags=re.S).strip()
    if not corpo: return ""
    p = corpo.split("\n\n")[0]
    p = re.sub(r"\s*\n\s*", " ", p).strip()
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--todos", action="store_true", help="reler o histórico inteiro, em vez de só o que falta")
    a = ap.parse_args()

    anterior = {}
    if SAIDA.exists():
        try:
            d = yaml.safe_load(SAIDA.read_text(encoding="utf-8")) or {}
            anterior = {x["id"]: x for x in (d.get("novidades") or []) if x.get("id")}
        except Exception as e:
            print("novidades.yaml ilegível, recomeçando:", str(e)[:60], file=sys.stderr)

    try:
        bruto = git("log", "--format=%H%x1f%ad%x1f%ct%x1f%s%x1f%b%x1e", "--date=short", "--no-merges")
    except Exception as e:
        print(f"sem histórico do git aqui ({str(e)[:50]}); mantendo as {len(anterior)} entradas que já existem", file=sys.stderr)
        bruto = ""

    novas = 0
    for reg in bruto.split("\x1e"):
        reg = reg.strip("\n")
        if not reg: continue
        partes = reg.split("\x1f")
        if len(partes) < 4: continue
        sha, data, quando, assunto = partes[0], partes[1], partes[2], partes[3]
        corpo = partes[4] if len(partes) > 4 else ""
        if AUTOMATICO.match(assunto): continue
        curto = sha[:9]
        if curto in anterior and not a.todos: continue
        try:
            arquivos = [l for l in git("show", "--name-only", "--format=", sha).splitlines() if l.strip()]
            novos = [l[2:].strip() for l in git("show", "--name-status", "--format=", sha).splitlines() if l.startswith("A\t")]
        except Exception:
            arquivos, novos = [], []
        anterior[curto] = {"id": curto, "data": data, "ordem": int(quando or 0), "titulo": assunto.strip(),
                           "texto": primeiro_paragrafo(corpo), "areas": areas(arquivos, novos),
                           "arquivos": len(arquivos)}
        novas += 1

    # pela hora do commit, não pelo hash: no mesmo dia a ordem do hash é arbitrária e inverte a história
    lista = sorted(anterior.values(), key=lambda x: (x.get("ordem") or 0, x["data"]), reverse=True)
    por_mes = {}
    for x in lista: por_mes[x["data"][:7]] = por_mes.get(x["data"][:7], 0) + 1
    out = {"generated_at": datetime.date.today().isoformat(),
           "nota": ("O que mudou no Atlas, tirado do histórico do projeto. Os commits automáticos de dado ficam "
                    "fora: o que eles mudam aparece no painel de frescor da metodologia."),
           "total": len(lista), "por_mes": dict(sorted(por_mes.items(), reverse=True)),
           "novidades": lista}
    if len(lista) < len(anterior):
        sys.exit("ABORTADO: a lista encolheria")
    SAIDA.write_text("# GERADO por scripts/novidades.py. Não edite à mão.\n" +
                     yaml.dump(out, allow_unicode=True, sort_keys=False, width=140), encoding="utf-8")
    print(f"novidades: {len(lista)} entradas ({novas} novas nesta passada) · meses: {len(por_mes)}")
    for x in lista[:5]: print(f"   {x['data']} [{', '.join(x['areas'])}] {x['titulo'][:62]}")


if __name__ == "__main__": main()
