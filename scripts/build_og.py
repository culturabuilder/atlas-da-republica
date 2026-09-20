#!/usr/bin/env python3
"""Imagens Open Graph (1200×630 PNG) do Atlas da República: uma por pessoa, uma por órgão, home e área educativa.

Chamado por scripts/build_site.py: build(site_dir, prefix, base, G) -> {id: "og/<id>.png"} (caminho relativo à raiz do site).
Também roda sozinho para teste: .venv/bin/python scripts/build_og.py
Usa fontes do sistema (Helvetica/Arial) porque as fontes web não estão no disco.
"""
import json, pathlib, time, re
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = pathlib.Path(__file__).resolve().parent.parent
W, H = 1200, 630
BG, INK, INK2, INK3, LINE, POVO = "#131412", "#ECEDE8", "#BDC0B8", "#9A9E95", "#33362F", "#C25A12"
SECTOR_COLOR = {"legislativo": "#B8452E", "executivo": "#3B4C9B", "judiciario": "#8A6C10", "essenciais": "#5E3D7A"}
SECTOR_LIGHT = {"legislativo": "#F0907A", "executivo": "#9AA6EE", "judiciario": "#E2C25A", "essenciais": "#C9A3E6"}  # para texto sobre fundo escuro
SUBTYPE = {"instituicao_de_ensino": "Instituição de ensino", "tribunal": "Tribunal", "empresa_publica": "Empresa pública", "ministerio": "Ministério", "autarquia": "Autarquia", "sociedade_economia_mista": "Sociedade de economia mista", "fundacao": "Fundação", "secao_judiciaria": "Seção judiciária", "agencia_reguladora": "Agência reguladora", "orgao_singular": "Órgão singular", "orgao_presidencia": "Órgão da Presidência", "ministerio_publico": "Ministério Público", "advocacia": "Advocacia pública", "casa_legislativa": "Casa legislativa", "forca_armada": "Força Armada", "chefia_executivo": "Chefia do Executivo", "defensoria": "Defensoria", "orgao_autonomo": "Órgão autônomo"}
ENTRY = {"eleito": "eleito", "nomeado": "nomeado", "suplente": "suplente"}

# ---------- fontes (carregadas uma vez por tamanho) ----------
_CANDIDATES = {
    "bold": [("/System/Library/Fonts/Helvetica.ttc", 1), ("/System/Library/Fonts/HelveticaNeue.ttc", 1), ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 0), ("/Library/Fonts/Arial Bold.ttf", 0), ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0)],
    "regular": [("/System/Library/Fonts/Helvetica.ttc", 0), ("/System/Library/Fonts/HelveticaNeue.ttc", 0), ("/System/Library/Fonts/Supplemental/Arial.ttf", 0), ("/Library/Fonts/Arial.ttf", 0), ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 0)],
}
_FONT_FILE = {}
_FONTS = {}


def _resolve(kind):
    if kind in _FONT_FILE: return _FONT_FILE[kind]
    for path, idx in _CANDIDATES[kind]:
        try:
            ImageFont.truetype(path, 20, index=idx); _FONT_FILE[kind] = (path, idx); return _FONT_FILE[kind]
        except Exception: continue
    _FONT_FILE[kind] = None; return None


def font(kind, size):
    key = (kind, size)
    if key in _FONTS: return _FONTS[key]
    f = _resolve(kind)
    try: _FONTS[key] = ImageFont.truetype(f[0], size, index=f[1]) if f else ImageFont.load_default(size=size)
    except Exception:
        try: _FONTS[key] = ImageFont.load_default(size=size)
        except Exception: _FONTS[key] = ImageFont.load_default()
    return _FONTS[key]


def wrap(text, f, maxw):
    words = (text or "").split(); lines = []; cur = ""
    for w in words:
        t = (cur + " " + w).strip()
        if f.getlength(t) <= maxw or not cur: cur = t
        else: lines.append(cur); cur = w
    if cur: lines.append(cur)
    # palavra maior que a linha: corta com reticências
    out = []
    for ln in lines:
        while f.getlength(ln) > maxw and len(ln) > 3: ln = ln[:-2].rstrip() + "…"
        out.append(ln)
    return out


def fit(text, kind, sizes, maxw, maxlines):
    """Escolhe o maior tamanho da lista em que o texto cabe em maxlines linhas."""
    for s in sizes:
        f = font(kind, s); lines = wrap(text, f, maxw)
        if len(lines) <= maxlines: return f, lines, s
    f = font(kind, sizes[-1]); lines = wrap(text, f, maxw)[:maxlines]
    if lines: lines[-1] = (lines[-1][:-1] if lines[-1].endswith("…") else lines[-1]).rstrip() + "…"
    return f, lines, sizes[-1]


