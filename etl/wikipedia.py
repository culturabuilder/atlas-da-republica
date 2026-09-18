#!/usr/bin/env python3
"""Wikipédia (pt): tabelas de "Composição atual" → data/generated/wikipedia.yaml

Mapa curado cargo → (página, regex da seção, coluna do nome, coluna da data). Fonte secundária, marcada
`source: wikipedia`; entra abaixo das páginas oficiais e acima do Wikidata.
Uso: .venv/bin/python etl/wikipedia.py
"""
import json, re, html, time, sys, pathlib, urllib.request, urllib.parse, unicodedata
import yaml
ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = {"User-Agent": "atlas-da-republica/0.1 (etl; contato via github)"}
MESES = {m: i + 1 for i, m in enumerate("janeiro fevereiro março abril maio junho julho agosto setembro outubro novembro dezembro".split())}
MAP = {
    "br-superior-tribunal-de-justica-ministro": ("Superior Tribunal de Justiça", r"Composi", "Nome", r"posse"),
    "br-tribunal-superior-do-trabalho-ministro": ("Tribunal Superior do Trabalho", r"Composi", "Nome", r"In[íi]cio"),
    "br-diretor-do-banco-central": ("Banco Central do Brasil", r"Composi", "Incumbente", r"In[íi]cio"),
    "br-anatel-diretor": ("Agência Nacional de Telecomunicações", r"Conselho Diretor", None, None),
    "br-conselheiro-do-cade": ("Conselho Administrativo de Defesa Econômica", r"Composi|Tribunal|Conselheiros", "Nome", r"In[íi]cio|posse"),
    "br-conselheiro-do-cnj": ("Conselho Nacional de Justiça", r"Composi", "Nome|Conselheiro", r"In[íi]cio|posse"),
    "br-conselheiro-do-cnmp": ("Conselho Nacional do Ministério Público", r"Composi", "Nome|Conselheiro", r"In[íi]cio|posse"),
}

# estatais e outros órgãos: campo "presidente"/"ceo" da infocaixa
INFOBOX = {
    "br-petrobras-dirigente": "Petrobras", "br-banco-do-brasil-dirigente": "Banco do Brasil", "br-caixa-economica-federal-dirigente": "Caixa Econômica Federal",
    "br-bndes-dirigente": "Banco Nacional de Desenvolvimento Econômico e Social", "br-correios-dirigente": "Empresa Brasileira de Correios e Telégrafos",
    "br-empresa-brasil-de-comunicacao-dirigente": "Empresa Brasil de Comunicação", "br-embrapa-dirigente": "Empresa Brasileira de Pesquisa Agropecuária",
    "br-conab-dirigente": "Companhia Nacional de Abastecimento", "br-dataprev-dirigente": "Dataprev", "br-codevasf-dirigente": "Codevasf",
    "br-infraero-dirigente": "Infraero", "br-telebras-dirigente": "Telebras", "br-finep-dirigente": "Financiadora de Estudos e Projetos",
    "br-ebserh-dirigente": "Empresa Brasileira de Serviços Hospitalares", "br-casa-da-moeda-do-brasil-dirigente": "Casa da Moeda do Brasil",
    "br-empresa-de-pesquisa-energetica-dirigente": "Empresa de Pesquisa Energética", "br-infra-sa-dirigente": "Infra S.A.",
    "br-capes-dirigente": "Coordenação de Aperfeiçoamento de Pessoal de Nível Superior", "br-ibge-dirigente": "Instituto Brasileiro de Geografia e Estatística",
    "br-enap-dirigente": "Escola Nacional de Administração Pública", "br-funasa-dirigente": "Fundação Nacional de Saúde", "br-previc-dirigente": "Superintendência Nacional de Previdência Complementar",
    "br-sudene-dirigente": "Superintendência do Desenvolvimento do Nordeste", "br-sudam-dirigente": "Superintendência do Desenvolvimento da Amazônia", "br-sudeco-dirigente": "Superintendência do Desenvolvimento do Centro-Oeste",
    "br-ana-dirigente": "Agência Nacional de Águas e Saneamento Básico", "br-ans-dirigente": "Agência Nacional de Saúde Suplementar", "br-antt-dirigente": "Agência Nacional de Transportes Terrestres",
    "br-anm-dirigente": "Agência Nacional de Mineração", "br-anpd-dirigente": "Autoridade Nacional de Proteção de Dados", "br-diretor-geral-da-policia-federal": "Polícia Federal",
    "br-diretor-geral-da-abin": "Agência Brasileira de Inteligência", "br-defensor-publico-geral-federal": "Defensoria Pública da União", "br-presidente-do-senado-federal": "Senado Federal",
}
def wikitext(title):
    u = "https://pt.wikipedia.org/w/api.php?" + urllib.parse.urlencode({"action": "parse", "page": title, "prop": "wikitext", "format": "json", "formatversion": 2, "redirects": 1})
    for i in range(4):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60))["parse"]["wikitext"]
        except Exception: time.sleep(4 * (i + 1))
    return ""
def infobox_head(wt):
    for key in ("presidente", "diretor_presidente", "diretor-presidente", "ceo", "diretor_geral", "diretor-geral", "dirigente", "chefe", "líder", "lider", "defensor", "superintendente", "presidente_atual", "diretor"):
        m = re.search(r"^\s*\|\s*" + re.escape(key) + r"\s*=\s*(.+?)\s*$", wt, re.M | re.I)
        if m:
            v = re.sub(r"<ref[^>]*>.*?</ref>|<ref[^>]*/>|\{\{[^}]*\}\}|<br\s*/?>.*$", "", m.group(1)).strip()
            v = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", v); v = re.sub(r"\(.*?\)", "", v).strip(" ,;")
            if 5 <= len(v) <= 60 and not re.search(r"\d{4}", v): return v, key
    return None, None

