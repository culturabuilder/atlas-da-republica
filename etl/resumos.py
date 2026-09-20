#!/usr/bin/env python3
"""Resumos em linguagem simples (Claude API) para MPs, vetos, pedidos de CPI e temas.

Lê `data/generated/omissao.yaml` e `data/generated/temas.yaml`, monta um texto-fonte por item
(ementa oficial + situação + prazo), e pede a um modelo Claude um resumo de 2 a 3 frases em
português claro, sem opinião. Cada resumo é gravado em `data/generated/resumos.yaml` com o hash
do texto-fonte; só é regenerado quando a ementa/situação muda. Sem `ANTHROPIC_API_KEY` no
ambiente ou em `.env`, o script mantém o arquivo como está e sai sem erro (o site mostra só a
ementa oficial).

Uso:
  python etl/resumos.py                # gera o que falta (respeita cache)
  python etl/resumos.py --dry-run      # mostra os itens pendentes e o prompt, sem chamar a API
  python etl/resumos.py --limit 20     # no máximo N chamadas nesta execução
  python etl/resumos.py --force ID     # regenera um item

Variáveis: ANTHROPIC_API_KEY (obrigatória para gerar), RESUMOS_MODEL (padrão: claude-sonnet-5).
Custo: ~600 tokens de entrada + ~150 de saída por item; ~120 itens ≈ centavos de dólar.
"""
import argparse, datetime, hashlib, os, pathlib, sys, time
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
GEN = ROOT / "data" / "generated"
OUT = GEN / "resumos.yaml"
MODEL = os.environ.get("RESUMOS_MODEL", "claude-sonnet-5")
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
                 f"Editada em {m.get('date')}; tramita há {m.get('days')} dias; prazo final {m.get('deadline')}"
                 + (f" (faltam {m.get('days_left')} dias)" if m.get("days_left") is not None else ""),
                 f"Situação no Congresso: {m.get('status')}"]
        if m.get("value") and float(m["value"]) >= 1000:
            parts.append(f"Valor envolvido: {_brl(m['value'])}")
        if m.get("prorogued"):
            parts.append("Já foi prorrogada uma vez (o prazo de 60 dias virou 120).")
        out.append({"id": m["id"], "kind": "mpv", "title": m.get("title"), "text": "\n".join(p for p in parts if p)})
    for v in vetos:
        parts = [f"{v.get('title')} ao projeto {v.get('materia')}, que virou a {v.get('norma')}",
                 f"Ementa oficial: {v.get('summary')}",
                 f"Veto publicado em {v.get('date')}; espera apreciação do Congresso há {v.get('days')} dias "
                 f"(a Constituição dá 30 dias para o Congresso decidir se mantém ou derruba o veto)."]
        out.append({"id": v["id"], "kind": "veto", "title": v.get("title"), "text": "\n".join(p for p in parts if p)})
    for r in rcps:
        parts = [f"Pedido de CPI {r.get('title')} na Câmara dos Deputados",
                 f"Texto oficial do requerimento: {r.get('summary')}",
                 f"Protocolado em {r.get('date')}, há {r.get('days')} dias; tem {r.get('signatures')} assinaturas "
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
                 f"Estado atual: {t.get('state')}" + (f"; sem andamento há {t.get('stalled_days')} dias" if t.get("stalled_days") else "")]
        for p in (t.get("processes") or [])[:3]:
            parts.append(f"Processo {p.get('id')} ({p.get('casa')}): {str(p.get('ementa') or '')[:400]} — situação: {p.get('situation')}; último andamento {p.get('last_move')}")
        out.append({"id": f"tema-{t['id']}", "kind": "tema", "title": t.get("name"), "text": "\n".join(p for p in parts if p)})
    for it in out:
        it["text"] = it["text"][:MAX_TEXT]
        it["hash"] = hashlib.sha1(it["text"].encode()).hexdigest()[:12]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=400)
    ap.add_argument("--force", action="append", default=[])
    args = ap.parse_args()
    _load_env()
    cache = _yaml(OUT) or {}
    resumos = dict(cache.get("resumos") or {})
    todo = [it for it in items() if it["id"] in args.force or resumos.get(it["id"], {}).get("hash") != it["hash"]]
    print(f"itens: {len(items())} · em cache: {len(resumos)} · pendentes: {len(todo)}")
    if args.dry_run:
        for it in todo[:5]:
            print("---", it["id"]); print(it["text"])
        return 0
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not todo:
        return 0
    if not key:
        print("sem ANTHROPIC_API_KEY: resumos não gerados (o site segue com as ementas oficiais)")
        return 0
    try:
        import anthropic
    except ImportError:
        print("sdk anthropic não instalado: pip install anthropic"); return 0
    client = anthropic.Anthropic(api_key=key)
    done = 0
    for it in todo[: args.limit]:
        try:
            msg = client.messages.create(model=MODEL, max_tokens=300, system=SYSTEM,
                                         messages=[{"role": "user", "content": f"Texto-fonte:\n{it['text']}\n\nEscreva o resumo em linguagem simples."}])
            text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
        except Exception as e:  # noqa: BLE001
            print(f"  falhou {it['id']}: {e}"); time.sleep(2); continue
        if not text or len(text) > 700:
            print(f"  descartado {it['id']} (tamanho {len(text)})"); continue
        resumos[it["id"]] = {"kind": it["kind"], "title": it["title"], "resumo": text, "hash": it["hash"],
                             "modelo": MODEL, "gerado_em": datetime.date.today().isoformat()}
        done += 1
        print(f"  ok {it['id']}: {text[:90]}…")
        time.sleep(0.3)
    # mantém só itens ainda existentes + os gerados
    current = {it["id"] for it in items()}
    resumos = {k: v for k, v in resumos.items() if k in current}
    body = yaml.dump({"generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                      "modelo": MODEL, "aviso": "Resumos gerados automaticamente por modelo de linguagem; podem conter erros. A ementa oficial prevalece.",
                      "total": len(resumos), "resumos": resumos}, allow_unicode=True, sort_keys=False, width=120)
    OUT.write_text("# GERADO por etl/resumos.py. Não edite à mão.\n" + body)
    print(f"gerados agora: {done} · total em cache: {len(resumos)} → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
