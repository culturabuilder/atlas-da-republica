#!/usr/bin/env python3
"""Quem o governo federal recebeu de fora → data/generated/recebidos.yaml.

A agenda pública (e-Agendas/CGU) diz com quem cada autoridade se reuniu, mas ninguém no site
consegue olhar isso somado: cada ficha mostra a agenda de uma pessoa. Somando as 456 agendas,
a primeira surpresa é que a maior parte do governo se reúne com o próprio governo — Casa Civil,
Presidência, Fazenda. O que interessa é a minoria que vem de fora: escritório de advocacia,
banco, empresa, associação setorial.

Como classificamos, do mais confiável para o menos:

  1. Junção com o nosso próprio grafo. Os 1.366 nós do Atlas SÃO os órgãos federais, com sigla e
     apelido curados. Se o nome da entidade casa com um nó, é órgão federal — não é chute, é o
     nosso dado. Cobre 85% dos encontros. O casamento é só determinístico: nome igual, núcleo sem
     artigo, sigla antes ou depois do travessão, forma jurídica removida, ou prefixo único. Sigla
     que aponta para mais de um nó não casa com nenhum, para nunca linkar errado.
  2. Marca jurídica no nome, para o que não casou: "ADVOGADOS" é escritório, "LTDA"/"S.A." é
     empresa, "ASSOCIAÇÃO"/"FEDERAÇÃO"/"SINDICATO" é representação setorial.
  3. Eikos, para o resto. Quatro perguntas binárias — federal, estadual ou municipal, estrangeira,
     interesse privado — porque é em pergunta binária factual que ele acerta; taxonomia de
     julgamento é onde ele erra. Só vale acima de 0,80 de confiança e se as respostas não se
     contradisserem. O veredito fica guardado no próprio arquivo e nunca é pedido duas vezes.

O que fica fora de qualquer um dos três sai como "não classificado" e NÃO é apresentado como
privado. É melhor dizer "não sei de 300" do que chamar uma estatal estadual de lobista.

Limite declarado: empresa controlada por estado ou município que o Atlas ainda não tem como nó
cai em "empresa" até o Eikos classificar. Medido em 03/10/2026: 2 entidades, 2 encontros.

Uso: .venv/bin/python etl/recebidos.py
"""
import datetime, json, os, pathlib, re, sys, time, unicodedata
from collections import Counter, defaultdict
import yaml
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import eikos

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "generated"
SAIDA = DATA / "recebidos.yaml"
TODAY = datetime.date.today()

# Abreviações do SIAPE/SCDP que aparecem nos nomes de órgão da agenda ("MIN GESTAO E INOV EM SERV").
ABREV = {"minist": "ministerio", "min": "ministerio", "nac": "nacional", "conserv": "conservacao",
         "desen": "desenvolvimento", "desenv": "desenvolvimento", "cien": "ciencia", "tecn": "tecnologia",
         "br": "brasileiro", "inst": "instituto", "univ": "universidade", "fund": "fundacao",
         "secret": "secretaria", "sec": "secretaria", "agric": "agricultura", "assis": "assistencia",
         "soci": "social", "famil": "familiar", "serv": "servicos", "educ": "educacao", "reg": "regional",
         "integ": "integracao", "inov": "inovacao", "amb": "ambiente", "rec": "recursos", "nat": "naturais",
         "pesq": "pesquisa", "adm": "administracao", "gest": "gestao", "transp": "transportes",
         "com": "comercio", "ind": "industria"}
FORMA = re.compile(r"\b(sa|s a|ltda|eireli|epp|mei|sociedade anonima)\b")
ADVOCACIA = re.compile(r"\badvogados?\b|\badvocacia\b")
EMPRESA = re.compile(r"\bltda\b|\bs a\b|\beireli\b|\bepp\b|\bmei\b|\bsa\b$")
SETORIAL = re.compile(r"\bassociacao\b|\bfederacao\b|\bconfederacao\b|\bsindicato\b|\bsindicatos\b")
PUBLICO = re.compile(r"\bminister|secretari|prefeitur|municip|estadual|governo|camara municipal|assembleia|"
                     r"tribunal|universidade federal|instituto federal|fundacao universidade|agencia nacional|"
                     r"conselho nacional|\buniao\b|\bfederal\b|embaixada|consulado|procuradoria|defensoria|"
                     r"policia|hospital universitario")

