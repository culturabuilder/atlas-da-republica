#!/usr/bin/env python3
"""Agenda oficial do presidente e do vice-presidente da República (site do Planalto).

O presidente e o vice não estão no e-Agendas (CGU); a agenda deles é publicada no gov.br/planalto,
uma página por dia: `<pasta da agenda>/AAAA-MM-DD`, com itens `.item-compromisso` (hora, título, local).
Não há lista de participantes. O site tem proteção antirrobô que aceita requisições com User-Agent de
navegador nas URLs canônicas; dias sem agenda respondem 404.

Saída: data/generated/agenda-planalto.yaml, no mesmo formato de agendas.yaml (people: {pessoa_id: {...}}),
com `fonte: planalto`, `locais_top` no lugar de `entidades_top` e `participantes` sempre vazio.
Cache por dia em build/cache-agenda-planalto/ (dias passados não mudam; hoje e ontem são relidos).
"""
import collections, datetime, html, json, pathlib, re, sys, time, urllib.error, urllib.request
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "generated" / "agenda-planalto.yaml"
CACHE = ROOT / "build" / "cache-agenda-planalto"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 AtlasDaRepublica/1.0 (+https://atlasdarepublica.org)"
JANELA = 90
PAUSA = 2.0  # segundos entre leituras; o site devolve 429 com ritmo maior

# cargo do grafo -> pastas de agenda no Planalto (canônicas; a URL muda quando muda o ocupante)
FONTES = {
    "br-presidente-da-republica": {
        "slug": "presidente",
        "bases": ["https://www.gov.br/planalto/pt-br/acompanhe-o-planalto/agenda-do-presidente-da-republica-lula/agenda-do-presidente-da-republica"],
        "url": "https://www.gov.br/planalto/pt-br/acompanhe-o-planalto/agenda-do-presidente-da-republica",
        "fonte_nome": "Agenda oficial do Planalto",
    },
    "br-vice-presidente-da-republica": {
        "slug": "vice",
        "bases": ["https://www.gov.br/planalto/pt-br/vice-presidencia/agenda-vice-presidente-geraldo-alckmin/agenda-do-vice-presidente-geraldo-alckmin",
                  "https://www.gov.br/planalto/pt-br/vice-presidencia/agenda-vice-presidente-geraldo-alckmin/agenda-de-presidente-em-exercicio"],
        "url": "https://www.gov.br/planalto/pt-br/vice-presidencia/agenda-vice-presidente-geraldo-alckmin",
        "fonte_nome": "Agenda oficial da Vice-Presidência",
    },
}

CARGOS_RX = re.compile(r"^(ministr[oa]|secret[áa]ri[oa]|chefe|presidente|vice-presidente|deputad[oa]|senador|governador|prefeit[oa]|embaixador|assessor|diretor|comandante|general|almirante|brigadeiro|procurador|advogad[oa]|controlador|reitor|desembargador|conselheir[oa]|líder|lider|cardeal|bispo|dom |papa|primeiro|primeira|rei|rainha|príncipe|princesa|sua |sr\.|sra\.)", re.I)
TIPOS = [
    ("viagem", re.compile(r"^(partida|chegada|embarque|desembarque|viagem|retorno|deslocamento|decolagem|pouso)", re.I)),
    ("audiencia", re.compile(r"audi[êe]ncia|recebe ", re.I)),
    ("reuniao", re.compile(r"reuni[ãa]o|encontro|despacho|conversa|almo[çc]o|jantar|caf[ée] da manh[ãa]|videoconfer[êe]ncia|telefonema|liga[çc][ãa]o", re.I)),
    ("evento", re.compile(r"cerim[ôo]nia|solenidade|evento|lan[çc]amento|posse|entrevista|sess[ãa]o|abertura|visita|pronunciamento|discurso|participa|assinatura|anúncio|an[úu]ncio|entrega|inaugura|comemora|homenagem|cúpula|c[úu]pula|assembleia|confer[êe]ncia|semin[áa]rio|programa|grava[çc][ãa]o", re.I)),
]


def _graph():
    p = ROOT / "build" / "graph.br.json"
    if p.exists(): return json.load(open(p, encoding="utf-8"))
    js = (ROOT / "web" / "graph.br.js").read_text(encoding="utf-8")
    return json.loads(js[js.index("{"):js.rindex("}") + 1])


def fetch(url, cache_file, refresh=False):
    if cache_file.exists() and not refresh:
        return cache_file.read_text(encoding="utf-8")
    for tent in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8", "Accept-Language": "pt-BR,pt;q=0.9"})
            with urllib.request.urlopen(req, timeout=40) as r:
                body = r.read().decode("utf-8", "replace")
            if "item-compromisso" not in body and "<title>" not in body:  # desafio antirrobô sem conteúdo
                time.sleep(3 + 3 * tent); continue
            cache_file.parent.mkdir(parents=True, exist_ok=True); cache_file.write_text(body, encoding="utf-8")
            time.sleep(PAUSA)
            return body
        except urllib.error.HTTPError as e:
            if e.code == 404:
                cache_file.parent.mkdir(parents=True, exist_ok=True); cache_file.write_text("", encoding="utf-8"); return ""
            if e.code == 429:  # limite de requisições do Planalto: recua bastante
                print(f"  429 em {url[-10:]}, aguardando {20 * (tent + 1)} s", flush=True); time.sleep(20 * (tent + 1)); continue
            time.sleep(2 + 2 * tent)
        except Exception:  # noqa: BLE001
            time.sleep(2 + 2 * tent)
    return None


def _txt(s):
    return html.unescape(re.sub(r"<[^>]+>", " ", s or "")).replace("\xa0", " ").strip()


def parse(body):
    items = []
    for m in re.finditer(r'<div class="item-compromisso">(.*?)</li>', body, re.S):
        blk = m.group(1)
        g = lambda cls: (lambda mm: _txt(mm.group(1)) if mm else None)(re.search(r'class="%s"[^>]*>(.*?)</' % cls, blk, re.S))
        hora = g("compromisso-inicio"); fim = g("compromisso-fim"); titulo = g("compromisso-titulo"); local = g("compromisso-local")
        desc = re.search(r'class="compromisso-descricao"[^>]*>(.*?)</div>', blk, re.S)
        if not titulo: continue
        items.append({"hora": (hora or "").replace("h", ":") if hora and re.match(r"^\d{1,2}h\d{2}$", hora) else hora, "fim": fim, "titulo": re.sub(r"\s+", " ", titulo), "local": local, "descricao": _txt(desc.group(1))[:300] if desc else None})
    return items


def tipo(titulo):
    for t, rx in TIPOS:
        if rx.search(titulo or ""): return t
    if CARGOS_RX.search(titulo or "") or re.search(r"^[A-ZÀ-Ú][\w'’.-]+( (de|da|do|dos|das|e|[A-ZÀ-Ú][\w'’.-]+))+,", titulo or ""): return "audiencia"
    if re.search(r"san[çc][ãa]o|fotografia|foto |declara[çc][ãa]o|podcast|desfile|concerto|apresenta[çc][ãa]o|encerramento|interven[çc][õo]es|missa|culto|recep[çc][ãa]o|exposi[çc][ãa]o|show|cine", titulo or "", re.I): return "evento"
    return "outro"


def quem(titulo):
    """'Ministro de Estado da Fazenda, Fernando Haddad' -> (nome, cargo); 'Fulano, presidente da X' -> (nome, cargo)."""
    t = (titulo or "").strip()
    m = re.match(r"^(?P<cargo>[^,]{4,120}),\s*(?P<nome>[A-ZÀ-Ú][^,]{3,80})$", t)
    if m and CARGOS_RX.search(m.group("cargo")): return m.group("nome").strip(), m.group("cargo").strip()
    m = re.match(r"^(?P<nome>[A-ZÀ-Ú][^,]{3,80}),\s*(?P<cargo>[^,]{4,140})$", t)
    if m and CARGOS_RX.search(m.group("cargo")): return m.group("nome").strip(), m.group("cargo").strip()
    return None


def main():
    refresh = "--refresh" in sys.argv
    janela = JANELA
    g = _graph()
    hoje = datetime.date.today(); inicio = hoje - datetime.timedelta(days=janela - 1)
    people, log = {}, []
    # dias já lidos em execuções anteriores (gravados no próprio YAML, que é versionado) dispensam nova leitura
    prev = (yaml.safe_load(OUT.read_text(encoding="utf-8")) or {}) if OUT.exists() and not refresh else {}
    prev_days = {}
    for pid, a in (prev.get("people") or {}).items():
        for slug_d, its in (a.get("dias") or {}).items(): prev_days[slug_d] = its
    for pos_id, cfg in FONTES.items():
        node = g["nodes"].get(pos_id) or {}
        holder = (node.get("people") or [{}])[0]
        pid = holder.get("id")
        if not pid: log.append(f"{pos_id}: sem ocupante no grafo"); continue
        comp = []; dias = 0; falhas = 0; dias_lidos = {}
        for i in range(janela):
            d = inicio + datetime.timedelta(days=i)
            for bi, base in enumerate(cfg["bases"]):
                key = f"{cfg['slug']}/{d.isoformat()}{'-b%d' % bi if bi else ''}"
                if key in prev_days and (hoje - d).days > 1:
                    its = [dict(x) for x in prev_days[key]]
                else:
                    cf = CACHE / cfg["slug"] / f"{d.isoformat()}{'-b%d' % bi if bi else ''}.html"
                    body = fetch(f"{base}/{d.isoformat()}", cf, refresh=refresh or (hoje - d).days <= 1)
                    if body is None: falhas += 1; continue
                    its = parse(body) if body else []
                dias_lidos[key] = [{k: v for k, v in x.items() if k in ("hora", "fim", "titulo", "local", "descricao") and v} for x in its]
                if not its: continue
                if its and bi == 0: dias += 1
                for it in its:
                    it["data"] = d.isoformat(); it["tipo"] = tipo(it["titulo"]); q = quem(it["titulo"])
                    it["participantes"] = [{"nome": q[0], "entidade": q[1]}] if q else []
                    if bi: it["nota"] = "como presidente em exercício"
                    comp.append(it)
        comp.sort(key=lambda x: (x["data"], x.get("hora") or ""))
        por_tipo = collections.Counter(x["tipo"] for x in comp)
        ents = collections.Counter(q["nome"] for x in comp for q in x["participantes"])
        cargo_de = {}
        for x in comp:
            for q in x["participantes"]: cargo_de.setdefault(q["nome"], q["entidade"][:70])
        locais = collections.Counter(re.sub(r"\s*[–-]\s*(Bras[íi]lia|DF)\s*$", "", x["local"]).strip() for x in comp if x.get("local"))
        rec = [{k: x.get(k) for k in ("data", "hora", "titulo", "tipo", "local", "participantes", "nota") if x.get(k) is not None} for x in comp[-8:]][::-1]
        people[pid] = {"agente": holder.get("name"), "cargo": node.get("name"), "orgao": (g["nodes"].get(node.get("head_of") or "") or {}).get("name"),
                       "fonte": "planalto", "fonte_nome": cfg["fonte_nome"], "url": cfg["url"], "compromissos_90d": len(comp), "dias_com_agenda": dias,
                       "por_tipo": dict(por_tipo.most_common()), "entidades_top": [{"nome": f"{k} ({cargo_de[k]})", "n": v} for k, v in ents.most_common(10)], "locais_top": [{"nome": k, "n": v} for k, v in locais.most_common(10)],
                       "ultimo": comp[-1]["data"] if comp else None, "recentes": rec, "dias_nao_lidos": falhas, "dias": dias_lidos}
        log.append(f"{pid}: {len(comp)} compromissos em {dias} dias ({falhas} dias não lidos)")
    print("\n".join(log))
    body = yaml.dump({"generated_at": hoje.isoformat(), "fonte": "gov.br/planalto — páginas diárias da agenda oficial (uma por dia, sem participantes)", "janela_dias": janela,
                      "janela_inicio": inicio.isoformat(), "people": people, "log": log}, allow_unicode=True, sort_keys=False, width=120)
    OUT.write_text("# GERADO por etl/agenda_planalto.py. Não edite à mão.\n" + body, encoding="utf-8")
    print(f"→ {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
