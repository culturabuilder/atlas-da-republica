#!/usr/bin/env python3
"""Temas quentes × andamento dos processos → data/generated/temas.yaml.

Para cada tema de data/temas.yaml:
  - atenção: notícias do Atlas por semana (palavras-chave no título e resumo) e visitas diárias ao verbete na Wikipédia (API Wikimedia, 90 dias)
  - processos: situação e último andamento na Câmara (/proposicoes, /tramitacoes) e no Senado (/processo); MPs e vetos vêm de omissao.yaml
  - estado calculado: em_movimento (andamento nos últimos 30 dias), aguardando, prazo_vencido, encerrado (aprovado, rejeitado, arquivado, caducou)
  - "silêncio com prazo vencido": atenção caiu mais de 80% do pico por 60 dias, processo pendente, sem andamento no período e prazo passado
Uso: .venv/bin/python etl/temas.py
"""
import json, re, sys, time, pathlib, datetime, unicodedata, urllib.request, urllib.parse, collections
import yaml
ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = {"User-Agent": "Mozilla/5.0 (Macintosh) atlas-da-republica/0.1 (https://atlasdarepublica.org)", "Accept": "application/json"}
TODAY = datetime.date.today()
def norm(s): return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9$/\. ]", " ", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())).strip()
def get(url):
    for i in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90) as r: return json.load(r)
        except Exception as e:
            if i == 2: print("falha", url, e, file=sys.stderr); return None
            time.sleep(2 * (i + 1))
def week(d): 
    dd = datetime.date.fromisoformat(str(d)[:10]); return (dd - datetime.timedelta(days=dd.weekday())).isoformat()

def camara(p):
    d = get(f"https://dadosabertos.camara.leg.br/api/v2/proposicoes?siglaTipo={p['sigla']}&numero={p['numero']}&ano={p['ano']}") or {}
    hits = d.get("dados") or []
    if not hits: return None
    pid = hits[0]["id"]; det = (get(f"https://dadosabertos.camara.leg.br/api/v2/proposicoes/{pid}") or {}).get("dados") or {}
    st = det.get("statusProposicao") or {}; tr = (get(f"https://dadosabertos.camara.leg.br/api/v2/proposicoes/{pid}/tramitacoes") or {}).get("dados") or []
    last = max((t.get("dataHora") or "" for t in tr), default=st.get("dataHora") or "")[:10]
    sit = st.get("descricaoSituacao") or ""; desp = st.get("despacho") or ""
    closed = bool(re.search(r"arquivad|transformad|prejudicad|rejeitad|retirad", sit + " " + desp, re.I))
    return {"casa": "camara", "id": f"{p['sigla']} {p['numero']}/{p['ano']}", "ementa": (det.get("ementa") or "")[:220], "situation": sit, "last_move": last, "organ": st.get("siglaOrgao"),
            "closed": closed, "outcome": sit if closed else None, "url": f"https://www.camara.leg.br/proposicoesWeb/fichadetramitacao?idProposicao={pid}"}

def senado(p):
    d = get(f"https://legis.senado.leg.br/dadosabertos/processo?sigla={p['sigla']}&numero={p['numero']}&ano={p['ano']}") or []
    d = [x for x in d if x.get("casaIdentificadora") in ("SF", "CN")] or d
    if not d: return None
    x = d[0]; sit = (x.get("situacaoAtual") or "").strip()
    closed = x.get("tramitando") == "Não" or bool(re.search(r"REJEITAD|ARQUIVAD|NORMA JUR|PREJUDICAD|RETIRAD|PERDA DE EFIC|ENCERRAD", sit))
    return {"casa": "senado", "id": x.get("identificacao"), "ementa": (x.get("ementa") or "")[:220], "situation": sit.capitalize(), "last_move": (x.get("dataSituacaoAtual") or x.get("dataUltimaAtualizacao") or "")[:10],
            "closed": closed, "outcome": sit.capitalize() if closed else None, "url": f"https://www25.senado.leg.br/web/atividade/materias/-/materia/{x.get('codigoMateria')}"}

def congresso(p, om):
    key = f"{'MPV' if p['sigla']=='MPV' else 'Veto'} {p['numero']}/{p['ano']}"
    for x in (om.get("mpvs") or []) + (om.get("vetos") or []):
        if (x.get("title") or "").replace("MPV ", "MPV ") == key or x.get("title") == key:
            return {"casa": "congresso", "id": x["title"], "ementa": (x.get("summary") or "")[:220], "situation": x.get("status") or ("em tramitação" if x.get("kind") == "veto" else ""), "last_move": x.get("date"),
                    "closed": False, "outcome": None, "deadline": x.get("deadline"), "days_left": x.get("days_left"), "overdue": x.get("overdue"), "url": x.get("url")}
    # MP/veto que não está mais em tramitação: consulta o Senado
    r = senado({"sigla": p["sigla"], "numero": p["numero"], "ano": p["ano"]})
    if r: r["casa"] = "congresso"
    return r

