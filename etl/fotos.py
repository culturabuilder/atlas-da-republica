#!/usr/bin/env python3
"""Fotos dos ocupantes → site/img/<id-da-pessoa>.jpg (48×48 em JPEG). Fontes: Câmara, Senado, Wikimedia Commons.
Uso: .venv/bin/python etl/fotos.py [--limit N]
"""
import json, io, sys, time, pathlib, argparse, urllib.request
from PIL import Image, ImageOps
ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "img"; OUT.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "atlas-da-republica/0.1 (fotos; contato via github)"}

def fetch(url):
    if "commons.wikimedia.org" in url and "?width" not in url: url += "?width=160"
    r = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(r, timeout=40).read()

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--limit", type=int); a = ap.parse_args()
    g = json.load(open(ROOT / "build" / "graph.br.json", encoding="utf-8"))
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
