#!/usr/bin/env python3
"""Fotos de páginas oficiais listadas em data/fotos-oficiais.yaml (nome -> url) → site/img/<id>.jpg.
Casa o nome com as pessoas do grafo (normalizado) e grava também no manifesto nome->foto.
Uso: .venv/bin/python etl/fotos_oficiais.py
"""
import json, io, re, sys, time, pathlib, unicodedata, urllib.request
import yaml
from PIL import Image, ImageOps
ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "img"; OUT.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36", "Accept": "image/*,*/*;q=0.8"}
def norm(s): return re.sub(r"[^a-z ]", "", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()).strip()
def main():
    g = json.load(open(ROOT / "build" / "graph.br.json", encoding="utf-8")); P = g["people"]
    byname = {}
    for p in P.values(): byname.setdefault(norm(p["name"]), []).append(p["id"])
    blocks = yaml.safe_load(open(ROOT / "data" / "fotos-oficiais.yaml", encoding="utf-8")) or []
    ok = miss = fail = 0
    for b in blocks:
        for name, url in (b.get("fotos") or {}).items():
            ids = byname.get(norm(name))
            if not ids: miss += 1; print("sem pessoa no grafo:", name, file=sys.stderr); continue
            try:
                try: data = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read()
                except Exception:  # certificados incompletos em alguns portais: curl usa a cadeia do sistema
                    import subprocess; data = subprocess.run(["curl", "-sL", "-m", "60", "-A", UA["User-Agent"], url], capture_output=True).stdout
                im = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
                im = ImageOps.fit(im, (96, 96), Image.LANCZOS, centering=(0.5, 0.25))
                for pid in ids: im.save(OUT / (pid + ".jpg"), "JPEG", quality=78, optimize=True)
                ok += 1
            except Exception as e: fail += 1; print("falhou:", name, e, file=sys.stderr)
            time.sleep(0.5)
    print(f"fotos oficiais: ok={ok} sem pessoa={miss} falhas={fail}")
if __name__ == "__main__": main()