def draw_lines(d, x, y, lines, f, size, fill, lh=1.12):
    for ln in lines:
        d.text((x, y), ln, font=f, fill=fill); y += int(size * lh)
    return y


def ellipsize(text, f, maxw):
    text = text or ""
    if f.getlength(text) <= maxw: return text
    while f.getlength(text + "…") > maxw and len(text) > 1: text = text[:-1]
    return text.rstrip() + "…"


# ---------- moldura comum ----------
def frame(base_url, accent=None):
    im = Image.new("RGB", (W, H), BG); d = ImageDraw.Draw(im)
    if accent: d.rectangle([0, 0, 14, H], fill=accent)
    # marca
    d.ellipse([56, 54, 80, 78], fill=POVO); d.ellipse([52, 50, 84, 82], outline=POVO, width=2)
    d.text((96, 50), "Atlas da República", font=font("bold", 26), fill=INK)
    # rodapé
    d.line([56, H - 78, W - 56, H - 78], fill=LINE, width=1)
    d.text((56, H - 62), base_url.replace("https://", "").replace("http://", "").rstrip("/"), font=font("regular", 22), fill=INK3)
    return im, d


def _photo(pid, size=280):
    p = ROOT / "assets" / "img" / f"{pid}.jpg"
    if not p.exists(): return None
    try:
        im = Image.open(p).convert("RGB")
        im = ImageOps.fit(im, (size, size), Image.LANCZOS)
        mask = Image.new("L", (size * 2, size * 2), 0); ImageDraw.Draw(mask).ellipse([0, 0, size * 2 - 1, size * 2 - 1], fill=255)
        return im, mask.resize((size, size), Image.LANCZOS)
    except Exception: return None


def og_person(p, G, base_url):
    im, d = frame(base_url)
    x = 56; textw = W - 112
    ph = _photo(p["id"]) if p.get("photo") else None
    if ph:
        pic, mask = ph; im.paste(pic, (56, 180), mask)
        d.ellipse([52, 176, 56 + 280 + 3, 180 + 280 + 3], outline=LINE, width=3)
        x = 56 + 280 + 48; textw = W - x - 56
    pos = p.get("positions") or []
    main = pos[0] if pos else None
    N = G.get("nodes") or {}
    sector = (N.get(main["id"]) or {}).get("sector") if main else None
    eyebrow = "Pessoa" + (f" · {(next((s['name'] for s in G['layout']['sectors'] if s['id'] == sector), '') if sector else '')}" if sector else "")
    d.text((x, 150), eyebrow.upper(), font=font("regular", 20), fill=SECTOR_LIGHT.get(sector, INK3))
    f, lines, size = fit(p.get("name") or "", "bold", [72, 64, 56, 48, 40], textw, 2)
    y = draw_lines(d, x - 3, 186, lines, f, size, INK)
    if main:
        role = main.get("name") or ""
        if main.get("role") and main["role"] not in ("Titular",): role = f"{main['role']} · {role}"
        f2, l2, s2 = fit(role, "regular", [34, 30, 26], textw, 2)
        y = draw_lines(d, x, y + 14, l2, f2, s2, INK2)
        others = len({q["id"] for q in pos[1:]})
        if others: d.text((x, y + 6), f"+ {others} outro{'s' if others > 1 else ''} cargo{'s' if others > 1 else ''}", font=font("regular", 22), fill=INK3); y += 34
    tag = " · ".join(t for t in (p.get("party"), p.get("uf")) if t)
    if tag: d.text((x, min(y + 18, H - 130)), tag, font=font("bold", 26), fill=INK3)
    return im


def og_node(n, G, base_url):
    sector = n.get("sector"); accent = SECTOR_COLOR.get(sector)
    im, d = frame(base_url, accent)
    x = 56; textw = W - 112
    sname = next((s.get("short") or s["name"] for s in G["layout"]["sectors"] if s["id"] == sector), "") if sector else ""
    tname = (G["layout"].get("node_types") or {}).get(n.get("type"), {}).get("name") or ""
    kind = SUBTYPE.get(n.get("subtype")) or tname
    if n.get("subtype") and tname and SUBTYPE.get(n.get("subtype")) and n["type"] != "department": kind = f"{SUBTYPE[n['subtype']]} · {tname}"
    eyebrow = " · ".join(t for t in (sname, kind) if t)
    d.text((x, 150), ellipsize(eyebrow.upper(), font("regular", 20), textw), font=font("regular", 20), fill=SECTOR_LIGHT.get(sector, INK3))
    f, lines, size = fit(n.get("name") or "", "bold", [72, 64, 56, 48, 40, 34], textw, 3)
    y = draw_lines(d, x - 3, 186, lines, f, size, INK)
    parent = (G["nodes"].get(n.get("parent") or "") or {}).get("name")
    if parent and y < H - 150:
        d.text((x, y + 14), ellipsize(f"Integra {parent}", font("regular", 26), textw), font=font("regular", 26), fill=INK2); y += 50
    cite = n.get("cite")
    if cite and y < H - 130: d.text((x, y + 12), ellipsize(cite, font("regular", 22), textw), font=font("regular", 22), fill=INK3)
    seats = n.get("seats_count") or n.get("seats")
    if isinstance(seats, int) and seats > 1: d.text((W - 56 - font("bold", 26).getlength(f"{seats} cadeiras"), 54), f"{seats} cadeiras", font=font("bold", 26), fill=INK3)
    return im


