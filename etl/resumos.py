#!/usr/bin/env python3
"""Resumos em linguagem simples (Claude API) para MPs, vetos, pedidos de CPI e temas.

Lê `data/generated/omissao.yaml` e `data/generated/temas.yaml`, monta um texto-fonte por item
(ementa oficial + situação + prazo), e pede a um modelo Claude um resumo de 2 a 3 frases em
português claro, sem opinião. Cada resumo é gravado em `data/generated/resumos.yaml` com o hash
do texto-fonte; só é regenerado quando a ementa/situação muda. Sem `ANTHROPIC_API_KEY` no
ambiente ou em `.env`, o script mantém o arquivo como está e sai sem erro (o site mostra só a
ementa oficial).

Conferência (Eikos): todo resumo gerado é conferido contra o próprio texto-fonte antes de ficar no
cache, e o resultado é gravado junto — `conferido` (bool, true quando nenhum alerta), `alertas`
(lista de rótulos) e `conf` (a maior confiança entre os alertas; 0 quando não há alerta). São três
perguntas: fato fora da fonte, juízo de valor e número ou data divergente. Sem EIKOS_KEY no ambiente
ou no .env, ou se o Eikos falhar, o resumo é gravado sem esses campos e nada mais muda.

Uso:
  python etl/resumos.py                # gera o que falta (respeita cache) e confere o que gerou
  python etl/resumos.py --dry-run      # mostra os itens pendentes e o prompt, sem chamar a API
  python etl/resumos.py --limit 20     # no máximo N chamadas nesta execução
  python etl/resumos.py --force ID     # regenera um item
  python etl/resumos.py --conferir     # só confere os resumos que já estão em cache, sem gerar nada

Provedores (RESUMOS_PROVIDER = culturabuilder | anthropic | auto, padrão auto):
  - culturabuilder: usa o comando `culturabuilder run -m builder-ai/builder-fast` (login OAuth já feito na máquina;
    não funciona no GitHub Actions). RESUMOS_MODEL padrão: builder-ai/builder-fast.
  - anthropic: SDK oficial com ANTHROPIC_API_KEY; RESUMOS_MODEL padrão: claude-sonnet-5.
Sem provedor disponível, o arquivo existente é mantido (os resumos já gerados continuam no site).
O texto-fonte não inclui contagens de dias, só datas, para o hash não mudar todo dia.
"""
import argparse, datetime, hashlib, json, os, pathlib, sys, time
import yaml
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import eikos

ROOT = pathlib.Path(__file__).resolve().parent.parent
GEN = ROOT / "data" / "generated"
OUT = GEN / "resumos.yaml"
PROVIDER = os.environ.get("RESUMOS_PROVIDER", "auto")
MODEL = os.environ.get("RESUMOS_MODEL")
CB_BIN = os.environ.get("CULTURABUILDER_BIN") or (__import__("shutil").which("culturabuilder") or str(pathlib.Path.home() / ".local" / "bin" / "culturabuilder"))
MAX_TEXT = 1800  # caracteres do texto-fonte enviados por item

SYSTEM = (
    "Você escreve para o Atlas da República, um site público e apartidário sobre o governo brasileiro. "
    "Sua tarefa: explicar em linguagem simples, para quem nunca leu um texto jurídico, o que é um ato do "
    "Congresso ou do Executivo e em que pé ele está. Regras: 2 ou 3 frases curtas (máximo 70 palavras), "
    "português do Brasil, voz ativa, sem adjetivos de opinião, sem dizer se é bom ou ruim, sem atribuir "
    "intenção a ninguém, sem inventar fatos que não estejam no texto-fonte. Traduza siglas e jargão "
    "(por exemplo: 'medida provisória' = regra que o presidente cria e já vale, mas o Congresso precisa "
    "aprovar em até 120 dias; 'veto' = trecho de lei que o presidente barrou e o Congresso pode derrubar; "
    "'CPI' = comissão de deputados ou senadores para investigar algo). Se houver prazo ou valor, diga em "
    "termos concretos (dias, reais por extenso aproximado). Responda só com o resumo, sem título nem aspas."
)


def _load_env():
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _yaml(p):
    return yaml.safe_load(p.read_text()) if p.exists() else None