def nz(s):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower())).strip()
def expandir(t): return " ".join(ABREV.get(w, w) for w in nz(t).split())
def nucleo(s): return re.sub(r"\s+", " ", re.sub(r"\b(da|de|do|das|dos|e|em)\b", " ", expandir(s))).strip()
def sem_forma(t): return re.sub(r"\s+", " ", FORMA.sub(" ", nucleo(t))).strip()

def indices(N):
    """Três índices sobre os nós do grafo: nome exato, núcleo e sigla. Chave ambígua vira None."""
    por_nome, por_nucleo, por_sigla = {}, {}, {}
    for nd in N.values():
        if nd.get("type") == "dept_head": continue
        for k in [nd.get("name")] + list(nd.get("aliases") or []):
            if not k: continue
            sg = str(k).strip()
            if 2 <= len(sg) <= 12 and " " not in sg and not sg.isdigit():
                ch = nz(sg)
                por_sigla[ch] = nd["id"] if ch not in por_sigla or por_sigla[ch] == nd["id"] else None
            if len(nz(k)) < 4: continue
            por_nome.setdefault(nz(k), nd["id"])
            kn = nucleo(k)
            por_nucleo[kn] = nd["id"] if kn not in por_nucleo or por_nucleo[kn] == nd["id"] else None
    return por_nome, {k: v for k, v in por_nucleo.items() if v}, {k: v for k, v in por_sigla.items() if v}

def casar(nome, por_nome, por_nucleo, por_sigla):
    """(id do nó, como casou) ou (None, None). Só determinístico."""
    def prefixo(t):
        if len(t) < 14: return None
        cand = {v for k, v in por_nucleo.items() if k.startswith(t + " ")}
        return next(iter(cand)) if len(cand) == 1 else None
    if por_nome.get(nz(nome)): return por_nome[nz(nome)], "nome"
    if por_nucleo.get(nucleo(nome)): return por_nucleo[nucleo(nome)], "nome"
    if por_nucleo.get(sem_forma(nome)): return por_nucleo[sem_forma(nome)], "forma"
    fim = re.match(r"^(.+?)\s*[-–]\s*([A-Za-z0-9\.]{2,12})$", nome.strip())
    if fim:
        if nz(fim.group(2)) in por_sigla: return por_sigla[nz(fim.group(2))], "sigla"
        if por_nucleo.get(sem_forma(fim.group(1))): return por_nucleo[sem_forma(fim.group(1))], "forma"
    ini = re.match(r"^([A-Za-z0-9\.]{2,12})\s*[-–]\s*(.+)$", nome.strip())
    if ini:
        if nz(ini.group(1)) in por_sigla: return por_sigla[nz(ini.group(1))], "sigla"
        resto = ini.group(2)
        if por_nome.get(nz(resto)): return por_nome[nz(resto)], "resto"
        if por_nucleo.get(nucleo(resto)): return por_nucleo[nucleo(resto)], "resto"
        p = prefixo(nucleo(resto))
        if p: return p, "prefixo"
    if nz(nome) in por_sigla: return por_sigla[nz(nome)], "sigla"
    p = prefixo(nucleo(nome))
    if p: return p, "prefixo"
    return None, None

def por_marca(nome, siglas_longas):
    """Classe pela marca jurídica no nome, ou None. Nome que contém sigla de órgão nosso não entra."""
    t = nz(nome)
    if set(t.split()) & siglas_longas: return None
    if PUBLICO.search(t): return "publico_outro"
    if ADVOCACIA.search(t): return "advocacia"
    if SETORIAL.search(t): return "setorial"
    if EMPRESA.search(t): return "empresa"
    return None

PERGUNTAS = {
    "federal": {"type": "boolean", "instructions": "Esta entidade integra a administração pública FEDERAL brasileira?",
        "criteria": {"true": "é órgão da administração direta federal, autarquia ou agência reguladora federal, fundação pública federal, universidade ou instituto federal de ensino, empresa pública ou sociedade de economia mista federal, ou órgão do Congresso Nacional, do Judiciário federal ou do Ministério Público da União",
                     "false": "é de outra esfera, é de outro país, ou é entidade privada"}},
    "subnacional": {"type": "boolean", "instructions": "Esta entidade é órgão ou entidade pública ESTADUAL ou MUNICIPAL brasileira?",
        "criteria": {"true": "é governo, secretaria, câmara municipal, assembleia, tribunal, universidade, fundação ou empresa de estado, do Distrito Federal ou de município brasileiro",
                     "false": "é federal, é de outro país, ou é privada"}},
    "estrangeira": {"type": "boolean", "instructions": "Esta entidade é de outro país ou é organismo internacional?",
        "criteria": {"true": "é governo, órgão, universidade, embaixada ou empresa de outro país, ou organismo multilateral",
                     "false": "é brasileira"}},
    "privado": {"type": "boolean", "instructions": "Esta entidade representa interesse econômico privado?",
        "criteria": {"true": "é empresa privada, banco privado, escritório de advocacia, consultoria, ou entidade que representa um setor econômico",
                     "false": "é órgão público de qualquer esfera, ou é entidade sem fim econômico"}},
}
# o que a resposta do Eikos vira; só uma pode ser verdadeira, senão é contradição
DE_EIKOS = {"federal": "publico_outro", "subnacional": "publico_outro", "estrangeira": "estrangeira", "privado": "empresa"}
PRIVADAS = ("advocacia", "empresa", "setorial")

