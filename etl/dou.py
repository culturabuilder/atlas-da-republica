#!/usr/bin/env python3
"""Diário Oficial da União, Seção 2 → data/generated/dou.json (acumula por dia).

Busca pública do in.gov.br (sem cadastro). Para cada verbo (NOMEAR, EXONERAR, DESIGNAR, DISPENSAR) percorre TODAS as
páginas de resultado do período usando o cursor da própria busca (newPage + score/id/displayDate do último resultado),
20 resultados por página. Para cada ato cujo trecho cita um cargo de chefia, baixa o texto integral, extrai pessoa e
cargo e casa o cargo com um cargo do grafo.
Uso: .venv/bin/python etl/dou.py                      (edição de hoje)
     .venv/bin/python etl/dou.py --from 2026-09-01 --to 2026-09-18   (período; usado para recuperar dias perdidos)
     .venv/bin/python etl/dou.py --max-pages 40
"""
import json, re, sys, html, pathlib, datetime, urllib.request, urllib.parse, unicodedata, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from sabatinas import build_index, match_position, norm
ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "generated" / "dou.json"
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
def get(url):
    """Uma requisição a cada 2,5 s; se o portal responder vazio/erro três vezes seguidas, aborta a execução (bloqueio por IP)."""
    time.sleep(2.5)
    for i in range(3):
        try:
            h = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90).read().decode("utf-8", "ignore")
            if h: BLOCKED["n"] = 0; return h
        except Exception as e: pass
        time.sleep(5 * (i + 1))
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

def act_text(url_title):
    h = get("https://www.in.gov.br/web/dou/-/" + url_title)
    m = re.search(r'<div[^>]*class="texto-dou"[^>]*>(.*?)<div class="rodape', h, re.S) or re.search(r'<p class="identifica">(.*?)<p class="assina">', h, re.S)
    t = html.unescape(re.sub(r"<[^>]+>", " ", m.group(1) if m else h))
    return re.sub(r"\s+", " ", t).strip()

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

def main():
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument("--from", dest="dfrom"); ap.add_argument("--to", dest="dto"); ap.add_argument("--max-pages", type=int, default=60); a = ap.parse_args()
    dfrom = datetime.date.fromisoformat(a.dfrom) if a.dfrom else None; dto = datetime.date.fromisoformat(a.dto) if a.dto else dfrom
    graph = json.load(open(ROOT / "build" / "graph.br.json", encoding="utf-8")); idx = build_index(graph)
    store = json.load(open(OUT, encoding="utf-8")) if OUT.exists() else {"acts": {}}
    today = datetime.date.today().isoformat(); seen = 0; new = 0; fetched = 0
    for v in VERBS:
        for it in search_all(v, dfrom, dto, a.max_pages):
            seen += 1
            key = it["urlTitle"]
            if key in store["acts"]: continue
            snippet = re.sub(r"<[^>]+>", " ", html.unescape(it.get("content") or "")) + " " + (it.get("title") or "")
            if not CARGO_RX.search(snippet) and not re.search(r"Decreto", it.get("artType") or "", re.I): continue
            text = act_text(key); fetched += 1
            acts = parse_acts(text)
            if not acts:
                store["acts"][key] = {"id": key, "date": today, "title": it.get("title"), "records": [], "skipped": True}  # lembra para não baixar de novo
                continue
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
                                  "url": "https://www.in.gov.br/web/dou/-/" + key, "records": recs, "verb_query": v}
            new += 1
            if fetched % 5 == 0: json.dump(store, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    store["updated_at"] = today; json.dump(store, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    linked = sum(1 for a in store["acts"].values() for r in a["records"] if r["position_id"])
    print(f"resultados vistos={seen} atos baixados={fetched} atos novos={new} total atos={len(store['acts'])} registros casados com cargo={linked}")
    for a in list(store["acts"].values())[-6:]:
        for r in a["records"][:2]: print("  -", a["date"], r["verb"], r["name"], "|", r["cargo"][:60], "->", r["position_id"], r["match_score"])

if __name__ == "__main__": main()