def _brl(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    for div, sing, plur in ((1e9, "bilhão", "bilhões"), (1e6, "milhão", "milhões")):
        if v >= div:
            n = v / div; s = f"{n:.1f}".rstrip("0").rstrip(".").replace(".", ",")
            return f"R$ {s} {sing if n < 2 else plur}"
    return f"R$ {v:,.0f}".replace(",", ".")


def items():
    """Lista de {id, kind, title, text} com o texto-fonte de cada item."""
    out = []
    om = _yaml(GEN / "omissao.yaml") or {}
    # mesmos recortes que scripts/build_graph.py leva para o site (para não pagar por itens invisíveis)
    mpvs = [x for x in om.get("mpvs") or [] if (x.get("days_left") is None or x["days_left"] >= -3) and "ANTES DA EC" not in (x.get("status") or "")]
    mpvs = sorted(mpvs, key=lambda x: (x.get("days_left") if x.get("days_left") is not None else 9999))[:15]
    vetos = (om.get("vetos") or [])[:12]
    rcps = [x for x in om.get("rcps") or [] if x.get("status") in ("aguardando", "indeferido", "outro")][:15]
    for m in mpvs:
        parts = [f"Medida provisória {m.get('title')}", f"Ementa oficial: {m.get('summary')}",
                 f"Editada em {m.get('date')}; prazo final para o Congresso votar: {m.get('deadline')}",
                 f"Situação no Congresso: {m.get('status')}"]
        if m.get("value") and float(m["value"]) >= 1000:
            parts.append(f"Valor envolvido: {_brl(m['value'])}")
        if m.get("prorogued"):
            parts.append("Já foi prorrogada uma vez (o prazo de 60 dias virou 120).")
        out.append({"id": m["id"], "kind": "mpv", "title": m.get("title"), "text": "\n".join(p for p in parts if p)})
    for v in vetos:
        parts = [f"{v.get('title')} ao projeto {v.get('materia')}, que virou a {v.get('norma')}",
                 f"Ementa oficial: {v.get('summary')}",
                 f"Veto publicado em {v.get('date')}; ainda não foi apreciado pelo Congresso "
                 f"(a Constituição dá 30 dias para o Congresso decidir se mantém ou derruba o veto)."]
        out.append({"id": v["id"], "kind": "veto", "title": v.get("title"), "text": "\n".join(p for p in parts if p)})
    for r in rcps:
        parts = [f"Pedido de CPI {r.get('title')} na Câmara dos Deputados",
                 f"Texto oficial do requerimento: {r.get('summary')}",
                 f"Protocolado em {r.get('date')}; tem {r.get('signatures')} assinaturas "
                 f"de deputados (mínimo exigido: {r.get('min_signatures')}).",
                 f"Situação: {r.get('situation')}" if r.get("situation") and "Não Definido" not in str(r.get("situation")) else None,
                 f"Último andamento ({r.get('last_move')}): {str(r.get('despacho') or '')[:400]}" if r.get("despacho") else None]
        out.append({"id": r["id"], "kind": "rcp", "title": r.get("title"), "text": "\n".join(p for p in parts if p)})
    for c in om.get("curated") or []:
        parts = [f"{c.get('title')} ({c.get('kind')})", f"Descrição: {c.get('summary')}",
                 f"Protocolado em {c.get('filed_at')}; status: {c.get('status')}",
                 f"Regra de prazo: {c.get('legal_deadline')}" if c.get("legal_deadline") else None]
        out.append({"id": c["id"], "kind": "curado", "title": c.get("title"), "text": "\n".join(p for p in parts if p)})
    tm = _yaml(GEN / "temas.yaml") or {}
    for t in tm.get("temas") or []:
        parts = [f"Tema em acompanhamento: {t.get('name')}", f"Pergunta que o site faz: {t.get('question')}",
                 f"Estado atual: {t.get('state')}"]
        for p in (t.get("processes") or [])[:3]:
            parts.append(f"Processo {p.get('id')} ({p.get('casa')}): {str(p.get('ementa') or '')[:400]} — situação: {p.get('situation')}; último andamento {p.get('last_move')}")
        out.append({"id": f"tema-{t['id']}", "kind": "tema", "title": t.get("name"), "text": "\n".join(p for p in parts if p)})
    for it in out:
        it["text"] = it["text"][:MAX_TEXT]
        it["hash"] = hashlib.sha1(it["text"].encode()).hexdigest()[:12]
    return out


# --- conferência do resumo contra o texto-fonte (Eikos) ---------------------------------------
# Medido em 24/09/2026 sobre os 51 resumos publicados. A pergunta "inventou" é a segunda versão: a
# ingênua deu 19 alarmes falsos em 50 porque os resumos acrescentam explicação cívica de propósito.
CONFERE_Q = {
 "inventou": {"type": "boolean", "instructions": "Algum número, data, nome, valor ou situação que o resumo atribui a ESTE item específico diverge do texto-fonte ou não aparece nele? Explicação genérica sobre o que é uma medida provisória, um veto ou um projeto de lei não conta como fato inventado.",
   "criteria": {"true": "o resumo atribui a este item um número, data, nome, valor ou situação processual que o texto-fonte não traz ou traz diferente",
                "false": "todo dado específico deste item confere com o texto-fonte; o que o resumo acrescenta é só explicação geral de como o processo funciona"}},
 "opiniao": {"type": "boolean", "instructions": "O resumo emite juízo de valor, diz se algo é bom ou ruim, ou atribui intenção a alguém?",
   "criteria": {"true": "há adjetivo de opinião, avaliação de mérito, ou intenção atribuída a pessoa, partido ou governo",
                "false": "o resumo apenas descreve o que a norma diz e em que pé está, sem avaliar"}},
 "numeros": {"type": "boolean", "instructions": "Todos os números e datas do resumo conferem com o texto-fonte?",
   "criteria": {"true": "cada número e cada data do resumo aparece igual no texto-fonte",
                "false": "algum número ou data do resumo diverge do texto-fonte ou não aparece nele"}},
}
ROTULOS = {"inventou": "fato fora da fonte", "opiniao": "juízo de valor", "numeros": "número ou data divergente"}


def conferir(texto_fonte, resumo):
    """{conferido, alertas, conf} comparando o resumo com a fonte, ou None se o Eikos não responder."""
    estado = f"TEXTO-FONTE OFICIAL:\n{texto_fonte[:1500]}\n\nRESUMO PUBLICADO:\n{resumo}"
    a = eikos.avaliar(estado, CONFERE_Q)
    if not a or any(k not in a or a[k].get("value") is None for k in CONFERE_Q):
        return None
    alertas = []
    for k in ("inventou", "opiniao", "numeros"):
        ruim = (not a[k]["value"]) if k == "numeros" else bool(a[k]["value"])
        if ruim: alertas.append((ROTULOS[k], float(a[k].get("confidence") or 0)))
    return {"conferido": not alertas, "alertas": [m for m, _ in alertas],
            "conf": round(max([c for _, c in alertas], default=0.0), 3)}


def fila_de_revisao(resumos):
    """Imprime quem ficou com alerta, do mais confiante ao menos."""
    com = [(v.get("conf") or 0, k, v) for k, v in resumos.items() if v.get("alertas")]
    checados = sum(1 for v in resumos.values() if "conferido" in v)
    print(f"\nfila de revisão: {len(com)} com alerta, de {checados} conferidos ({len(resumos)} em cache)")
    for c, k, v in sorted(com, key=lambda x: -x[0]):
        marca = " " if c >= eikos.CORTE_CONFIANCA else "?"
        print(f"  {marca}[{c:.2f}] {v.get('title')} — {', '.join(v['alertas'])}")
    if com: print("  ? = abaixo do corte de confiança do Eikos; olhe antes de tirar do ar.")


def _gen_culturabuilder(model):
    import subprocess
    def gen(text):
        prompt = f"{SYSTEM}\n\nTexto-fonte:\n{text}\n\nEscreva o resumo em linguagem simples."
        r = subprocess.run([CB_BIN, "run", "-m", model, "--format", "json", "--title", "atlas-resumos", prompt],
                           capture_output=True, text=True, timeout=180)
        if r.returncode != 0: raise RuntimeError((r.stderr or r.stdout)[-300:])
        parts = []
        for line in r.stdout.splitlines():
            line = line.strip()
            if not line.startswith("{"): continue
            try: ev = json.loads(line)
            except ValueError: continue
            if ev.get("type") == "text": parts.append(((ev.get("part") or {}).get("text") or ""))
        return "\n".join(parts).strip()
    return gen


def _gen_anthropic(model):
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    def gen(text):
        msg = client.messages.create(model=model, max_tokens=300, system=SYSTEM,
                                     messages=[{"role": "user", "content": f"Texto-fonte:\n{text}\n\nEscreva o resumo em linguagem simples."}])
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
    return gen


def _provider():
    """(função geradora, nome do modelo) conforme RESUMOS_PROVIDER e o que existe na máquina."""
    want = PROVIDER
    has_cb = pathlib.Path(CB_BIN).exists() if CB_BIN else False
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if want in ("auto", "culturabuilder") and has_cb:
        m = MODEL or "builder-ai/builder-fast"; return _gen_culturabuilder(m), f"culturabuilder:{m}"
    if want in ("auto", "anthropic") and has_key:
        try:
            m = MODEL or "claude-sonnet-5"; return _gen_anthropic(m), f"anthropic:{m}"
        except ImportError:
            print("sdk anthropic não instalado: pip install anthropic")
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=400)
    ap.add_argument("--force", action="append", default=[])
    ap.add_argument("--conferir", action="store_true", help="confere os resumos já em cache, sem gerar nada")
    args = ap.parse_args()
    _load_env()
    cache = _yaml(OUT) or {}
    resumos = dict(cache.get("resumos") or {})
    todos = items()
    por_id = {it["id"]: it for it in todos}
    todo = [it for it in todos if it["id"] in args.force or resumos.get(it["id"], {}).get("hash") != it["hash"]]
    print(f"itens: {len(todos)} · em cache: {len(resumos)} · pendentes: {len(todo)}")
    if args.conferir:
        return _conferir_cache(resumos, por_id, cache.get("modelo"), args.force)
    if args.dry_run:
        for it in todo[:5]:
            print("---", it["id"]); print(it["text"])
        return 0
    if not todo:
        fila_de_revisao(resumos)
        return 0
    gen, modelo = _provider()
    if not gen:
        print("nenhum provedor disponível (culturabuilder no PATH ou ANTHROPIC_API_KEY): resumos não gerados; o site segue com os já existentes")
        fila_de_revisao(resumos)
        return 0
    print(f"provedor: {modelo}")
    done = 0
    for it in todo[: args.limit]:
        try:
            text = gen(it["text"])
        except Exception as e:  # noqa: BLE001
            print(f"  falhou {it['id']}: {e}"); time.sleep(2); continue
        if not text or len(text) > 700:
            print(f"  descartado {it['id']} (tamanho {len(text)})"); continue
        reg = {"kind": it["kind"], "title": it["title"], "resumo": text, "hash": it["hash"],
               "modelo": modelo, "gerado_em": datetime.date.today().isoformat()}
        # confere contra o texto-fonte antes de entrar no cache; sem chave/erro, entra sem os campos
        c = conferir(it["text"], text) if eikos.disponivel() else None
        if c: reg.update(c)
        resumos[it["id"]] = reg
        done += 1
        aviso = "" if not c else ("" if c["conferido"] else f"  ⚠ {', '.join(c['alertas'])} [{c['conf']:.2f}]")
        print(f"  ok {it['id']}: {text[:90]}…{aviso}")
        time.sleep(0.3)
    _escrever({it["id"] for it in todos}, resumos, modelo)
    print(f"gerados agora: {done} · total em cache: {len(resumos)} → {OUT}")
    g = eikos.gasto()
    print(f"gasto Eikos: {g['chamadas']} chamadas, {g['tokens']} tokens de entrada, {g['erros']} erros")
    fila_de_revisao(resumos)
    return 0