def page(title):
    u = "https://pt.wikipedia.org/w/api.php?" + urllib.parse.urlencode({"action": "parse", "page": title, "prop": "text", "format": "json", "formatversion": 2, "redirects": 1})
    for i in range(4):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60))["parse"]["text"]
        except Exception as e: time.sleep(4 * (i + 1))
    return ""

def cell(c): return re.sub(r"\s*\[\s*\d+\s*\]", "", re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", c)))).replace("\u200b", "").strip()
def date(s):
    m = re.search(r"(\d{1,2})º?\s+de\s+([a-zç]+)\s+de\s+(\d{4})", (s or "").lower())
    if m and m.group(2) in MESES: return f"{m.group(3)}-{MESES[m.group(2)]:02d}-{int(m.group(1)):02d}"
    m = re.search(r"(\d{4})", s or ""); return f"{m.group(1)}-01-01" if m else None

def tables(h):
    for m in re.finditer(r'<h[23][^>]*>(.*?)</h[23]>(.*?)(?=<h[23]|$)', h, re.S):
        name = cell(m.group(1)); rows = re.findall(r"<tr[^>]*>(.*?)</tr>", m.group(2), re.S)
        cells = [[cell(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S)] for r in rows]
        if cells: yield name, [c for c in cells if c]

def main():
    out = {}
    for pid, (title, sec_rx, name_col, date_rx) in MAP.items():
        h = page(title); time.sleep(3)
        if not h: print(pid, "sem página", file=sys.stderr); continue
        people = []
        for sec, rows in tables(h):
            if not re.search(sec_rx, sec, re.I): continue
            header = rows[0]
            if name_col is None:  # tabela transposta (linha 1 = cargos, linha 2 = nomes)
                if len(rows) >= 2:
                    for role, nm in zip(rows[0], rows[1]):
                        if nm and not re.search(r"substitut", role, re.I): people.append({"name": nm, "role": role})
                break
            ni = next((i for i, c in enumerate(header) if re.search(name_col, c, re.I)), None)
            di = next((i for i, c in enumerate(header) if date_rx and re.search(date_rx, c, re.I)), None)
            fi = next((i for i, c in enumerate(header) if re.search(r"Fim|T[ée]rmino", c, re.I)), None)
            ri = next((i for i, c in enumerate(header) if re.search(r"^Cargo$", c, re.I)), None)
            if ni is None: continue
            today = __import__("datetime").date.today().isoformat()
            for r in rows[1:]:
                shift = 1 if len(r) == len(header) + 1 and re.match(r"^\d+$", r[0]) else 0   # coluna de numeração fora do cabeçalho
                if len(r) < len(header) + shift - 1: continue  # linha de continuação de célula mesclada (mandato anterior)
                j = ni + shift
                if len(r) <= j or not r[j] or re.match(r"^\d+$", r[j]): continue
                nm = r[j]
                if len(nm) < 5 or len(nm) > 70 or re.match(r"^(Diretor|Diretora|Presidente|Ministro|Conselheiro)", nm): continue
                fim = date(r[fi + shift]) if fi is not None and len(r) > fi + shift else None
                if fim and fim < today: continue
                role = r[ri + shift] if ri is not None and len(r) > ri + shift else None
                if pid == "br-diretor-do-banco-central" and role and re.match(r"^Presidente", role): continue
                people.append({"name": nm, "started_at": date(r[di + shift]) if di is not None and len(r) > di + shift else None, "role": role})
            break
        # dedupe
        seen, uniq = set(), []
        for p in people:
            if p["name"] in seen: continue
            seen.add(p["name"]); uniq.append(dict(p, id="br-p-wp-" + re.sub(r"[^a-z0-9]+", "-", p["name"].lower()), source="wikipedia", verified=False, entry_mode="nomeado",
                                            source_url="https://pt.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))))
        if uniq: out[pid] = uniq
        print(pid, "->", len(uniq), [p["name"] for p in uniq[:3]], file=sys.stderr)
    for pid, title in INFOBOX.items():
        wt = wikitext(title); time.sleep(2)
        nm, key = infobox_head(wt)
        if nm and pid not in out:
            out[pid] = [{"id": "br-p-wp-" + re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", nm).encode("ascii", "ignore").decode().lower()), "name": nm, "started_at": None, "role": None,
                         "source": "wikipedia", "verified": False, "entry_mode": "nomeado", "note": f"infocaixa da Wikipédia (campo {key})", "source_url": "https://pt.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))}]
        print(pid, "->", nm, file=sys.stderr)
    class D(yaml.SafeDumper):
        def increase_indent(self, flow=False, indentless=False): return super().increase_indent(flow, False)
    (ROOT / "data" / "generated" / "wikipedia.yaml").write_text("# GERADO por etl/wikipedia.py. Fonte secundária (Wikipédia), não editar à mão.\n" + yaml.dump({"positions": out}, Dumper=D, allow_unicode=True, sort_keys=False, width=110), encoding="utf-8")
    print("cargos:", len(out), "pessoas:", sum(len(v) for v in out.values()))

if __name__ == "__main__": main()
