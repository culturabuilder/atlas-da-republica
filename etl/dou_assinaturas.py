#!/usr/bin/env python3
"""Dirigentes atuais pela assinatura do ato mais recente no DOU → data/generated/dou-assinaturas.yaml

Para cada órgão com cargo de chefia (autarquias, agências, fundações, órgãos singulares, empresas), busca na
Seção 2 do último mês a frase "<CARGO> DO/DA <ÓRGÃO>" (ex.: "PRESIDENTE DO INSTITUTO NACIONAL DO SEGURO SOCIAL"),
pega o ato mais recente cujo preâmbulo começa com esse cargo e lê o nome em <p class="assina">. Assinaturas de
substitutos são ignoradas. Uma consulta a cada 2,5 s.
Uso: .venv/bin/python etl/dou_assinaturas.py [--limit N]
"""
import json, re, sys, html, pathlib, argparse, datetime, urllib.parse, unicodedata
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import dou
import yaml
ROOT = pathlib.Path(__file__).resolve().parent.parent
SUBTYPES = {"autarquia", "agencia_reguladora", "fundacao", "orgao_singular", "empresa_publica", "sociedade_economia_mista", "ministerio_publico", "defensoria", "advocacia"}

def norm(s): return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().upper()

def search(phrase):
    p = {"q": f'"{phrase}"', "s": "do2", "exactDate": "mes", "sortType": "0"}
    h = dou.get("https://www.in.gov.br/consulta/-/buscar/dou?" + urllib.parse.urlencode(p))
    m = re.search(r'BuscaDouPortlet_params"[^>]*>(.*?)</script>', h, re.S)
    try: return json.loads(m.group(1)).get("jsonArray", []) if m else []
    except Exception: return []

def signature(url_title):
    h = dou.get("https://www.in.gov.br/web/dou/-/" + url_title)
    clean = lambda x: re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", x))).strip()
    names = [clean(x) for x in re.findall(r'<p class="assina">(.*?)</p>', h, re.S)]
    cargos = [clean(x) for x in re.findall(r'<p class="cargo">(.*?)</p>', h, re.S)]
    return names, cargos

def role_phrase(position_name, org_name):
    """'Presidente do Ibama' -> 'PRESIDENTE DO INSTITUTO BRASILEIRO ...' (nome completo do órgão, sem artigo)."""
    role = re.match(r"^(Diretor-Presidente|Diretor-Geral|Diretora-Presidente|Presidente|Superintendente|Diretor-Superintendente|Procurador-Geral|Defensor Público-Geral|Advogado-Geral|Secretário Especial|Secretário|Comandante|Diretor)", position_name)
    if not role: return None
    art = "DA" if re.match(r"^(Agência|Fundação|Comissão|Superintendência|Empresa|Companhia|Caixa|Casa|Escola|Financiadora|Procuradoria|Defensoria|Advocacia|Secretaria|Polícia|Marinha|Força)", org_name) else "DO"
    short = " ".join(norm(org_name).split()[:5])   # a busca e o trecho do resultado truncam nomes longos
    return f"{norm(role.group(1))} {art} {short}"

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--limit", type=int); a = ap.parse_args()
    g = json.load(open(ROOT / "build" / "graph.br.json", encoding="utf-8")); N = g["nodes"]
    targets = []
    for n in N.values():
        if n["type"] != "dept_head" or (n.get("seats") or 1) != 1: continue
        org = N.get(n.get("head_of") or "")
        if not org or org.get("subtype") not in SUBTYPES: continue
        if n.get("people") and n["people"][0].get("source") in ("oficial",): continue
        ph = role_phrase(n["name"], org["name"])
        if ph: targets.append((n, org, ph))
    if a.limit: targets = targets[:a.limit]
    out, today = {}, datetime.date.today().isoformat()
    prev = {}
    pf = ROOT / "data" / "generated" / "dou-assinaturas.yaml"
    if pf.exists(): prev = (yaml.safe_load(open(pf, encoding="utf-8")) or {}).get("positions") or {}
    out.update(prev)
    def variants(ph, org, pos_name=""):
        vs = [ph]
        pn = norm(re.sub(r"^(Diretor|Diretora|Presidente|Superintendente|Procurador|Defensor|Advogado|Secretário|Comandante)[^ ]*( Especial| Público-Geral| Geral)?", lambda m: m.group(0), pos_name))
        if pn and pn != ph: vs.insert(0, pn)   # o próprio nome do cargo ("PROCURADOR-GERAL DA REPUBLICA", "DIRETOR-GERAL DA POLICIA FEDERAL")
        vs.append(re.sub(r"^PRESIDENTE ", "PRESIDENTA ", ph)); vs.append(re.sub(r"^DIRETOR-", "DIRETORA-", ph)); vs.append(re.sub(r"^DIRETOR ", "DIRETORA ", ph))
        for a in org.get("aliases") or []:
            if a.isupper() and 2 < len(a) <= 8: vs.append(re.sub(r" D[OA] .*$", (" DA " if ph.split(" ")[1] == "DA" else " DO ") + norm(a), ph))
        return list(dict.fromkeys(vs))
    for i, (n, org, ph) in enumerate(targets):
        if n["id"] in prev: continue
        found = None
        for v in variants(ph, org, n['name']):
            items = search(v)
            if not items: continue
            for it in items[:10]:
                sn = norm(re.sub(r"<[^>]+>", " ", it.get("content") or ""))
                if not re.search(r"\b(O|A)\s+" + re.escape(v), sn[:600]): continue
                ph = v; break
            else: continue
            break
        for it in (items if found is None and items else [])[:10]:
            sn = norm(re.sub(r"<[^>]+>", " ", it.get("content") or ""))
            if not re.search(r"\b(O|A)\s+" + re.escape(ph), sn[:600]): continue
            names, cargos = signature(it["urlTitle"])
            if not names: continue
            if any(re.search(r"substitut|interin|exerc[íi]cio", c, re.I) for c in cargos): continue
            d = it.get("pubDate", ""); date = f"{d[6:10]}-{d[3:5]}-{d[0:2]}" if re.match(r"\d\d/\d\d/\d{4}", d) else today
            nm = names[-1]
            if nm.isupper(): nm = " ".join(w.lower() if w.lower() in ("de", "da", "do", "das", "dos", "e") else w.capitalize() for w in nm.split())
            found = {"id": "br-p-dou-" + re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", nm).encode("ascii", "ignore").decode().lower()), "name": nm,
                     "source": "dou", "verified": False, "entry_mode": "nomeado", "evidence_date": date, "evidence": it.get("title"),
                     "source_url": "https://www.in.gov.br/web/dou/-/" + it["urlTitle"], "note": "assina atos como titular; data de posse não consta"}
            break
        print(f"[{i+1}/{len(targets)}] {n['name'][:45]:45} -> {found['name'] if found else '—'}", file=sys.stderr)
        if found: out[n["id"]] = [found]
        class D(yaml.SafeDumper):
            def increase_indent(self, flow=False, indentless=False): return super().increase_indent(flow, False)
        (ROOT / "data" / "generated" / "dou-assinaturas.yaml").write_text("# GERADO por etl/dou_assinaturas.py: dirigente = quem assina os atos do órgão no DOU (Seção 2, último mês).\n" + yaml.dump({"generated_at": today, "positions": out}, Dumper=D, allow_unicode=True, sort_keys=False, width=110), encoding="utf-8")
    print(f"cargos alvo={len(targets)} encontrados={len(out)}")

if __name__ == "__main__": main()
