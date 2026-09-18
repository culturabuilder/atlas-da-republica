#!/usr/bin/env python3
"""Portal da Transparência: ocupantes de CCE-18 (código CCX 011.8) por ministério → data/generated/portal-cce.yaml

Cria um cargo agregado por ministério ("Dirigentes CCE-18 do Ministério X": secretários-executivos, secretários
nacionais e especiais) com a lista de ocupantes, unidade de exercício e data de ingresso na função.
Requer PORTAL_TRANSPARENCIA_KEY. Uso: .venv/bin/python etl/portal_cce.py
"""
import json, os, re, sys, time, pathlib, datetime, urllib.request, urllib.parse, unicodedata, difflib
import yaml
ROOT = pathlib.Path(__file__).resolve().parent.parent
API = "https://api.portaldatransparencia.gov.br/api-de-dados"

def key():
    k = os.environ.get("PORTAL_TRANSPARENCIA_KEY")
    if not k and (ROOT / ".env").exists():
        for line in open(ROOT / ".env"):
            if line.startswith("PORTAL_TRANSPARENCIA_KEY="): k = line.split("=", 1)[1].strip()
    if not k: sys.exit("PORTAL_TRANSPARENCIA_KEY ausente")
    return k

def get(path, params, k):
    url = API + path + "?" + urllib.parse.urlencode(params)
    for i in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"chave-api-dados": k, "Accept": "application/json"}), timeout=90) as r: return json.load(r)
        except Exception: time.sleep(2 * (i + 1))
    return []

def norm(s): return re.sub(r"[^a-z0-9 ]", " ", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()).strip()
def cap(nm): return " ".join(w.lower() if w.lower() in ("de", "da", "do", "das", "dos", "e") else w.capitalize() for w in nm.split())

def main():
    k = key()
    g = json.load(open(ROOT / "build" / "graph.br.json", encoding="utf-8")); N = g["nodes"]
    siape = []
    for p in range(1, 60):
        page = get("/orgaos-siape", {"pagina": p}, k)
        if not page: break
        siape += page
    cand = [o for o in siape if str(o["codigo"]).endswith("000") or o["descricao"].startswith(("Presidência", "Advocacia", "Controladoria"))]
    mins = [n for n in N.values() if n.get("subtype") in ("ministerio", "orgao_presidencia") and n["ring"] <= 2 and n["type"] == "department"]
    out = {}; today = datetime.date.today().isoformat()
    for m in mins:
        best, score = None, 0
        for o in cand:
            r = difflib.SequenceMatcher(None, norm(m["name"]), norm(o["descricao"])).ratio()
            if r > score: best, score = o, r
        if not best or score < 0.6: print(f"{m['name'][:50]}: sem código SIAPE ({score:.2f})", file=sys.stderr); continue
        people = []
        for p in range(1, 12):
            rows = get("/servidores", {"orgaoServidorExercicio": best["codigo"], "codigoFuncaoCargo": "CCX0118", "pagina": p}, k)
            if not rows: break
            for y in rows:
                s = y["servidor"]; f = (y.get("fichasFuncao") or [{}])[0]
                d = f.get("dataIngressoFuncao") or ""; started = f"{d[6:10]}-{d[3:5]}-{d[0:2]}" if re.match(r"\d\d/\d\d/\d{4}", d) else None
                nm = cap(s["pessoa"]["nome"])
                people.append({"id": "br-p-pt-" + str(s["id"]), "name": nm, "started_at": started, "unit": (f.get("uorgExercicio") or "").strip().title() or None,
                               "role": "CCE-18", "entry_mode": "nomeado", "source": "portal", "verified": True, "source_url": f"https://portaldatransparencia.gov.br/servidores/{s['id']}"})
            if len(rows) < 15: break
            time.sleep(0.7)
        if people:
            pid = m["id"].replace("br-ministerio-", "br-dirigentes-cce18-").replace("br-", "br-dirigentes-cce18-", 1) if not m["id"].startswith("br-ministerio-") else m["id"].replace("br-ministerio-", "br-dirigentes-cce18-")
            out[pid] = {"head_of": m["id"], "siape": best["codigo"], "siape_name": best["descricao"], "people": people}
        print(f"{m['name'][:50]:50} SIAPE {best['codigo']} -> {len(people)} CCE-18", file=sys.stderr)
        time.sleep(0.7)
    class D(yaml.SafeDumper):
        def increase_indent(self, flow=False, indentless=False): return super().increase_indent(flow, False)
    (ROOT / "data" / "generated" / "portal-cce.yaml").write_text("# GERADO por etl/portal_cce.py (Portal da Transparência, CCX 011.8 por órgão). Não editar à mão.\n" + yaml.dump({"generated_at": today, "positions": out}, Dumper=D, allow_unicode=True, sort_keys=False, width=110), encoding="utf-8")
    print(f"ministérios={len(mins)} com CCE-18={len(out)} pessoas={sum(len(v['people']) for v in out.values())}")

if __name__ == "__main__": main()
