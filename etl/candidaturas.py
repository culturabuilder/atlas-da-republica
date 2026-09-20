#!/usr/bin/env python3
"""Candidaturas dos ocupantes de cargos → data/generated/candidaturas.yaml.

Fonte: TSE, "Candidatos" (consulta_cand_{ano}.zip, baixados manualmente em build/cache-tse/ porque o CDN do TSE bloqueia
acesso automatizado). Para cada pessoa do grafo, as candidaturas encontradas por nome completo idêntico (normalizado):
ano, cargo disputado, partido, UF/município e resultado. Quando a pessoa tem data de nascimento conhecida (Wikidata) e a
candidatura também, a data precisa bater; nomes com até três palavras são marcados como "possível homônimo".
Não é filiação: é o partido pelo qual a pessoa concorreu naquela eleição.
Uso: .venv/bin/python etl/candidaturas.py
"""
import csv, io, re, sys, zipfile, pathlib, datetime, unicodedata, collections, json
import yaml
ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / "build" / "cache-tse"
def norm(s): return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())).strip()
def main():
    g = json.load(open(ROOT / "build" / "graph.br.json", encoding="utf-8")); P = g["people"]; N = g["nodes"]
    nasc_p = ROOT / "data" / "generated" / "nascimentos.yaml"
    nasc = ((yaml.safe_load(open(nasc_p, encoding="utf-8")) or {}).get("people") or {}) if nasc_p.exists() else {}
    # nome completo por pessoa: senadores têm full_name; demais usam o nome do registro
    full = {}
    for nid, n in N.items():
        for p in n.get("people") or []:
            if p.get("id"): full.setdefault(p["id"], p.get("full_name") or p.get("name"))
    for pid, p in P.items(): full.setdefault(pid, p.get("name"))
    by_name = collections.defaultdict(list)
    for pid, nm in full.items(): by_name[norm(nm)].append(pid)
    # nome de urna: só casa quando é único entre todos os candidatos do arquivo e tem duas ou mais palavras (conservador)
    short = collections.defaultdict(list)
    for pid, p in P.items(): short[norm(p.get("name"))].append(pid)
    urna_count = collections.Counter(); urna_rows = []
    found = collections.defaultdict(list); rows = 0
    if not list(CACHE.glob("consulta_cand_*.zip")): print("candidaturas: arquivos consulta_cand_*.zip ausentes (download manual do TSE); mantendo o gerado anterior", file=sys.stderr); return
    for zp in sorted(CACHE.glob("consulta_cand_*.zip")):
        z = zipfile.ZipFile(zp)
        for name in sorted(z.namelist()):
            if not name.endswith(".csv") or re.search(r"_(BR|BRASIL)\.csv$", name): continue  # o arquivo BRASIL repete os arquivos por UF
            with z.open(name) as f:
                r = csv.reader(io.TextIOWrapper(f, encoding="latin1"), delimiter=";"); head = next(r); ix = {h: i for i, h in enumerate(head)}
                I = {k: ix[k] for k in ("ANO_ELEICAO", "NR_TURNO", "SG_UF", "NM_UE", "DS_CARGO", "NM_CANDIDATO", "NM_URNA_CANDIDATO", "SG_PARTIDO", "DT_NASCIMENTO", "DS_SIT_TOT_TURNO", "DS_SITUACAO_CANDIDATURA")}
                for row in r:
                    rows += 1
                    if row[I["NR_TURNO"]] != "1": continue
                    k = norm(row[I["NM_CANDIDATO"]]); ku = norm(row[I["NM_URNA_CANDIDATO"]])
                    if ku in short and len(ku.split()) >= 2: urna_count[(int(row[I["ANO_ELEICAO"]]), ku)] += 1; urna_rows.append((ku, [row[i] for i in range(len(row))], I))
                    if k not in by_name: continue
                    dn = row[I["DT_NASCIMENTO"]]; birth = f"{dn[6:10]}-{dn[3:5]}-{dn[0:2]}" if re.match(r"\d{2}/\d{2}/\d{4}", dn) else None
                    for pid in by_name[k]:
                        nb = (nasc.get(pid) or {}).get("birth")
                        if nb and birth and str(nb)[:10] != birth: continue
                        found[pid].append({"ano": int(row[I["ANO_ELEICAO"]]), "cargo": row[I["DS_CARGO"]].title(), "partido": row[I["SG_PARTIDO"]], "uf": row[I["SG_UF"]], "ue": row[I["NM_UE"]].title(),
                                           "urna": row[I["NM_URNA_CANDIDATO"]].title(), "resultado": (row[I["DS_SIT_TOT_TURNO"]] or "").title().replace("#Nulo", "").strip() or None, "situacao": row[I["DS_SITUACAO_CANDIDATURA"]].title(),
                                           "confirmado_por_nascimento": bool(nb and birth), "possivel_homonimo": (len(k.split()) <= 3) and not (nb and birth)})
        print(zp.name, "lido", file=sys.stderr, flush=True)
    # segunda passada: urna única no ano, pessoa sem casamento por nome completo
    for ku, row, I in urna_rows:
        ano = int(row[I["ANO_ELEICAO"]])
        if urna_count[(ano, ku)] != 1: continue
        for pid in short[ku]:
            if pid in found: continue
            nb = (nasc.get(pid) or {}).get("birth"); dn = row[I["DT_NASCIMENTO"]]; birth = f"{dn[6:10]}-{dn[3:5]}-{dn[0:2]}" if re.match(r"\d{2}/\d{2}/\d{4}", dn) else None
            if nb and birth and str(nb)[:10] != birth: continue
            found[pid].append({"ano": ano, "cargo": row[I["DS_CARGO"]].title(), "partido": row[I["SG_PARTIDO"]], "uf": row[I["SG_UF"]], "ue": row[I["NM_UE"]].title(), "urna": row[I["NM_URNA_CANDIDATO"]].title(),
                               "resultado": (row[I["DS_SIT_TOT_TURNO"]] or "").title().replace("#Nulo", "").strip() or None, "situacao": row[I["DS_SITUACAO_CANDIDATURA"]].title(), "confirmado_por_nascimento": bool(nb and birth), "possivel_homonimo": not (nb and birth), "casado_por": "nome de urna único"})
    out = {}
    elect_pos = {pid: {q["id"] for q in (P.get(pid) or {}).get("positions") or []} for pid in found}
    for pid, lst in found.items():
        # quem é deputado/senador no grafo e aparece como candidato ao mesmo cargo em 2022 é a mesma pessoa: sem dúvida de homônimo
        for c in lst:
            same = (c["ano"] == 2022 and ((c["cargo"] == "Deputado Federal" and "br-deputado-federal" in elect_pos[pid]) or (c["cargo"] == "Senador" and "br-senador" in elect_pos[pid])) and str(c.get("resultado") or "").startswith("Eleito"))
            if same: c["possivel_homonimo"] = False; c["confirmado_por_nascimento"] = c.get("confirmado_por_nascimento", False); c["casado_por"] = "mandato atual"
        seen = set(); uniq = []
        for c in sorted(lst, key=lambda c: (-c["ano"], c["cargo"])):
            key = (c["ano"], c["cargo"], c["partido"], c["ue"])
            if key in seen: continue
            seen.add(key); uniq.append(c)
        out[pid] = uniq
    data = {"generated_at": datetime.date.today().isoformat(), "fonte": "TSE, Candidatos 2022 e 2024 (consulta_cand)", "people": out}
    (ROOT / "data" / "generated" / "candidaturas.yaml").write_text("# GERADO por etl/candidaturas.py. Não edite à mão. Partido pelo qual a pessoa concorreu; não é filiação.\n" + yaml.dump(data, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    hom = sum(1 for v in out.values() if any(c["possivel_homonimo"] for c in v))
    print(f"candidaturas: {rows} linhas lidas; {len(out)} pessoas do grafo com candidatura em 2022/2024 ({hom} com possível homônimo)")
    # amostra: ocupantes de cargos nomeados (não eletivos)
    elect = {"br-deputado-federal", "br-senador", "br-presidente-da-republica", "br-vice-presidente-da-republica"}
    nom = [(pid, v) for pid, v in out.items() if not (set(q["id"] for q in (P.get(pid) or {}).get("positions") or []) & elect)]
    print(f"  em cargos não eletivos: {len(nom)}")
    for pid, v in nom[:8]: print("   ", full.get(pid), "->", [(c["ano"], c["cargo"], c["partido"], c["resultado"]) for c in v[:2]], "| homônimo?" if any(c["possivel_homonimo"] for c in v) else "")
if __name__ == "__main__": main()
