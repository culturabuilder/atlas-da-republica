#!/usr/bin/env python3
"""Casar nome de órgão, como vem de uma fonte externa, com um nó do grafo do Atlas.

Os 1.366 nós do Atlas são os órgãos federais, com nome, sigla e apelido já curados: quando o nome de
uma fonte casa com um nó, isso não é chute, é o nosso próprio dado. Só que cada fonte escreve o nome
do mesmo órgão de um jeito — "MGI", "MIN.DA GEST.E DA INOVACAO EM SERVICOS PUBLICO", "Ministério da
Gestão e da Inovação em Serviços Públicos" — e as regras para reconciliar isso foram sendo apuradas
caso a caso, conferindo à mão o que passava a casar.

Este módulo existe porque a lógica já tinha dois consumidores (etl/recebidos.py e etl/sancoes.py) e
duas cópias de uma regra sutil divergem. Consumidor novo entra aqui.

A regra de ouro: só casamento determinístico e verificável. Chave que aponta para mais de um nó não
casa com nenhum, porque linkar errado é pior do que não linkar — um deputado aparecendo como relator
na comissão errada, ou uma demissão pendurada no ministério de outra pessoa, destrói a confiança que
o projeto inteiro depende de ter.
"""
import re
import unicodedata

# Abreviações do SIAPE, do SCDP e dos cadastros da CGU, que cortam o nome do órgão sem critério fixo.
ABREV = {
    "minist": "ministerio", "min": "ministerio", "mini": "ministerio",
    "nac": "nacional", "nacl": "nacional", "conserv": "conservacao",
    "desen": "desenvolvimento", "desenv": "desenvolvimento", "desenvolv": "desenvolvimento",
    "cien": "ciencia", "tecn": "tecnologia", "tec": "tecnologia", "br": "brasileiro",
    "inst": "instituto", "univ": "universidade", "fund": "fundacao",
    "secret": "secretaria", "sec": "secretaria", "agric": "agricultura",
    "assis": "assistencia", "soci": "social", "famil": "familiar", "serv": "servicos",
    "educ": "educacao", "reg": "regional", "integ": "integracao", "inov": "inovacao",
    "amb": "ambiente", "rec": "recursos", "nat": "naturais", "aliment": "alimentacao",
    "pesq": "pesquisa", "adm": "administracao", "gest": "gestao", "transp": "transportes",
    "com": "comercio", "ind": "industria", "publico": "publicos", "gen": "geral",
}
FORMA_JURIDICA = re.compile(r"\b(sa|s a|ltda|eireli|epp|mei|sociedade anonima)\b")
PREFIXO_ADM = re.compile(r"^(departamento de|departamento|secretaria especial da|secretaria da|secretaria de|"
                         r"superintendencia regional de|superintendencia de|superintendencia|"
                         r"coordenacao geral de|coordenacao de|comando da|comando do|comando de)\s+")

# Mesma pessoa jurídica, nome antigo ou administrativo na fonte -> nó de hoje. Um por um, conferido.
NOMES_ALTERNATIVOS = {
    "fundacao nacional indio": "br-funai",                                  # renomeada em 2023
    "ministerio agricultura pecuaria abastecimento": "br-ministerio-da-agricultura-e-pecuaria",
    "ministerio ciencia tecnologia inovacoes": "br-ministerio-da-ciencia-tecnologia-e-inovacao",
    "secretaria receita federal": "br-receita-federal-do-brasil",
    "comando exercito": "br-exercito-brasileiro",                           # nome administrativo do Exército
    "comando marinha": "br-marinha-do-brasil",
}
# Órgão que não existe mais e não tem sucessor único: casar seria atribuir o fato a quem não é dele.
EXTINTOS = {
    "ministerio economia": "existiu de 2019 a 2022; dividido em Fazenda, Gestão, MDIC e Planejamento",
    "ministerio trabalho previdencia": "existiu de 2021 a 2023; dividido em Trabalho e Emprego e Previdência Social",
    "ministerio planejamento desenvolvimento gestao": "reorganizado mais de uma vez desde 2016",
    "ministerio infraestrutura": "dividido em Transportes e Portos e Aeroportos em 2023",
    "ministerio desenvolvimento regional": "dividido em Integração e Desenvolvimento Regional e Cidades em 2023",
    "ministerio trabalho emprego previdencia social": "o par Trabalho/Previdência mudou de desenho em 2023",
}
# Nome genérico que designa um conjunto, não um órgão: casar com qualquer membro seria arbitrário.
GENERICOS = {
    "justica federal": "designa o conjunto dos tribunais e seções federais, não um órgão",
    "poder judiciario": "designa um poder inteiro",
    "forcas armadas": "designa as três Forças",
    "justica trabalho": "designa o conjunto dos tribunais do trabalho",
    "justica eleitoral": "designa o conjunto da Justiça Eleitoral",
    "justica militar": "designa o conjunto da Justiça Militar",
    "ministerio publico": "designa o conjunto dos ramos do Ministério Público",
}


