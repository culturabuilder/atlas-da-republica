#!/usr/bin/env python3
"""Datas de nascimento (Wikidata P569) das pessoas em cargos vitalícios ou com aposentadoria compulsória aos 75 anos
(ministros do STF, STJ, TST, TSE, STM e TCU, presidentes desses tribunais) → data/generated/nascimentos.yaml.

Busca por nome (wbsearchentities, pt) e aceita o item se for pessoa (P31=Q5), brasileira (P27=Q155) ou descrita como
brasileira, e tiver P569. Cache em build/cache-nascimentos.json. Uso: .venv/bin/python etl/nascimentos.py
"""
import json, re, sys, time, pathlib, unicodedata, urllib.request, urllib.parse
import yaml
ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / "build" / "cache-nascimentos.json"
UA = {"User-Agent": "atlas-da-republica/0.1 (https://atlasdarepublica.org)"}
def norm(s): return re.sub(r"[^a-z ]", "", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()).strip()
def api(params):
    time.sleep(0.6)
    u = "https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode(dict(params, format="json"))
    return json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60))
def lookup(name):
    hits = api({"action": "wbsearchentities", "search": name, "language": "pt", "limit": 6}).get("search") or []
    if not hits: hits = api({"action": "wbsearchentities", "search": name, "language": "en", "limit": 6}).get("search") or []
    ids = [h["id"] for h in hits]
    if not ids: return None
    ents = api({"action": "wbgetentities", "ids": "|".join(ids), "props": "claims|descriptions|labels", "languages": "pt|en"}).get("entities") or {}
    best = None
    for qid in ids:
        e = ents.get(qid) or {}; c = e.get("claims") or {}
        def vals(p): return [x.get("mainsnak", {}).get("datavalue", {}).get("value") for x in c.get(p, [])]
        if not any((v or {}).get("id") == "Q5" for v in vals("P31")): continue
        desc = ((e.get("descriptions") or {}).get("pt") or {}).get("value", "") + " " + ((e.get("descriptions") or {}).get("en") or {}).get("value", "")
        br = any((v or {}).get("id") == "Q155" for v in vals("P27")) or re.search(r"brasil|brazil", desc, re.I)
        birth = [v for v in vals("P569") if v]
        if not birth: continue
        judge = any((v or {}).get("id") in ("Q16533", "Q1516800") for v in vals("P106")) or bool(c.get("P39")) or re.search(r"juiz|jurist|judge|magistr|minist|advogad|lawyer", desc, re.I)
        score = (2 if br else 0) + (2 if judge else 0) + (1 if norm(((e.get("labels") or {}).get("pt") or {}).get("value", "")) == norm(name) else 0)
        b = birth[0]; t = b.get("time", ""); prec = b.get("precision", 9)
        date = t[1:11] if prec >= 11 else (t[1:8] + "-01" if prec == 10 else t[1:5] + "-01-01")
        if not br and not judge: continue
        if best is None or score > best[0]: best = (score, qid, date, desc.strip())
    return best
def main():
    g = json.load(open(ROOT / "build" / "graph.br.json", encoding="utf-8")); N = g["nodes"]
    cache = json.load(open(CACHE, encoding="utf-8")) if CACHE.exists() else {}
    out = {}; want = {}
    for n in N.values():
        if n["type"] != "dept_head": continue
        vital = any("vital" in ((p.get("entry") or {}).get("term_note") or "") for p in n.get("people") or []) or "tcu" in n["id"]
        if not vital: continue
        for p in n.get("people") or []:
            if p.get("id") and p.get("name"): want[p["id"]] = p["name"]
    print(f"{len(want)} pessoas em cargos vitalícios", file=sys.stderr)
    ok = 0
    for pid, name in want.items():
        if pid in cache: r = cache[pid]
        else:
            try: r = lookup(name)
            except Exception as e: print("erro", name, e, file=sys.stderr); r = None
            cache[pid] = r; json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
        if r: out[pid] = {"name": name, "qid": r[1], "birth": r[2], "match": r[3][:80], "source": "wikidata"}; ok += 1
    (ROOT / "data" / "generated" / "nascimentos.yaml").write_text("# GERADO por etl/nascimentos.py (Wikidata P569). Não edite à mão.\n" + yaml.dump({"people": out}, allow_unicode=True, sort_keys=False, width=110), encoding="utf-8")
    print(f"nascimentos: {ok} de {len(want)}")
    for pid, r in list(out.items())[:8]: print("  ", r["name"], r["birth"], "|", r["match"][:50])
if __name__ == "__main__": main()