def _escrever(current, resumos, modelo):
    """Grava resumos.yaml mantendo só itens ainda existentes. Modifica `resumos` no lugar."""
    for k in [k for k in resumos if k not in current]: del resumos[k]
    body = yaml.dump({"generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                      "modelo": modelo, "aviso": "Resumos gerados automaticamente por modelo de linguagem; podem conter erros. A ementa oficial prevalece.",
                      "total": len(resumos), "resumos": resumos}, allow_unicode=True, sort_keys=False, width=120)
    OUT.write_text("# GERADO por etl/resumos.py. Não edite à mão.\n" + body)


def _conferir_cache(resumos, por_id, modelo, force):
    """--conferir: roda a checagem nos resumos já em cache (sem gerar nada) e imprime a fila."""
    if not eikos.disponivel():
        print("sem EIKOS_KEY: nada conferido; o arquivo segue como está")
        fila_de_revisao(resumos); return 0
    alvos = []
    for rid, r in resumos.items():
        if "conferido" in r and rid not in force: continue
        src = por_id.get(rid) or next((v for v in por_id.values() if v["title"] == r.get("title")), None)
        if src: alvos.append((rid, r, src))
        else: print(f"  sem texto-fonte para {rid} ({r.get('title')}): não dá para conferir")
    print(f"a conferir: {len(alvos)}")
    falhas = 0
    for rid, r, src in alvos:
        c = conferir(src["text"], r.get("resumo") or "")
        if not c:
            falhas += 1
            if falhas >= 5: print("5 falhas no Eikos, desistindo desta execução", file=sys.stderr); break
            continue
        r.update(c)
    _escrever(set(por_id), resumos, modelo)
    g = eikos.gasto()
    print(f"conferidos agora: {len(alvos) - falhas}" + (f" · falhas={falhas}" if falhas else "") + f" → {OUT}")
    print(f"gasto Eikos: {g['chamadas']} chamadas, {g['tokens']} tokens de entrada, {g['erros']} erros")
    fila_de_revisao(resumos)
    return 0


if __name__ == "__main__":
    sys.exit(main())