def wiki(article):
    if not article: return None
    start = (TODAY - datetime.timedelta(days=91)).strftime("%Y%m%d"); end = (TODAY - datetime.timedelta(days=1)).strftime("%Y%m%d")
    d = get(f"https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/pt.wikipedia/all-access/user/{urllib.parse.quote(article)}/daily/{start}/{end}") or {}
    items = d.get("items") or []
    if not items: return None
    weekly = collections.OrderedDict()
    for it in items:
        ts = it["timestamp"]; w = week(f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"); weekly[w] = weekly.get(w, 0) + it["views"]
    return {"article": article, "url": f"https://pt.wikipedia.org/wiki/{article}", "weekly": dict(weekly), "total_90d": sum(it["views"] for it in items), "last7": sum(it["views"] for it in items[-7:]), "peak_week": max(weekly.values()) if weekly else 0}

def main():
    temas = yaml.safe_load(open(ROOT / "data" / "temas.yaml", encoding="utf-8")) or []
    om_p = ROOT / "data" / "generated" / "omissao.yaml"; om = yaml.safe_load(open(om_p, encoding="utf-8")) if om_p.exists() else {}
    news = json.load(open(ROOT / "data" / "generated" / "noticias.json", encoding="utf-8")).get("articles") or {}
    arts = list(news.values()) if isinstance(news, dict) else news
    out = []
    for t in temas:
        kws = [norm(k) for k in t.get("keywords") or []]
        hits = [a for a in arts if any(k in norm((a.get("title") or "") + " " + (a.get("summary") or "")) for k in kws)]
        weekly = collections.Counter(week(a["date"]) for a in hits if a.get("date"))
        procs = []
        for p in t.get("processes") or []:
            r = {"camara": camara, "senado": senado}.get(p["casa"], lambda q: congresso(q, om))(p)
            time.sleep(0.3)
            if not r: print(f"aviso: {t['id']}: processo não encontrado {p}", file=sys.stderr); continue
            r["requested"] = f"{p['sigla']} {p['numero']}/{p['ano']} ({p['casa']})"; procs.append(r)
        w = wiki(t.get("wikipedia"))
        # estado do tema = estado do processo mais avançado ainda aberto; se todos fechados, encerrado
        open_ = [p for p in procs if not p.get("closed")]
        def days_since(d):
            try: return (TODAY - datetime.date.fromisoformat(str(d)[:10])).days
            except Exception: return None
        if not procs: state = "sem_processo"
        elif not open_: state = "encerrado"
        else:
            ds = [days_since(p.get("last_move")) for p in open_ if p.get("last_move")]
            overdue = any(p.get("overdue") or (p.get("days_left") is not None and p["days_left"] < 0) for p in open_)
            state = "prazo_vencido" if overdue else ("em_movimento" if ds and min(ds) <= 30 else "parado")
        stalled_days = min((days_since(p.get("last_move")) for p in open_ if p.get("last_move")), default=None)
        # silêncio: pico semanal de atenção (Wikipédia) e as últimas 8 semanas abaixo de 20% do pico
        silence = None
        if w and w["weekly"]:
            wk = list(w["weekly"].values()); peak = max(wk); recent = wk[-8:]
            silence = bool(peak >= 200 and all(v <= 0.2 * peak for v in recent)) if len(wk) >= 10 else False
        flag = bool(silence and state in ("parado", "prazo_vencido") and (stalled_days or 0) >= 60)
        out.append({"id": t["id"], "name": t["name"], "question": t.get("question"), "keywords": t.get("keywords"), "curated": t.get("curated"), "news_hits": len(hits), "news_weekly": dict(sorted(weekly.items())),
                    "news_recent": [{"id": a["id"], "title": a["title"], "date": a["date"], "publication": a.get("publication")} for a in sorted(hits, key=lambda a: a.get("date") or "", reverse=True)[:5]],
                    "wikipedia": w, "processes": procs, "state": state, "stalled_days": stalled_days, "silence_after_peak": silence, "silent_and_stalled": flag})
    data = {"generated_at": TODAY.isoformat(), "temas": out}
    (ROOT / "data" / "generated" / "temas.yaml").write_text("# GERADO por etl/temas.py. Não edite à mão.\n" + yaml.dump(data, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    for t in out: print(f"  {t['id']:28s} {t['state']:14s} parado há {t['stalled_days']} d · notícias {t['news_hits']} · wiki {(t['wikipedia'] or {}).get('total_90d')} (pico sem. {(t['wikipedia'] or {}).get('peak_week')}) · silêncio {t['silence_after_peak']} · processos {[p['id']+':'+(p['situation'] or '')[:25] for p in t['processes']]}")
if __name__ == "__main__": main()
