#!/usr/bin/env python3
"""Cliente do Eikos-27B: pergunta tipada com probabilidade calibrada, zero token de saída.

O Eikos não gera texto. Recebe um estado (o caso) e perguntas tipadas, e devolve a resposta com
uma probabilidade calibrada para cada opção, numa passada só. Serve para o que no Atlas hoje ou
não é feito, ou é feito por modelo gerativo caro:

  - porteiro: esta notícia é sobre o governo federal?            (boolean)
  - conferência: este resumo afirma número que não está na fonte? (boolean)
  - identidade: estes dois registros são a mesma pessoa?          (boolean)
  - triagem: responder tudo e mandar ao humano só o que ficou abaixo do corte de confiança

Onde ele acerta, medido em 24/09/2026 sobre dado do próprio Atlas: pergunta binária com resposta
factual conferível. Onde erra: taxonomia que exige julgamento de domínio (85% ao classificar
benefícios, perdendo as discordâncias). Não use para o que um regex já resolve bem.

CORTE_CONFIANCA é o limite acima do qual a resposta pode valer sozinha. Acima de 0,80 ele acertou
98% das vezes no porteiro de relevância, cobrindo 83% dos casos; abaixo de 0,60, só 25%.

Experimento da Cultura Builder, sem garantia de disponibilidade. É HTTP sem criptografia: só mande
texto que já é público. A chave vem de EIKOS_KEY, no ambiente ou no .env (que não vai para o git).
Sem chave, todas as funções devolvem None e quem chama segue sem a checagem, nunca quebra.

Uso:
  .venv/bin/python etl/eikos.py            # teste de fumaça
  from eikos import avaliar, disponivel    # dentro de outro conector
"""
import json, os, pathlib, time, urllib.error, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
URL = os.environ.get("EIKOS_URL", "http://154.59.156.40:33532")
CORTE_CONFIANCA = float(os.environ.get("EIKOS_CORTE", "0.80"))
LIMITE_POR_MINUTO = 120
_ultimo = [0.0]
_gasto = {"chamadas": 0, "tokens": 0, "erros": 0}


def _chave():
    k = os.environ.get("EIKOS_KEY")
    if k: return k.strip()
    env = ROOT / ".env"
    if env.exists():
        for ln in env.read_text(encoding="utf-8").splitlines():
            if ln.startswith("EIKOS_KEY="):
                return ln.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def disponivel():
    """Há chave configurada? Quem chama deve seguir sem a checagem quando não houver."""
    return bool(_chave())


def gasto():
    """Quanto esta execução consumiu, para o conector poder imprimir no fim."""
    return dict(_gasto)


def avaliar(state, questions, tentativas=3, timeout=60):
    """Devolve o dicionário de respostas, ou None se não der (sem chave, fora do ar, erro)."""
    chave = _chave()
    if not chave: return None
    espera = 60.0 / LIMITE_POR_MINUTO - (time.time() - _ultimo[0])
    if espera > 0: time.sleep(espera)
    corpo = json.dumps({"state": state, "questions": questions}).encode()
    req = urllib.request.Request(f"{URL}/v1/evaluate", data=corpo, method="POST",
                                 headers={"Authorization": f"Bearer {chave}", "Content-Type": "application/json"})
    for t in range(tentativas):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.loads(r.read())
            _ultimo[0] = time.time()
            _gasto["chamadas"] += 1
            _gasto["tokens"] += (d.get("usage") or {}).get("input_tokens", 0)
            return d.get("answers") or {}
        except urllib.error.HTTPError as e:
            if e.code in (429, 502) and t < tentativas - 1: time.sleep(3 * 2 ** t); continue
            _gasto["erros"] += 1; return None
        except Exception:
            if t < tentativas - 1: time.sleep(3 * 2 ** t); continue
            _gasto["erros"] += 1; return None
    return None


def sim_nao(state, pergunta, quando_sim, quando_nao, chave="r"):
    """Atalho para uma pergunta binária. Devolve (valor, confiança) ou (None, 0)."""
    a = avaliar(state, {chave: {"type": "boolean", "instructions": pergunta,
                                "criteria": {"true": quando_sim, "false": quando_nao}}})
    if not a or chave not in a: return None, 0.0
    r = a[chave]
    return bool(r.get("value")), float(r.get("confidence") or 0)


def decide_sozinho(confianca):
    """A resposta pode valer sem revisão humana?"""
    return confianca >= CORTE_CONFIANCA


if __name__ == "__main__":
    import sys
    if not disponivel():
        print("sem EIKOS_KEY no ambiente nem no .env", file=sys.stderr); sys.exit(2)
    v, c = sim_nao("Título: Lula sanciona lei que muda o Bolsa Família. Fonte: Agência Brasil.",
                   "Esta notícia trata do governo federal brasileiro?",
                   "trata do governo federal, do Congresso, do Judiciário federal ou das eleições federais",
                   "trata de outro assunto")
    print(f"resposta: {v} | confiança {c:.2f} | decide sozinho: {decide_sozinho(c)}")
    print(f"gasto: {gasto()}")
