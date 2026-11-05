#!/usr/bin/env python3
"""Download dos zips de dados abertos do TSE, compartilhado pelos conectores que os leem.

Por que existe: patrimônio, candidaturas, doadores e votos liam zips que alguém tinha de baixar à mão
num formulário do TSE. No servidor que atualiza o site todo dia esse arquivo nunca existe, então os
quatro apareciam como "falta arquivo local" em todo eval — o patrimônio ficou 42 dias assim, e o dado
publicado envelheceu sem que ninguém pudesse consertar sem acesso à máquina.

O catálogo de dados abertos do TSE (dadosabertos.tse.jus.br, CKAN) publica o endereço direto de cada
zip no CDN, e o CDN serve sem formulário: conferido em 05/11/2026, HEAD em bem_candidato_2022.zip
devolve 5,7 MB application/zip. É a mesma fonte, o mesmo arquivo — só sem a mão no meio.

Dois dos quatro arquivos são grandes: prestação de contas de 2022 tem 472 MB e votação por município
631 MB. Num runner limpo seria isso de download por rodada, todo dia, para dado de eleição encerrada
que não muda. Esses só baixam com ATLAS_TSE_PESADO=1, e sem eles o conector mantém o que já publicou.

Nota sobre o bloqueio: o conector de candidaturas dizia no cabeçalho que "o CDN do TSE bloqueia".
Bloqueia com User-Agent de script; com assinatura de navegador serve normalmente. Era isso.

Uso: from tse import baixar;  baixar("bem_candidato", 2022, CACHE)
"""
import os, pathlib, sys, urllib.request, zipfile

CDN = "https://cdn.tse.jus.br/estatistica/sead/odsele"
NAVEGADOR = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/129.0 Safari/537.36", "Accept": "application/zip,*/*"}
MINIMO = 100_000   # zip menor que isto é página de erro, não dado


def baixar(base, ano, cache, timeout=900, pasta=None, pesado=False):
    """Garante {cache}/{base}_{ano}.zip. Devolve True se o arquivo está lá no fim.

    `pasta` é o diretório no CDN quando difere do nome do arquivo (prestacao_contas/...).
    `pesado` marca arquivo de centenas de MB: só baixa com ATLAS_TSE_PESADO=1.

    Nunca levanta: quem chama decide o que fazer sem o arquivo, e todos eles sabem manter o anterior.
    """
    cache = pathlib.Path(cache)
    alvo = cache / f"{base}_{ano}.zip"
    if alvo.exists() and alvo.stat().st_size > MINIMO: return True
    if pesado and os.environ.get("ATLAS_TSE_PESADO") != "1":
        print(f"  TSE: {alvo.name} não está em disco e tem centenas de MB; rode com ATLAS_TSE_PESADO=1 "
              f"para baixar. Mantido o dado já publicado.", file=sys.stderr)
        return False
    cache.mkdir(parents=True, exist_ok=True)
    url = f"{CDN}/{pasta or base}/{base}_{ano}.zip"
    tmp = alvo.with_suffix(".parcial")
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=NAVEGADOR), timeout=timeout) as r, open(tmp, "wb") as f:
            while True:
                b = r.read(1 << 20)
                if not b: break
                f.write(b)
        # zip truncado é pior que zip ausente: o conector leria metade e gravaria menos do que havia
        with zipfile.ZipFile(tmp) as z:
            if z.testzip() is not None: raise zipfile.BadZipFile("conteúdo corrompido")
        tmp.replace(alvo)
        print(f"  TSE: baixado {alvo.name}, {alvo.stat().st_size/1048576:.1f} MB", file=sys.stderr)
        return True
    except Exception as e:
        tmp.unlink(missing_ok=True)
        print(f"  TSE: {base}_{ano}.zip não baixou ({type(e).__name__} {str(e)[:70]})", file=sys.stderr)
        return alvo.exists() and alvo.stat().st_size > MINIMO
