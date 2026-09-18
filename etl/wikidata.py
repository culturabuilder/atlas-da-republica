#!/usr/bin/env python3
"""Wikidata (API de ações, sem SPARQL) → data/generated/ocupantes.yaml

1. Mapeia cada cargo (dept_head e chefias eletivas) para um item de cargo no Wikidata por busca de rótulo,
   com sobrescritas curadas em data/wikidata-overrides.yaml. O mapa gerado vai para data/generated/wikidata-map.yaml.
2. Para cada item de cargo, lista as pessoas que apontam para ele (backlinks) e filtra as declarações
   P39 (cargo ocupado) sem data de término. Coleta início (P580), foto (P18) e partido (P102).

Uso: .venv/bin/python etl/wikidata.py [--limit N] [--only id1,id2]
"""
import json, sys, time, pathlib, argparse, re, urllib.request, urllib.parse, unicodedata
import yaml
ROOT = pathlib.Path(__file__).resolve().parent.parent
API = "https://www.wikidata.org/w/api.php"
UA = {"User-Agent": "atlas-da-republica/0.1 (https://github.com/atlas-da-republica; etl)"}
CACHE = ROOT / "build" / "cache-wikidata.json"
cache = json.load(open(CACHE)) if CACHE.exists() else {}

def call(params):
    key = json.dumps(params, sort_keys=True)
    if key in cache: return cache[key]
    params = dict(params, format="json", maxlag=5)
    for attempt in range(5):
        try:
            r = urllib.request.Request(API + "?" + urllib.parse.urlencode(params), headers=UA)
            data = json.load(urllib.request.urlopen(r, timeout=90))
            if "error" in data and data["error"].get("code") == "maxlag": time.sleep(3); continue
            cache[key] = data; return data
        except Exception as e:
            time.sleep(2 + attempt * 3)
    return {}

def norm(s): return re.sub(r"[^a-z0-9 ]", "", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()).strip()

def search(text):
    d = call({"action": "wbsearchentities", "search": text, "language": "pt", "uselang": "pt", "type": "item", "limit": 8})
    return d.get("search", [])

def find_position(name):
    """Devolve (qid, label, confiança) ou None."""
    cands = []
    for q in (name, name + " do Brasil", re.sub(r"^Ministro de Estado", "Ministro", name) + " do Brasil"):
        for s in search(q):
            desc = (s.get("description") or "").lower(); lab = s.get("label") or ""
            score = 0
            if re.search(r"bra[sz]il", desc) or re.search(r"bra[sz]il", lab.lower()): score += 3
            if re.search(r"cargo|position|office|minist|ministerial|head|chefe|presidente|president|judge|juiz|magistrat", desc): score += 2
            if re.search(r"wikinews|article|notícia|person|pessoa|human|político|politician|humano", desc): score -= 4
            if re.search(r"minist[ée]rio|ministry|ag[êe]ncia|agency|[óo]rg[ãa]o|department|autarquia|empresa|company|bank of|banco|tribunal|court", desc) and not re.search(r"position|cargo|office|head of|chefe|minister of|ministro|president of|presidente|judge|juiz|member of|membro", desc): score -= 5
            if norm(lab) == norm(q): score += 2
            cands.append((score, s["id"], lab, desc))
    cands.sort(reverse=True)
    return cands[0] if cands and cands[0][0] >= 3 else None

def entities(qids, props="claims|labels|descriptions"):
    out = {}
    for i in range(0, len(qids), 50):
        d = call({"action": "wbgetentities", "ids": "|".join(qids[i:i+50]), "props": props, "languages": "pt|en"})
        out.update(d.get("entities", {}))
    return out

def backlinks(qid):
    ids, cont = [], None
    while True:
        p = {"action": "query", "list": "backlinks", "bltitle": qid, "blnamespace": 0, "bllimit": 500}
        if cont: p["blcontinue"] = cont
        d = call(p); ids += [b["title"] for b in d.get("query", {}).get("backlinks", []) if b["title"].startswith("Q")]
        cont = d.get("continue", {}).get("blcontinue")
        if not cont or len(ids) > 3000: break
    return ids

def label(ent): return (ent.get("labels", {}).get("pt") or ent.get("labels", {}).get("en") or {}).get("value")
def tval(snak):
    try: return snak["datavalue"]["value"]["time"][1:11]
    except Exception: return None