def nz(s):
    """Minúsculas, sem acento e sem pontuação, espaços colapsados."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ",
                  unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower())).strip()


def nucleo(s):
    """O miolo comparável do nome: sem artigo, sem abreviação e sem hífen.

    O hífen importa: "infra-estrutura" (grafia anterior a 2009) virava "infra estrutura" e deixava de
    casar com "infraestrutura". Juntar os pedaços da palavra hifenizada resolve a classe inteira.
    """
    t = re.sub(r"[-–]", "", str(s or ""))
    palavras = [ABREV.get(p, p) for p in nz(t).split()]
    return re.sub(r"\s+", " ", re.sub(r"\b(da|de|do|das|dos|e|em)\b", " ", " ".join(palavras))).strip()


def sem_forma(s):
    """Núcleo sem a forma jurídica: "BANCO DO BRASIL SA" e "Banco do Brasil" são o mesmo banco."""
    return re.sub(r"\s+", " ", FORMA_JURIDICA.sub(" ", nucleo(s))).strip()


def indices(nodes):
    """Três índices sobre os nós: nome exato, núcleo e sigla. Chave ambígua é descartada."""
    por_nome, por_nucleo, por_sigla = {}, {}, {}
    for nd in nodes.values():
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


def casar(nome, idx):
    """(id do nó, como casou) quando casa; (None, motivo) quando não.

    Passes, do mais seguro para o menos: recusa declarada, nome alternativo declarado, nome exato,
    núcleo, forma jurídica removida, sigla antes ou depois do travessão, prefixo administrativo e,
    por último, núcleo de um único nó contido no nome (unidade regional, nome com palavras a mais).
    """
    por_nome, por_nucleo, por_sigla = idx
    bruto = str(nome or "").strip()
    nuc = nucleo(bruto)
    if not nuc: return None, "sem nome"
    if nuc in EXTINTOS: return None, "extinto"
    if nuc in GENERICOS: return None, "genérico"
    if nuc in NOMES_ALTERNATIVOS: return NOMES_ALTERNATIVOS[nuc], "nome alternativo"
    if por_nome.get(nz(bruto)): return por_nome[nz(bruto)], "nome"
    if por_nucleo.get(nuc): return por_nucleo[nuc], "nome"
    if por_nucleo.get(sem_forma(bruto)): return por_nucleo[sem_forma(bruto)], "forma jurídica"
    fim = re.match(r"^(.+?)\s*[-–]\s*([A-Za-z0-9\.]{2,12})$", bruto)
    if fim:
        if nz(fim.group(2)) in por_sigla: return por_sigla[nz(fim.group(2))], "sigla"
        if por_nucleo.get(sem_forma(fim.group(1))): return por_nucleo[sem_forma(fim.group(1))], "forma jurídica"
    ini = re.match(r"^([A-Za-z0-9\.]{2,12})\s*[-–]\s*(.+)$", bruto)
    if ini:
        if nz(ini.group(1)) in por_sigla: return por_sigla[nz(ini.group(1))], "sigla"
        resto = ini.group(2)
        if por_nome.get(nz(resto)): return por_nome[nz(resto)], "resto"
        if por_nucleo.get(nucleo(resto)): return por_nucleo[nucleo(resto)], "resto"
    if nz(bruto) in por_sigla: return por_sigla[nz(bruto)], "sigla"
    sem_pref = PREFIXO_ADM.sub("", nuc).strip()
    if sem_pref and por_nucleo.get(sem_pref): return por_nucleo[sem_pref], "prefixo administrativo"
    for alvo in (nuc, sem_pref):
        if len(alvo) < 14: continue
        cand = {v for k, v in por_nucleo.items() if len(k) >= 14 and (k + " ") in (alvo + " ")}
        if len(cand) == 1: return next(iter(cand)), "contido no nome"
    return None, "não casou"
