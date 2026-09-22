#!/usr/bin/env python3
"""Diário Oficial da União, Seção 2 → data/generated/dou.json (acumula por dia).

Busca pública do in.gov.br (sem cadastro). Para cada verbo (NOMEAR, EXONERAR, DESIGNAR, DISPENSAR) percorre TODAS as
páginas de resultado do período usando o cursor da própria busca (newPage + score/id/displayDate do último resultado),
20 resultados por página. Para cada ato cujo trecho cita um cargo de chefia, baixa o texto integral, extrai pessoa e
cargo e casa o cargo com um cargo do grafo.
Uso: .venv/bin/python etl/dou.py                      (edição de hoje)
     .venv/bin/python etl/dou.py --from 2026-09-01 --to 2026-09-18   (período; usado para recuperar dias perdidos)
     .venv/bin/python etl/dou.py --max-pages 40
     .venv/bin/python etl/dou.py --backfill            (varredura retroativa desde 1º/1/2023, janelas mensais)

--backfill: percorre mês a mês (do mais recente para o mais antigo) as buscas de NOMEAR e DESIGNAR, guardando o
resultado bruto de cada janela em build/cache-dou/<AAAA-MM>-<verbo>.json e o texto de cada ato em
build/cache-dou/textos/. Retoma de onde parou (janela já cacheada não é buscada de novo), grava dou.json a cada
janela, respeita --pause (≥0,5 s entre requisições) e recua exponencialmente em 429/5xx.

VOLUME OBSERVADO (medido em 22/9/2026, Seção 2): janeiro/2023 tem 85 páginas de NOMEAR, 201 de DESIGNAR e 66 de
EXONERAR — ~350 páginas de listagem por mês, ~16 mil requisições só de listagem para os 45 meses desde 2023, sem
contar o texto integral de cada ato. A varredura completa é, portanto, de dezenas de horas; --max-pages limita as
páginas por janela (padrão 40) e a varredura fica enviesada para os atos mais recentes de cada mês. Para descobrir
a data de posse de uma pessoa específica o caminho barato é etl/posses.py, que busca o nome entre aspas (uma
consulta cobre todo o período, ~1 s) em vez de varrer o diário inteiro.
"""
import json, re, sys, html, pathlib, datetime, urllib.request, urllib.error, urllib.parse, unicodedata, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from sabatinas import build_index, match_position, norm
ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "generated" / "dou.json"
CACHE = ROOT / "build" / "cache-dou"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36", "Accept": "text/html,*/*;q=0.8", "Accept-Language": "pt-BR,pt;q=0.9"}
ORGS = ["Presidência da República", "Ministério da Fazenda", "Ministério da Justiça e Segurança Pública", "Ministério da Saúde", "Ministério da Educação",
        "Ministério da Defesa", "Ministério das Relações Exteriores", "Ministério de Minas e Energia", "Ministério da Gestão e da Inovação em Serviços Públicos",
        "Ministério do Planejamento e Orçamento", "Ministério do Desenvolvimento, Indústria, Comércio e Serviços", "Ministério da Agricultura e Pecuária",
        "Ministério do Meio Ambiente e Mudança do Clima", "Ministério dos Transportes", "Ministério de Portos e Aeroportos", "Ministério das Comunicações",
        "Ministério da Ciência, Tecnologia e Inovação", "Ministério do Trabalho e Emprego", "Ministério da Previdência Social", "Ministério das Cidades",
        "Ministério da Integração e do Desenvolvimento Regional", "Ministério do Desenvolvimento e Assistência Social, Família e Combate à Fome",
        "Ministério dos Direitos Humanos e da Cidadania", "Ministério da Cultura", "Ministério do Esporte", "Ministério do Turismo", "Ministério das Mulheres",
        "Ministério da Igualdade Racial", "Ministério dos Povos Indígenas", "Ministério do Desenvolvimento Agrário e Agricultura Familiar", "Ministério da Pesca e Aquicultura",
        "Ministério do Empreendedorismo, da Microempresa e da Empresa de Pequeno Porte", "Controladoria-Geral da União", "Banco Central do Brasil",
        "Ministério Público da União", "Defensoria Pública da União", "Tribunal de Contas da União", "Poder Judiciário", "Poder Legislativo", "Entidades de Fiscalização do Exercício das Profissões Liberais"]
VERBS = ["NOMEAR", "EXONERAR", "DESIGNAR", "DISPENSAR"]
CARGO_RX = re.compile(r"Ministro de Estado|Presidente d|Diretor[a]?(?:-Geral|-Presidente| d)|Secret[áa]ri[oa](?:-Executiv[oa]| Nacional| Especial| de Estado)|Procurador[a]?-Geral|Defensor[a]? P[úu]blic[oa]-Geral|Comandante d|Chefe d[oa] (?:Casa|Gabinete|Secretaria)|Advogad[oa]-Geral|Superintendente|Conselheir[oa] d|Membro d[oa] Conselho|Ministr[oa] d[oa] (?:Supremo|Superior|Tribunal)", re.I)

BLOCKED = {"n": 0}
PAUSE = {"s": 2.5}          # segundos entre requisições (>= 0,5); --backfill baixa para --pause
def get(url):
    """Uma requisição por PAUSE segundos; recua exponencialmente em 429/5xx; três consultas vazias seguidas abortam (bloqueio por IP)."""
    time.sleep(max(0.5, PAUSE["s"]))
    for i in range(4):
        try:
            h = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90).read().decode("utf-8", "ignore")
            if h: BLOCKED["n"] = 0; return h
            wait = 5 * (i + 1)
        except urllib.error.HTTPError as e:
            wait = min(180, 15 * (2 ** i)) if e.code == 429 or e.code >= 500 else 5 * (i + 1)
            print(f"    HTTP {e.code}; aguardando {wait}s", file=sys.stderr, flush=True)
        except Exception:
            wait = 5 * (i + 1)
        time.sleep(wait)
    BLOCKED["n"] += 1
    if BLOCKED["n"] >= 3: sys.exit("in.gov.br sem resposta em 3 consultas seguidas: provável bloqueio temporário; tente mais tarde")
    return ""

def search_all(q, date_from=None, date_to=None, max_pages=60):
    """Gera todos os resultados de uma consulta, página a página (cursor da busca do portal)."""
    base = {"q": q, "s": "do2", "sortType": "0", "delta": "20"}
    if date_from: base.update({"exactDate": "personalizado", "publishFrom": date_from.strftime("%d/%m/%Y"), "publishTo": (date_to or date_from).strftime("%d/%m/%Y")})
    else: base["exactDate"] = "dia"
    page, cursor, seen = 1, {}, set()
    while page <= max_pages:
        h = get("https://www.in.gov.br/consulta/-/buscar/dou?" + urllib.parse.urlencode(dict(base, **cursor)))
        m = re.search(r'<script[^>]*id="_br_com_seatecnologia_in_buscadou_BuscaDouPortlet_params"[^>]*>(.*?)</script>', h, re.S)
        try: hits = json.loads(m.group(1)).get("jsonArray", []) if m else []
        except Exception: hits = []
        tp = re.search(r"totalPages\s*:\s*(\d+)", h); total = int(tp.group(1)) if tp else 1
        fresh = [x for x in hits if x.get("urlTitle") not in seen]
        print(f"  {q}: página {page}/{total}, {len(fresh)} resultados", file=sys.stderr, flush=True)
        if not fresh: break
        for x in fresh: seen.add(x["urlTitle"]); yield x
        if page >= total: break
        last = hits[-1]; cursor = {"currentPage": page, "newPage": page + 1, "score": last.get("score", 0), "id": last.get("classPK"), "displayDate": last.get("displayDateSortable")}
        page += 1

def act_text(url_title, cache_dir=None):
    """Texto integral do ato; com cache_dir guarda/reaproveita build/cache-dou/textos/<urlTitle>.txt."""
    f = (cache_dir / "textos" / (url_title[:150] + ".txt")) if cache_dir else None
    if f and f.exists(): return f.read_text(encoding="utf-8")
    h = get("https://www.in.gov.br/web/dou/-/" + url_title)
    m = re.search(r'<div[^>]*class="texto-dou"[^>]*>(.*?)<div class="rodape', h, re.S) or re.search(r'<p class="identifica">(.*?)<p class="assina">', h, re.S)
    t = html.unescape(re.sub(r"<[^>]+>", " ", m.group(1) if m else h))
    t = re.sub(r"\s+", " ", t).strip()
    if f and t: f.parent.mkdir(parents=True, exist_ok=True); f.write_text(t, encoding="utf-8")
    return t

def parse_acts(text):
    """Devolve lista de (verbo, pessoa, cargo, órgão-trecho)."""
    out = []
    for m in re.finditer(r"\b(NOMEAR|EXONERAR|DESIGNAR|DISPENSAR)\b[,:]?\s+(?:a pedido,\s*)?(?:o[ s]|a[ s]|os|as)?\s*(?:Senhor[a]?|Sr[a]?\.?|Doutor[a]?)?\s*([A-ZÁ-Ú][A-ZÁ-Ú'\-\. ]{5,}?)(?:,|\s+(?:para|do|da|de))", text):
        verb, name = m.group(1), m.group(2).strip(" ,.")
        tail = text[m.end(): m.end() + 400]
        c = re.search(r"(?:do|para exercer o|para o|no|para ocupar o) cargo (?:de|em comissão de)\s+(.+?)(?:,|\.| c[óo]digo| CCE| FCE| DAS| n[ií]vel|$)", tail, re.I) or re.search(r"(?:para exercer a|da|a) fun[çc][ãa]o de\s+(.+?)(?:,|\.| c[óo]digo| CCE| FCE| FCPE|$)", tail, re.I) or re.search(r"(?:como|do cargo de|para o cargo de)\s+(.+?)(?:,|\.|$)", tail, re.I)
        cargo = c.group(1).strip() if c else None
        if not cargo or not CARGO_RX.search(cargo): continue
        org = re.search(r"d[oa]s? ([A-ZÁ-Ú][\w\-\.]*(?: (?:d[oa]s?|e|de) ?[A-ZÁ-Ú][\w\-\.]*)+)", tail[len(c.group(0)) if c else 0:][:200])
        out.append((verb, " ".join(w.capitalize() if len(w) > 2 else w.lower() for w in name.split()), cargo[:160], org.group(1) if org else None))
    return out

def handle_hit(it, verb_query, store, idx, graph, today, cache_dir=None):
    """Baixa, interpreta e guarda um resultado da busca em store['acts']. Devolve (baixou?, novo?)."""
    key = it["urlTitle"]
    if key in store["acts"]: return False, False
    snippet = re.sub(r"<[^>]+>", " ", html.unescape(it.get("content") or "")) + " " + (it.get("title") or "")
    if not CARGO_RX.search(snippet) and not re.search(r"Decreto", it.get("artType") or "", re.I): return False, False
    text = act_text(key, cache_dir)
    acts = parse_acts(text)
    if not acts:
        store["acts"][key] = {"id": key, "date": today, "title": it.get("title"), "records": [], "skipped": True}  # lembra para não baixar de novo
        return True, False
    print(f"    + {it.get('title','')[:60]} ({len(acts)} registros)", file=sys.stderr, flush=True)
    d = it.get("pubDate", "")
    date = f"{d[6:10]}-{d[3:5]}-{d[0:2]}" if re.match(r"\d\d/\d\d/\d{4}", d) else today
    recs = []
    for verb, name, cargo, org_txt in acts:
        pid, sc = match_position(cargo + (" " + org_txt if org_txt else ""), idx, graph)
        # no DOU o casamento exige papel igual (Diretor de departamento nunca vira Ministro) e score alto
        role = lambda t: (re.match(r"(ministr|president|diretor president|diretor geral|diretor|conselheir|procurador|defensor|superintendent|membro|advogad|comandante|secretari)", norm(t)) or [None])[0]
        if pid and (sc < 0.75 or role(cargo) != role(graph["nodes"][pid]["name"])): pid, sc = None, sc
        recs.append({"verb": verb, "name": name, "cargo": cargo, "org_text": org_txt, "position_id": pid, "match_score": sc})
    store["acts"][key] = {"id": key, "date": date, "title": it.get("title"), "artType": it.get("artType"), "hierarchy": it.get("hierarchyList"),
                          "url": "https://www.in.gov.br/web/dou/-/" + key, "records": recs, "verb_query": verb_query}
    return True, True

def months(dfrom, dto):
    """Janelas mensais (primeiro..último dia do mês) do mais recente para o mais antigo."""
    out, y, m = [], dto.year, dto.month
    while (y, m) >= (dfrom.year, dfrom.month):
        first = datetime.date(y, m, 1)
        last = datetime.date(y + (m == 12), m % 12 + 1, 1) - datetime.timedelta(days=1)
        out.append((max(first, dfrom), min(last, dto)))
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return out

def backfill(dfrom, dto, max_pages, store, idx, graph, verbs=("NOMEAR", "DESIGNAR")):
    """Varredura retroativa em janelas mensais, com cache por janela em build/cache-dou/ para poder retomar."""
    CACHE.mkdir(parents=True, exist_ok=True)
    today = datetime.date.today().isoformat()
    done = set(store.setdefault("backfill", {}).setdefault("windows", []))
    tot_hits = tot_new = 0
    for wfrom, wto in months(dfrom, dto):
        tag = wfrom.strftime("%Y-%m")
        for v in verbs:
            wkey = f"{tag}-{v}"
            cf = CACHE / f"{wkey}.json"
            t0 = time.time()
            if cf.exists():
                hits = json.load(open(cf, encoding="utf-8"))
                print(f"[{wkey}] cache: {len(hits)} resultados", file=sys.stderr, flush=True)
            else:
                hits = list(search_all(v, wfrom, wto, max_pages))
                json.dump(hits, open(cf, "w", encoding="utf-8"), ensure_ascii=False)
                print(f"[{wkey}] busca: {len(hits)} resultados em {time.time()-t0:.0f}s", file=sys.stderr, flush=True)
            if wkey in done: continue
            new = 0
            for it in hits:
                _, n = handle_hit(it, v, store, idx, graph, today, CACHE)
                new += n
            tot_hits += len(hits); tot_new += new
            store["backfill"]["windows"].append(wkey)
            store["backfill"].update({"from": dfrom.isoformat(), "to": dto.isoformat(), "updated_at": today})
            store["updated_at"] = today
            json.dump(store, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
            print(f"[{wkey}] {new} atos novos ({time.time()-t0:.0f}s); total de atos no arquivo: {len(store['acts'])}", file=sys.stderr, flush=True)
    return tot_hits, tot_new

def main():
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument("--from", dest="dfrom"); ap.add_argument("--to", dest="dto"); ap.add_argument("--max-pages", type=int, default=60)
    ap.add_argument("--backfill", action="store_true", help="varredura retroativa mês a mês desde --from (padrão 2023-01-01)")
    ap.add_argument("--pause", type=float, default=None, help="segundos entre requisições (mínimo 0,5; padrão 2,5, ou 0,8 no --backfill)")
    a = ap.parse_args()
    dfrom = datetime.date.fromisoformat(a.dfrom) if a.dfrom else None; dto = datetime.date.fromisoformat(a.dto) if a.dto else dfrom
    if a.pause: PAUSE["s"] = a.pause
    graph = json.load(open(ROOT / "build" / "graph.br.json", encoding="utf-8")); idx = build_index(graph)
    store = json.load(open(OUT, encoding="utf-8")) if OUT.exists() else {"acts": {}}
    today = datetime.date.today().isoformat(); seen = 0; new = 0; fetched = 0
    if a.backfill:
        if a.pause is None: PAUSE["s"] = 0.8
        seen, new = backfill(dfrom or datetime.date(2023, 1, 1), dto or datetime.date.today(), a.max_pages if a.max_pages != 60 else 40, store, idx, graph)
    else:
        for v in VERBS:
            for it in search_all(v, dfrom, dto, a.max_pages):
                seen += 1
                f, n = handle_hit(it, v, store, idx, graph, today)
                fetched += f; new += n
                if f and fetched % 5 == 0: json.dump(store, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    store["updated_at"] = today; json.dump(store, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    linked = sum(1 for a in store["acts"].values() for r in a["records"] if r["position_id"])
    print(f"resultados vistos={seen} atos baixados={fetched} atos novos={new} total atos={len(store['acts'])} registros casados com cargo={linked}")
    for a in list(store["acts"].values())[-6:]:
        for r in a["records"][:2]: print("  -", a["date"], r["verb"], r["name"], "|", r["cargo"][:60], "->", r["position_id"], r["match_score"])

if __name__ == "__main__": main()