def holders(pos_qid, seats=1):
    people = entities(backlinks(pos_qid))
    out = []
    for qid, ent in people.items():
        if not any((c.get("mainsnak", {}).get("datavalue", {}).get("value", {}) or {}).get("id") == "Q5" for c in ent.get("claims", {}).get("P31", [])): continue
        for st in ent.get("claims", {}).get("P39", []):
            try: v = st["mainsnak"]["datavalue"]["value"]["id"]
            except Exception: continue
            if v != pos_qid: continue
            q = st.get("qualifiers", {})
            if "P582" in q: continue  # já encerrado
            start = tval(q["P580"][0]) if "P580" in q else None
            if not start: continue  # sem data de início não dá para saber se é o atual
            img = None
            for c in ent.get("claims", {}).get("P18", [])[:1]:
                try: img = c["mainsnak"]["datavalue"]["value"]
                except Exception: pass
            party = None
            for c in ent.get("claims", {}).get("P102", []):
                if "P582" in c.get("qualifiers", {}): continue
                try: party = c["mainsnak"]["datavalue"]["value"]["id"]; break
                except Exception: pass
            acting = any(x.get("datavalue", {}).get("value", {}).get("id") in ("Q4164871",) for x in q.get("P2868", [])) or any(x.get("datavalue", {}).get("value", {}).get("id") == "Q4164871" for x in q.get("P39", []))
            out.append({"id": "br-p-wd-" + qid.lower(), "name": label(ent), "wikidata": qid, "started_at": start, "party_qid": party,
                        "image_commons": ("https://commons.wikimedia.org/wiki/Special:FilePath/" + urllib.parse.quote(img)) if img else None,
                        "acting": bool(acting), "entry_mode": "nomeado", "source_url": f"https://www.wikidata.org/wiki/{qid}", "source": "wikidata", "verified": False})
    out.sort(key=lambda p: p.get("started_at") or "", reverse=True)
    return out[:max(1, seats)]

def find_org(name, aliases):
    """Item do órgão no Wikidata (busca por nome e siglas)."""
    cands = []
    for q in [name] + [a for a in (aliases or []) if len(a) >= 3][:2]:
        for s in search(q):
            desc = (s.get("description") or "").lower(); lab = s.get("label") or ""; score = 0
            if re.search(r"bra[sz]il", desc) or re.search(r"bra[sz]il", lab.lower()): score += 3
            if re.search(r"minist[ée]rio|ministry|ag[êe]ncia|agency|[óo]rg[ãa]o|government|governo|autarquia|tribunal|court|bank|banco|company|empresa|foundation|funda[çc][ãa]o|institute|instituto|council|conselho|departamento|department|secretar", desc): score += 2
            if re.search(r"wikinews|article|person|human|humano|político|politician|position|cargo|office", desc): score -= 4
            if norm(lab) == norm(q): score += 3
            cands.append((score, s["id"], lab, desc))
    cands.sort(reverse=True)
    return cands[0] if cands and cands[0][0] >= 4 else None

def claim_ids(ent, prop, only_open=True):
    out = []
    for c in ent.get("claims", {}).get(prop, []):
        if only_open and "P582" in c.get("qualifiers", {}): continue
        try: out.append((c["mainsnak"]["datavalue"]["value"]["id"], tval(c["qualifiers"]["P580"][0]) if "P580" in c.get("qualifiers", {}) else None))
        except Exception: pass
    return out

