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

Endereço: EIKOS_URL, no ambiente ou no .env. O experimento original era http://154.59.156.40:33532 (HTTP
sem criptografia, de onde vem a regra de só mandar texto já público); ele saiu do ar em outubro de 2026 e o
serviço passou a https://api.openinterp.org (Ekbasis, da Open Interpretability), agora com TLS. O endpoint
novo fica atrás de Cloudflare e recusa cliente sem User-Agent de navegador, com "error code: 1010" — que
não é erro de credencial e engana quem for diagnosticar.

A chave vem de EIKOS_KEY. Sem chave, ou com chave recusada, todas as funções devolvem None e quem chama
segue sem a checagem, nunca quebra. Onde isso mudaria o que aparece na tela, o conector diz: etl/noticias.py
tem porteiro de reserva, e etl/recebidos.py declara as entidades como não classificadas.

Uso:
  .venv/bin/python etl/eikos.py            # teste de fumaça
  from eikos import avaliar, disponivel    # dentro de outro conector
"""
import json, os, pathlib, sys, time, urllib.error, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
def _do_ambiente_ou_env(nome, padrao=None):
    """Variável do ambiente, ou do .env do projeto, ou o padrão.

    O cliente lia a chave do .env mas o endereço só do ambiente. Resultado: trocar EIKOS_URL no .env
    não tinha efeito nenhum, em silêncio — perdi tempo achando que a credencial nova estava sendo
    recusada quando o cliente seguia batendo no endereço antigo, já desligado.
    """
    v = os.environ.get(nome)
    if v: return v.strip()
    env = ROOT / ".env"
    if env.exists():
        for ln in env.read_text(encoding="utf-8").splitlines():
            if ln.startswith(nome + "="):
                return ln.split("=", 1)[1].strip().strip('"').strip("'")
    return padrao


# O experimento original (http://154.59.156.40:33532) saiu do ar em outubro de 2026; o padrão passa a
# ser o endereço novo, com TLS. EIKOS_URL continua mandando, para apontar para outro sem mexer no código.
URL = (_do_ambiente_ou_env("EIKOS_URL", "https://openinterp.org/api/v1") or "").rstrip("/")
# A rota é /v1/systemone sobre uma base que já termina em /api/v1 — o "/v1" dobrado é do serviço, não
# engano: está assim no openapi.json (servers: .../api/v1, paths: /v1/systemone). Qualquer outra
# combinação devolve 404, e com chave válida o 404 parece credencial recusada.
ROTA = os.environ.get("EIKOS_ROTA", "/v1/systemone")
CORTE_CONFIANCA = float(os.environ.get("EIKOS_CORTE", "0.80"))
LIMITE_POR_MINUTO = 120
_ultimo = [0.0]
_gasto = {"chamadas": 0, "tokens": 0, "erros": 0}


def _chave():
    return _do_ambiente_ou_env("EIKOS_KEY")


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
    # O User-Agent de navegador não é cosmético: o endereço novo fica atrás de Cloudflare, que recusa
    # cliente sem assinatura de navegador com "error code: 1010" — e 1010 vem como 403, o que faz
    # parecer credencial inválida quando é bloqueio de borda.
    req = urllib.request.Request(f"{URL}{ROTA}", data=corpo, method="POST",
                                 headers={"Authorization": f"Bearer {chave}", "Content-Type": "application/json",
                                          "Accept": "application/json",
                                          "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"})
    for t in range(tentativas):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.loads(r.read())
            _ultimo[0] = time.time()
            _gasto["chamadas"] += 1
            _gasto["tokens"] += (d.get("usage") or {}).get("input_tokens", 0)
            return d.get("answers") or {}
        except urllib.error.HTTPError as e:
            # 401 e 403 são credencial recusada ou bloqueio de borda: insistir não resolve e só bate no
            # serviço. Dizer o motivo uma vez, com o texto da resposta, poupa o diagnóstico de quem vier
            # depois — antes isso saía como erro mudo e parecia o serviço estar fora.
            if e.code in (401, 403):
                if not _gasto.get("avisou"):
                    try: detalhe = e.read()[:120].decode(errors="replace")
                    except Exception: detalhe = ""
                    print(f"Eikos recusou a credencial em {URL} (HTTP {e.code}): {detalhe}", file=sys.stderr)
                    _gasto["avisou"] = True
                _gasto["erros"] += 1; return None
            if e.code in (429, 502) and t < tentativas - 1: time.sleep(3 * 2 ** t); continue
            _gasto["erros"] += 1; return None
        except Exception:
            if t < tentativas - 1: time.sleep(3 * 2 ** t); continue
            _gasto["erros"] += 1; return None
    return None


def confianca(resposta):
    """A confiança calibrada, quando o serviço a oferece.

    O Ekbasis devolve dois números: `confidence` cru e `calibrated.confidence`, corrigido por
    temperatura. No teste de 15/10/2026 o cru deu 0,94 e o calibrado 0,85 para a mesma resposta —
    usar o cru inflaria a certeza e deixaria o corte de 0,80 mais permissivo do que o que foi medido.
    """
    if not isinstance(resposta, dict): return 0.0
    cal = resposta.get("calibrated")
    if isinstance(cal, dict) and cal.get("confidence") is not None:
        return float(cal["confidence"])
    return float(resposta.get("confidence") or 0)


def probabilidade(resposta):
    if not isinstance(resposta, dict): return 0.0
    cal = resposta.get("calibrated")
    if isinstance(cal, dict) and cal.get("probability") is not None:
        return float(cal["probability"])
    return float(resposta.get("probability") or 0)


def sim_nao(state, pergunta, quando_sim, quando_nao, chave="r"):
    """Atalho para uma pergunta binária. Devolve (valor, confiança calibrada) ou (None, 0)."""
    a = avaliar(state, {chave: {"type": "boolean", "instructions": pergunta,
                                "criteria": {"true": quando_sim, "false": quando_nao}}})
    if not a or chave not in a: return None, 0.0
    r = a[chave]
    return bool(r.get("value")), confianca(r)


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
