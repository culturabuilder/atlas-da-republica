#!/usr/bin/env python3
"""Diário Oficial da União, Seção 2 → data/generated/dou.json (acumula por dia).

Busca pública do in.gov.br (sem cadastro), filtrada por órgão principal (orgPrin) e dia. Para cada ato de
nomeação/exoneração/designação cujo trecho cita um cargo de chefia, baixa o texto integral, extrai pessoa e
cargo e casa o cargo com um cargo do grafo. Cobertura: só o que a busca devolve por dia (20 por consulta),
por isso as consultas são por órgão. O INLABS (XML completo) substitui isto quando houver cadastro.
Uso: .venv/bin/python etl/dou.py [--date dia]  (dia = hoje por padrão; a busca do portal só filtra por dia corrente,
semana, mês ou ano, então --date serve apenas para rotular)
"""
import json, re, sys, html, pathlib, datetime, urllib.request, urllib.parse, unicodedata, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from sabatinas import build_index, match_position, norm
ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "generated" / "dou.json"
UA = {"User-Agent": "Mozilla/5.0 atlas-da-republica/0.1"}
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

def get(url):
    for i in range(3):
        try: return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90).read().decode("utf-8", "ignore")
        except Exception as e: time.sleep(2)
    return ""

def search(q, org):
    u = "https://www.in.gov.br/consulta/-/buscar/dou?" + urllib.parse.urlencode({"q": q, "s": "do2", "exactDate": "dia", "sortType": "0", "orgPrin": org})
    h = get(u); m = re.search(r'<script[^>]*id="_br_com_seatecnologia_in_buscadou_BuscaDouPortlet_params"[^>]*>(.*?)</script>', h, re.S)
    try: return json.loads(m.group(1)).get("jsonArray", []) if m else []
    except Exception: return []

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
    graph = json.load(open(ROOT / "build" / "graph.br.json", encoding="utf-8")); idx = build_index(graph)
    store = json.load(open(OUT, encoding="utf-8")) if OUT.exists() else {"acts": {}}
    today = datetime.date.today().isoformat(); seen = 0; new = 0; fetched = 0
    for org in ORGS:
        for v in VERBS:
            for it in search(v, org):
                seen += 1
                key = it["urlTitle"]
                if key in store["acts"]: continue
                snippet = re.sub(r"<[^>]+>", " ", it.get("content") or "")
                if not CARGO_RX.search(snippet) and not re.search(r"Decreto", it.get("artType") or "", re.I): continue
                text = act_text(key); fetched += 1
                acts = parse_acts(text)
                if not acts: continue
                d = it.get("pubDate", "")
                date = f"{d[6:10]}-{d[3:5]}-{d[0:2]}" if re.match(r"\d\d/\d\d/\d{4}", d) else today
                recs = []
                for verb, name, cargo, org_txt in acts:
                    pid, sc = match_position(cargo + (" " + org_txt if org_txt else ""), idx, graph)
                    recs.append({"verb": verb, "name": name, "cargo": cargo, "org_text": org_txt, "position_id": pid, "match_score": sc})
                store["acts"][key] = {"id": key, "date": date, "title": it.get("title"), "artType": it.get("artType"), "hierarchy": it.get("hierarchyList"),
                                      "url": "https://www.in.gov.br/web/dou/-/" + key, "records": recs, "org_query": org}
                new += 1
        json.dump(store, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    store["updated_at"] = today; json.dump(store, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    linked = sum(1 for a in store["acts"].values() for r in a["records"] if r["position_id"])
    print(f"resultados vistos={seen} atos baixados={fetched} atos novos={new} total atos={len(store['acts'])} registros casados com cargo={linked}")
    for a in list(store["acts"].values())[-6:]:
        for r in a["records"][:2]: print("  -", a["date"], r["verb"], r["name"], "|", r["cargo"][:60], "->", r["position_id"], r["match_score"])

if __name__ == "__main__": main()