def og_home(G, base_url):
    im, d = frame(base_url)
    st = G.get("stats") or {}
    d.text((56, 150), "GOVERNO FEDERAL DO BRASIL", font=font("regular", 20), fill=INK3)
    f, lines, size = fit("Quem manda em quê no governo federal", "bold", [72, 64], W - 112, 2)
    y = draw_lines(d, 53, 186, lines, f, size, INK)
    d.text((56, y + 14), "Cada órgão, cargo e colegiado da União e as relações legais entre eles, com a norma citada.", font=font("regular", 26), fill=INK2)
    y += 90; x = 56
    for n, l in ((st.get("nodes"), "órgãos e cargos"), (st.get("edges"), "relações"), (st.get("seats_filled"), f"de {st.get('seats_total')} cadeiras com ocupante")):
        if n is None: continue
        d.text((x, y), f"{n:,}".replace(",", "."), font=font("bold", 44), fill=INK); wn = font("bold", 44).getlength(f"{n:,}".replace(",", "."))
        d.text((x + wn + 10, y + 18), l, font=font("regular", 22), fill=INK3); x += wn + font("regular", 22).getlength(l) + 60
    # faixa de setores
    sx = 56
    for s in G["layout"]["sectors"]:
        d.rectangle([sx, H - 108, sx + 260, H - 96], fill=SECTOR_COLOR.get(s["id"], LINE)); sx += 272
    return im


def og_como_funciona(G, base_url):
    im, d = frame(base_url)
    d.text((56, 150), "ÁREA EDUCATIVA · 9 MINUTOS", font=font("regular", 20), fill=INK3)
    f, lines, size = fit("Como funciona a República", "bold", [80, 72], W - 112, 2)
    y = draw_lines(d, 53, 186, lines, f, size, INK)
    f2, l2, s2 = fit("Uma visita guiada pela roda: quem você elege, quem nomeia quem, quem vigia quem.", "regular", [30, 26], W - 112, 2)
    draw_lines(d, 56, y + 16, l2, f2, s2, INK2)
    sx = 56
    for s in G["layout"]["sectors"]:
        d.rectangle([sx, H - 108, sx + 260, H - 96], fill=SECTOR_COLOR.get(s["id"], LINE)); sx += 272
    return im


def save(im, path, colors):
    q = im.quantize(colors=colors, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.FLOYDSTEINBERG)
    q.save(path, "PNG", optimize=True)


def build(site_dir, prefix, base, G):
    site = pathlib.Path(site_dir); out = site / "og"; out.mkdir(parents=True, exist_ok=True)
    base_url = f"{base.rstrip('/')}{(prefix or '').rstrip('/')}"
    result = {}
    save(og_home(G, base_url), out / "atlas.png", 64); result["atlas"] = "og/atlas.png"
    save(og_como_funciona(G, base_url), out / "como-funciona.png", 64); result["como-funciona"] = "og/como-funciona.png"
    for n in G["nodes"].values():
        if n.get("type") == "dept_head": continue
        save(og_node(n, G, base_url), out / f"{n['id']}.png", 48); result[n["id"]] = f"og/{n['id']}.png"
    for p in G.get("people", {}).values():
        save(og_person(p, G, base_url), out / f"{p['id']}.png", 128 if p.get("photo") else 48); result[p["id"]] = f"og/{p['id']}.png"
    return result


if __name__ == "__main__":
    G = json.load(open(ROOT / "build" / "graph.br.json", encoding="utf-8"))
    t0 = time.time(); r = build(ROOT / "site", "", "http://localhost:8765", G); dt = time.time() - t0
    sizes = []
    for k, rel in r.items():
        p = ROOT / "site" / rel
        with Image.open(p) as im:
            assert im.size == (W, H), (k, im.size)
        sizes.append(p.stat().st_size)
    sizes.sort()
    print(f"{len(r)} imagens em {dt:.1f}s · tamanho min/mediana/max: {sizes[0] // 1024} / {sizes[len(sizes) // 2] // 1024} / {sizes[-1] // 1024} KB · total {sum(sizes) // 1024 // 1024} MB")
