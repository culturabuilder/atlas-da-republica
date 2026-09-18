#!/usr/bin/env python3
"""Senado: mensagens MSF de indicação de autoridade → data/generated/sabatinas.yaml

Fontes (sem chave): /dadosabertos/processo?sigla=MSF&ano=Y e /dadosabertos/votacao?idProcesso=ID.
Cada sabatina traz nome, cargo (extraído da ementa), datas, resultado e placar; o cargo é casado com um
cargo do grafo por similaridade de nome.
Uso: .venv/bin/python etl/sabatinas.py [--anos 2023,2024,2025,2026]
"""
import json, re, sys, pathlib, argparse, urllib.request, unicodedata, difflib
import yaml
ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / "build" / "cache-senado.json"
cache = json.load(open(CACHE)) if CACHE.exists() else {}

def get(url):
    if url in cache: return cache[url]
    r = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "atlas-da-republica/0.1"})
    try: d = json.load(urllib.request.urlopen(r, timeout=90))
    except Exception as e: print("falhou", url, e, file=sys.stderr); d = None
    cache[url] = d; return d

def norm(s): return re.sub(r"[^a-z0-9 ]", " ", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()).strip()

def parse_ementa(e):
    e = re.sub(r"\s+", " ", e or "")
    m = re.search(r"o nome d[oa]s?\s+(.+?)(?:,|\s+para\s|\s+a fim)", e)
    name = m.group(1).strip(" ,.") if m else None
    if name:
        name = re.sub(r"^(?:Senhora?|Sra?\.?|Doutora?|Dra?\.?|Excelent[íi]ssim[oa]|General(?: de Exército| de Brigada| de Divisão)?|Almirante(?: de Esquadra)?|Vice-Almirante|Tenente-Brigadeiro(?: do Ar)?|Brigadeiro|Ministr[oa]|Desembargador[a]?|Procurador[a]?|Juiz[a]?|Professor[a]?|Embaixador[a]?|Diplomata|Conselheir[oa])\s+", "", name, flags=re.I).strip()
        name = re.sub(r"^(?:Senhora?|Sra?\.?|Doutora?|Dra?\.?)\s+", "", name, flags=re.I)
        if name.isupper(): name = " ".join(w.capitalize() if len(w) > 2 else w.lower() for w in name.split())
    if name: name = " ".join(w.capitalize() if len(w) > 2 else w.lower() for w in name.split())
    c = re.search(r"(?:para (?:exercer|compor|ocupar)|ao cargo de|para o cargo de|para exercer o cargo de|como)\s+(?:o cargo de\s+|a função de\s+)?(.+?)(?:\.$|,? (?:na forma|com mandato|em vaga|na vaga|em decorr|decorrente|destinad|cumulativamente|nos termos|em virtude|em substitui)|, e, cumulativamente|$)", e)
    cargo = c.group(1).strip(" .") if c else None
    return name, cargo

def build_index(graph):
    idx = []
    for n in graph["nodes"].values():
        if n["type"] != "dept_head": continue
        org = graph["nodes"].get(n.get("head_of") or "", {})
        keys = {norm(n["name"])}
        for a in (org.get("aliases") or []) + [org.get("name") or ""]:
            if a: keys.add(norm(re.sub(r"^(Ministro|Presidente|Diretor(?:-Geral|-Presidente)?|Conselheiro|Diretor)( d[oa]s?)?", "", n["name"]) + " " + a))
        idx.append((n["id"], keys, org.get("name", "")))
    return idx

def match_position(cargo, idx, graph):
    if not cargo: return None, 0
    c = norm(cargo)
    # regras diretas
    if re.search(r"embaixad|chefe de miss|missao diplomatica", c): return "br-ministerio-das-relacoes-exteriores", 1.0
    best, score = None, 0
    role = lambda t: (re.match(r"(ministr|president|diretor president|diretor geral|diretor|conselheir|procurador|defensor|superintendent|membro|advogad)", t) or [None])[0]
    rc = role(c)
    for pid, keys, org in idx:
        pname = norm(graph["nodes"][pid]["name"]); rp = role(pname)
        for k in keys:
            r = difflib.SequenceMatcher(None, c, k).ratio()
            if org and norm(org) and norm(org) in c: r += 0.25
            if rc and rp: r += 0.15 if rc == rp else -0.15
            if r > score: best, score = pid, r
    return (best, round(score, 2)) if score >= 0.62 else (None, round(score, 2))

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--anos", default="2023,2024,2025,2026"); a = ap.parse_args()
    graph = json.load(open(ROOT / "build" / "graph.br.json", encoding="utf-8"))
    idx = build_index(graph)
    out = []
    for ano in a.anos.split(","):
        lst = get(f"https://legis.senado.leg.br/dadosabertos/processo?sigla=MSF&ano={ano}") or []
        for m in lst:
            if not (m.get("tipoConteudo") or "").startswith("Indica"): continue
            name, cargo = parse_ementa(m.get("ementa"))
            pid, sc = match_position(cargo, idx, graph)
            rec = {"msf": m.get("identificacao"), "id_processo": m.get("id"), "tipo": m.get("tipoConteudo"), "apresentacao": m.get("dataApresentacao"),
                   "deliberacao": m.get("dataDeliberacao"), "resultado": m.get("siglaTipoDeliberacao"), "tramitando": m.get("tramitando") == "Sim",
                   "name": name, "cargo": cargo, "position_id": pid, "match_score": sc, "url": f"https://www25.senado.leg.br/web/atividade/materias/-/materia/{m.get('codigoMateria')}"}
            if m.get("dataDeliberacao"):
                v = get(f"https://legis.senado.leg.br/dadosabertos/votacao?idProcesso={m.get('id')}") or []
                v = [x for x in v if x.get("sigla") == "MSF"] or v
                if v:
                    x = sorted(v, key=lambda y: y.get("dataSessao") or "")[-1]
                    rec.update({"votos_sim": x.get("totalVotosSim"), "votos_nao": x.get("totalVotosNao"), "abstencoes": x.get("totalVotosAbstencao"), "secreta": x.get("votacaoSecreta") == "S"})
            out.append(rec)
        json.dump(cache, open(CACHE, "w"), ensure_ascii=False)
    out.sort(key=lambda r: r.get("deliberacao") or r.get("apresentacao") or "", reverse=True)
    class D(yaml.SafeDumper):
        def increase_indent(self, flow=False, indentless=False): return super().increase_indent(flow, False)
    (ROOT / "data" / "generated" / "sabatinas.yaml").write_text("# GERADO por etl/sabatinas.py. Não edite à mão.\n" + yaml.dump({"generated_from": "legis.senado.leg.br/dadosabertos (MSF)", "sabatinas": out}, Dumper=D, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    from collections import Counter
    print(f"indicações={len(out)} com cargo casado={sum(1 for r in out if r['position_id'])} aprovadas={sum(1 for r in out if r['resultado']=='APROVADA_NO_PLENARIO')} em tramitação={sum(1 for r in out if r['tramitando'])}")
    print("sem casar:", [(r["cargo"] or "")[:60] for r in out if not r["position_id"]][:12])
    print("exemplos:", [(r["name"], (r["cargo"] or "")[:40], r["position_id"], r.get("votos_sim")) for r in out if r["position_id"]][:6])

if __name__ == "__main__": main()