def classificar_com_eikos(nome):
    """(classe, confiança) ou (None, 0). Resposta contraditória ou pouco confiante não vale."""
    # Uma tentativa por entidade: são centenas, e o que falhar volta na próxima rodada porque o
    # arquivo só guarda veredito bem-sucedido. Três tentativas com espera crescente aqui custariam
    # horas quando o servidor está fora.
    a = eikos.avaliar(f"Nome da entidade, como consta na agenda pública de uma autoridade do governo federal brasileiro: {nome}",
                      PERGUNTAS, tentativas=1, timeout=30)
    if not a: return None, 0.0
    verd = {k: (bool(a[k].get("value")), float(a[k].get("confidence") or 0)) for k in PERGUNTAS if k in a}
    if len(verd) != len(PERGUNTAS): return None, 0.0
    sim = [k for k, (v, _) in verd.items() if v]
    if len(sim) != 1: return None, min(c for _, c in verd.values())
    k = sim[0]; conf = verd[k][1]
    if not eikos.decide_sozinho(conf): return None, conf
    return DE_EIKOS[k], conf

def main():
    ag_p = DATA / "agendas.yaml"
    if not ag_p.exists(): sys.exit(2)
    ag = yaml.safe_load(ag_p.read_text(encoding="utf-8")) or {}
    pessoas = ag.get("people") or {}
    if not pessoas: sys.exit("agendas.yaml sem pessoas")
    graf = ROOT / "build" / "graph.br.json"
    if not graf.exists(): sys.exit(2)
    N = json.load(open(graf, encoding="utf-8"))["nodes"]
    idx = indices(N)
    siglas_longas = {s for s in idx[2] if len(s) >= 5}

    # o que já foi classificado antes: veredito do Eikos não se pede duas vezes
    antes = {}
    if SAIDA.exists():
        prev = yaml.safe_load(SAIDA.read_text(encoding="utf-8")) or {}
        antes = {k: v for k, v in (prev.get("entidades") or {}).items() if isinstance(v, dict)}

    enc = Counter(); por_entidade = defaultdict(Counter)
    for pid, v in pessoas.items():
        for e in (v.get("entidades_top") or []):
            nome = (e.get("nome") or "").strip()
            if not nome: continue
            n = int(e.get("n") or 0)
            enc[nome] += n; por_entidade[nome][pid] += n

    ent = {}; pedir = []
    for nome in enc:
        nid, como = casar(nome, *idx)
        if nid:
            ent[nome] = {"classe": "orgao_federal", "via": como, "no": nid}; continue
        cl = por_marca(nome, siglas_longas)
        if cl:
            ent[nome] = {"classe": cl, "via": "marca"}; continue
        ja = antes.get(nome)
        if ja and ja.get("via") == "eikos" and ja.get("classe"):
            ent[nome] = dict(ja); continue
        ent[nome] = {"classe": "nao_classificado", "via": None}; pedir.append(nome)

    if pedir and eikos.disponivel():
        # Disjuntor. Em 03/10/2026 o servidor do Eikos devolvia 502 e o conector ficou pendurado:
        # 937 entidades, cada uma com três tentativas e espera crescente. Serviço de apoio fora do ar
        # não pode travar o conector — se as primeiras seguidas falham, desistimos e seguimos sem ele.
        # Orçamento de tempo. O update.sh corta cada conector em 900s (ATLAS_LIMITE) e são centenas de
        # entidades: o que não couber hoje é perguntado amanhã, porque o veredito fica guardado. Um
        # conector cortado no meio é pior do que um que para sozinho e grava o que já sabe.
        ORCAMENTO = float(os.environ.get("RECEBIDOS_ORCAMENTO", "420"))
        comeco = time.time()
        SEGUIDAS = 8
        falhas = 0; perguntadas = 0
        for nome in pedir:
            if time.time() - comeco > ORCAMENTO:
                print(f"orçamento de {ORCAMENTO:.0f}s esgotado: {perguntadas} de {len(pedir)} perguntadas, o resto fica para a próxima rodada")
                break
            cl, conf = classificar_com_eikos(nome)
            perguntadas += 1
            if cl:
                ent[nome] = {"classe": cl, "via": "eikos", "conf": round(conf, 3), "em": TODAY.isoformat()}
                falhas = 0
            else:
                # conf > 0 significa que ele respondeu e a resposta não bastou: não é falha de serviço
                falhas = 0 if conf > 0 else falhas + 1
                if falhas >= SEGUIDAS:
                    print(f"Eikos sem resposta em {SEGUIDAS} seguidas: parando após {perguntadas} de {len(pedir)}")
                    break
        decididas = sum(1 for n_ in pedir if ent[n_].get("via") == "eikos")
        print(f"Eikos: {perguntadas} perguntadas, {decididas} decididas acima do corte · gasto {eikos.gasto()}")
    elif pedir:
        print(f"Eikos indisponível: {len(pedir)} entidades ficam como não classificadas")

    nomes = {p: (v.get("agente") or p) for p, v in pessoas.items()}
    privadas = []
    for nome, info in ent.items():
        if info["classe"] not in PRIVADAS: continue
        quem = por_entidade[nome].most_common(6)
        privadas.append({"nome": nome, "n": enc[nome], "classe": info["classe"], "via": info["via"],
                         "recebida_por": [{"pessoa": p, "nome": nomes.get(p, p), "n": c} for p, c in quem]})
    privadas.sort(key=lambda x: (-x["n"], x["nome"]))

    quem_recebeu = Counter(); quantas = defaultdict(set)
    for nome, info in ent.items():
        if info["classe"] not in PRIVADAS: continue
        for p, c in por_entidade[nome].items(): quem_recebeu[p] += c; quantas[p].add(nome)

    por_classe = Counter(info["classe"] for info in ent.values())
    vol_classe = Counter()
    for nome, info in ent.items(): vol_classe[info["classe"]] += enc[nome]

    out = {"generated_at": TODAY.isoformat(),
           "fonte": ag.get("fonte"), "agenda_lida_em": str(ag.get("generated_at") or "")[:10],
           "janela_dias": ag.get("janela_dias"), "janela_inicio": str(ag.get("janela_inicio") or "")[:10],
           "agendas": len(pessoas), "entidades_n": len(ent), "encontros": sum(enc.values()),
           "nota": ("Soma das entidades mais frequentes de cada agenda pública, não o total de reuniões do governo: "
                    "o conector da agenda guarda as mais frequentes por autoridade. Entidade sem classificação não é "
                    "apresentada como privada. Empresa controlada por estado ou município que o Atlas ainda não tem "
                    "como nó pode aparecer como empresa até ser classificada uma a uma."),
           "por_classe": {k: {"entidades": por_classe[k], "encontros": vol_classe[k]} for k in sorted(por_classe)},
           "privadas": privadas[:120],
           "privadas_total": {"entidades": sum(por_classe[c] for c in PRIVADAS), "encontros": sum(vol_classe[c] for c in PRIVADAS)},
           "quem_recebeu": [{"pessoa": p, "nome": nomes.get(p, p), "encontros": c, "entidades": len(quantas[p])}
                            for p, c in quem_recebeu.most_common(30)],
           "entidades": {k: v for k, v in sorted(ent.items())}}
    SAIDA.write_text("# GERADO por etl/recebidos.py. Não edite à mão.\n" + yaml.dump(out, allow_unicode=True, sort_keys=False, width=140), encoding="utf-8")
    print(f"recebidos: {len(ent)} entidades, {sum(enc.values())} encontros")
    for k in sorted(por_classe, key=lambda k: -vol_classe[k]): print(f"   {vol_classe[k]:>6} encontros · {por_classe[k]:>4} entidades · {k}")
    print(f"   interesse privado: {out['privadas_total']['encontros']} encontros em {out['privadas_total']['entidades']} entidades")
    for x in privadas[:8]: print(f"      {x['n']:>3}  [{x['classe']}] {x['nome'][:56]}")

if __name__ == "__main__": main()