def person_record(qid, ent, start):
    img = None
    for c in ent.get("claims", {}).get("P18", [])[:1]:
        try: img = c["mainsnak"]["datavalue"]["value"]
        except Exception: pass
    party = None
    for c in ent.get("claims", {}).get("P102", []):
        if "P582" in c.get("qualifiers", {}): continue
        try: party = c["mainsnak"]["datavalue"]["value"]["id"]; break
        except Exception: pass
    return {"id": "br-p-wd-" + qid.lower(), "name": label(ent), "wikidata": qid, "started_at": start, "party_qid": party,
            "image_commons": ("https://commons.wikimedia.org/wiki/Special:FilePath/" + urllib.parse.quote(img)) if img else None,
            "acting": False, "entry_mode": "nomeado", "source_url": f"https://www.wikidata.org/wiki/{qid}", "source": "wikidata", "verified": False}

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--limit", type=int); ap.add_argument("--only"); a = ap.parse_args()
    g = json.load(open(ROOT / "build" / "graph.br.json", encoding="utf-8"))["nodes"]
    overrides = yaml.safe_load(open(ROOT / "data" / "wikidata-overrides.yaml", encoding="utf-8")) or {} if (ROOT / "data" / "wikidata-overrides.yaml").exists() else {}
    targets = [n for n in g.values() if n["type"] == "dept_head" or n["id"] in ("br-presidente-da-republica", "br-vice-presidente-da-republica")]
    targets = [n for n in targets if n["id"] not in ("br-deputado-federal", "br-senador")]
    if a.only: targets = [n for n in targets if n["id"] in a.only.split(",")]
    if a.limit: targets = targets[:a.limit]
    mapping, positions, party_qids = {}, {}, set()
    org_cache = {}
    for i, n in enumerate(targets):
        ov = overrides.get(n["id"])
        if ov is False: mapping[n["id"]] = {"qid": None, "note": "sem item no Wikidata (curado)"}; continue
        qid = lab = None; conf = 0; hs = []; route = None
        if ov: qid, lab, conf, route = ov, "(override)", 9, "override"
        else:
            f = find_position(n["name"])
            if f: conf, qid, lab, desc = f; route = "busca do cargo"
        # rota pelo órgão: P2388 (cargo do dirigente) ou dirigentes diretos (P1037/P488/P169/P35/P6)
        org = g.get(n.get("head_of") or "")
        org_ent = None
        if org:
            if org["id"] not in org_cache:
                fo = find_org(org["name"], org.get("aliases"))
                if fo:
                    org_ent_map = entities([fo[1]]); ent0 = org_ent_map.get(fo[1]) or {}
                    country = [c[0] for c in claim_ids(ent0, "P17", only_open=False)]
                    if country and "Q155" not in country: fo = None; ent0 = None  # órgão de outro país
                    org_cache[org["id"] + ":ent"] = ent0
                org_cache[org["id"]] = fo
            fo = org_cache.get(org["id"]); org_ent = org_cache.get(org["id"] + ":ent")
            if org_ent and not qid:
                heads = claim_ids(org_ent, "P2388", only_open=False)
                if heads: qid, lab, conf, route = heads[0][0], "(P2388 de " + fo[2] + ")", 6, "P2388 do órgão"
        if qid: hs = holders(qid, n.get("seats") or 1)
        if not hs and org_ent and (n.get("seats") or 1) == 1:
            direct = []
            for prop in ("P1037", "P488", "P169", "P35", "P6"):
                direct += claim_ids(org_ent, prop)
            if direct:
                pe = entities([d[0] for d in direct])
                hs = [person_record(d[0], pe[d[0]], d[1]) for d in direct if d[0] in pe]
                hs.sort(key=lambda p: p.get("started_at") or "", reverse=True); hs = hs[:1]; route = (route or "") + " + dirigente do órgão"
        if not qid and not hs:
            mapping[n["id"]] = {"qid": None, "note": "não encontrado", "org_item": (org_cache.get(org["id"]) or [None, None])[1] if org else None}
            print(f"[{i+1}/{len(targets)}] {n['name']}: sem item", file=sys.stderr); continue
        mapping[n["id"]] = {"qid": qid, "label": lab, "confidence": conf, "holders": len(hs), "route": route, "org_item": (org_cache.get(org["id"]) or [None, None])[1] if org else None}
        if hs: positions[n["id"]] = hs; party_qids |= {h["party_qid"] for h in hs if h.get("party_qid")}
        print(f"[{i+1}/{len(targets)}] {n['name']} -> {qid} {lab!r} ocupantes={len(hs)}", file=sys.stderr)
        json.dump(cache, open(CACHE, "w"), ensure_ascii=False)
    parties = {q: label(e) for q, e in entities(sorted(party_qids), "labels").items()}
    for hs in positions.values():
        for h in hs: h["party"] = parties.get(h.pop("party_qid", None)) if h.get("party_qid") else h.pop("party_qid", None)
    class D(yaml.SafeDumper):
        def increase_indent(self, flow=False, indentless=False): return super().increase_indent(flow, False)
    (ROOT / "data" / "generated" / "wikidata-map.yaml").write_text("# GERADO por etl/wikidata.py. Para corrigir um mapeamento, use data/wikidata-overrides.yaml (id do cargo: QID, ou false).\n" + yaml.dump(mapping, Dumper=D, allow_unicode=True, sort_keys=True, width=110), encoding="utf-8")
    (ROOT / "data" / "generated" / "ocupantes.yaml").write_text("# GERADO por etl/wikidata.py. Não edite à mão.\n" + yaml.dump({"generated_from": "wikidata.org (P39 sem P582)", "positions": positions}, Dumper=D, allow_unicode=True, sort_keys=False, width=110), encoding="utf-8")
    json.dump(cache, open(CACHE, "w"), ensure_ascii=False)
    print(f"cargos alvo={len(targets)} mapeados={sum(1 for m in mapping.values() if m.get('qid'))} com ocupante={len(positions)} pessoas={sum(len(v) for v in positions.values())}")

if __name__ == "__main__": main()
