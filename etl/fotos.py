#!/usr/bin/env python3
"""Fotos dos ocupantes → site/img/<id-da-pessoa>.jpg (48×48 em JPEG). Fontes: Câmara, Senado, Wikimedia Commons.
Uso: .venv/bin/python etl/fotos.py [--limit N]
"""
import json, io, sys, re, time, pathlib, argparse, urllib.request, urllib.parse, urllib.error
from PIL import Image, ImageOps
ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "img"; OUT.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "atlas-da-republica/0.1 (fotos; contato via github)"}

def fetch(url):
    if "commons.wikimedia.org" in url and "?width" not in url: url += "?width=160"
    r = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(r, timeout=40).read()

WD = "https://www.wikidata.org/w/api.php"
def wd(params):
    params = dict(params, format="json")
    for i in range(4):
        try:
            r = urllib.request.Request(WD + "?" + urllib.parse.urlencode(params), headers=UA)
            return json.load(urllib.request.urlopen(r, timeout=60))
        except urllib.error.HTTPError as e:
            if e.code == 429: time.sleep(20 * (i + 1)); continue
            raise
    return {}
def commons_image(name):
    """Busca de arquivos no Wikimedia Commons pelo nome completo; exige primeiro e último nome no título do arquivo."""
    q = urllib.parse.urlencode({"action": "query", "list": "search", "srsearch": f'"{name}"', "srnamespace": 6, "srlimit": 8, "format": "json"})
    for i in range(4):
        try:
            j = json.load(urllib.request.urlopen(urllib.request.Request("https://commons.wikimedia.org/w/api.php?" + q, headers=UA), timeout=60)); break
        except urllib.error.HTTPError as e:
            if e.code == 429: time.sleep(20 * (i + 1)); continue
            return None
        except Exception: return None
    else: return None
    nn = lambda s: re.sub(r"[^a-z ]", "", __import__("unicodedata").normalize("NFKD", s).encode("ascii", "ignore").decode().lower())
    w = [x for x in nn(name).split() if x not in ("de", "da", "do", "das", "dos", "e")]
    if len(w) < 2: return None
    hits = [h["title"] for h in j.get("query", {}).get("search", []) if re.search(r"\.(jpe?g|png)$", h["title"], re.I)]
    good = [h for h in hits if w[0] in nn(h) and any(x in nn(h) for x in w[1:] if len(x) > 3)]
    good.sort(key=lambda h: (0 if "cropped" in h.lower() else 1, len(h)))
    return ("https://commons.wikimedia.org/wiki/Special:FilePath/" + urllib.parse.quote(good[0][5:])) if good else None

def name_variants(n):
    w = n.split(); out = [n]
    if len(w) >= 3: out += [w[0] + " " + w[-1], " ".join(w[:2]) + " " + w[-1], w[0] + " " + w[1]]
    return list(dict.fromkeys(out))
def wikidata_image(name):
    """Foto (P18) da pessoa no Wikidata, procurando pelo nome; exige item humano com descrição ligada ao Brasil ou a política."""
    try:
        hits = wd({"action": "wbsearchentities", "search": name, "language": "pt", "type": "item", "limit": 5}).get("search", [])
    except Exception: return None
    for h in hits:
        d = (h.get("description") or "").lower()
        if d and not re.search(r"brasil|brazil|polit|minist|jurist|juiz|judge|econom|advogad|lawyer|diplomat|military|militar|servidor|engenh|professor|empres|banqueir|econom", d): continue
        try:
            ent = wd({"action": "wbgetentities", "ids": h["id"], "props": "claims"})["entities"][h["id"]]
        except Exception: continue
        cl = ent.get("claims", {})
        if not any((c.get("mainsnak", {}).get("datavalue", {}).get("value", {}) or {}).get("id") == "Q5" for c in cl.get("P31", [])): continue
        for c in cl.get("P18", [])[:1]:
            try: return "https://commons.wikimedia.org/wiki/Special:FilePath/" + urllib.parse.quote(c["mainsnak"]["datavalue"]["value"])
            except Exception: pass
        return None
    return None

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--limit", type=int); a = ap.parse_args()
    g = json.load(open(ROOT / "build" / "graph.br.json", encoding="utf-8"))
    cache_p = ROOT / "build" / "cache-fotos.json"; cache = json.load(open(cache_p)) if cache_p.exists() else {}
    # sem foto de origem: tenta o Wikidata pelo nome (só quem não é parlamentar; eles já vêm com foto oficial)
    import yaml
    blocked = set((yaml.safe_load(open(ROOT / "data" / "fotos-bloqueadas.yaml", encoding="utf-8")) or []) if (ROOT / "data" / "fotos-bloqueadas.yaml").exists() else [])
    for p in g["people"].values():
        if p.get("image") or p.get("source") == "api": continue
        if p["id"] in blocked: p["image"] = None; continue
        if p["id"] in cache: p["image"] = cache[p["id"]]; continue
        img = None
        for v in name_variants(p["name"]):
            img = wikidata_image(v)
            if img: break
            time.sleep(0.6)
        if not img:
            for v in name_variants(p["name"]):
                img = commons_image(v); time.sleep(1.2)
                if img: break
            if img: print("commons:", p["name"], "->", img[-60:], file=sys.stderr)
        cache[p["id"]] = img; p["image"] = img; time.sleep(0.6)
        print("wikidata:", p["name"], "->", "foto" if img else "—", file=sys.stderr)
    json.dump(cache, open(cache_p, "w"), ensure_ascii=False)
    people = [p for p in g["people"].values() if p.get("image")]
    if a.limit: people = people[:a.limit]
    ok = skip = fail = 0
    for i, p in enumerate(people):
        dst = OUT / (p["id"] + ".jpg")
        if dst.exists(): skip += 1; continue
        try:
            im = Image.open(io.BytesIO(fetch(p["image"]))); im = ImageOps.exif_transpose(im).convert("RGB")
            im = ImageOps.fit(im, (96, 96), Image.LANCZOS, centering=(0.5, 0.3))
            im.save(dst, "JPEG", quality=78, optimize=True); ok += 1
        except Exception as e:
            fail += 1
        if i % 50 == 0: print(f"[{i}/{len(people)}] ok={ok} fail={fail}", file=sys.stderr)
        time.sleep(0.15)
    print(f"fotos: ok={ok} já existiam={skip} falhas={fail} de {len(people)}")

if __name__ == "__main__": main()
