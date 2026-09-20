#!/usr/bin/env python3
"""Placar da omissão → data/generated/omissao.yaml.

Decisões que têm prazo ou rito e não aconteceram, com o responsável pelo próximo passo:
  - vetos presidenciais em tramitação (Senado, /materia/vetos/{ano} e /materia/vetos/antesrcn); prazo: 30 dias (CF art. 66 §4º)
  - medidas provisórias em tramitação (Senado, /processo?sigla=MPV&tramitando=S + /processo/prazo); prazo: 60+60 dias (CF art. 62)
  - requerimentos de CPI na Câmara (RCP) com assinaturas e situação (Câmara, /proposicoes + /autores); mínimo 171 assinaturas
  - casos curados em data/omissao-curado.yaml (CPMI, denúncias)
Uso: .venv/bin/python etl/omissao.py
"""
import json, re, sys, time, pathlib, datetime, urllib.request, urllib.parse
import yaml
ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = {"User-Agent": "Mozilla/5.0 (Macintosh) atlas-da-republica/0.1", "Accept": "application/json"}
TODAY = datetime.date.today()
def get(url, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90) as r: return json.load(r)
        except Exception as e:
            if i == tries - 1: print("falha", url, e, file=sys.stderr); return None
            time.sleep(3 * (i + 1))
def lst(x): return x if isinstance(x, list) else ([x] if x else [])
def days(d): 
    try: return (TODAY - datetime.date.fromisoformat(str(d)[:10])).days
    except Exception: return None

def vetos():
    out = []
    seen = set()
    def add(v):
        m = v.get("Materia") or {}
        if m.get("EmTramitacao") != "Sim" or v.get("Codigo") in seen: return
        seen.add(v.get("Codigo"))
        mv = v.get("MateriaVetada") or {}; norma = mv.get("NormaGerada") or {}
        dm = re.search(r"(\d{2})/(\d{2})/(\d{4})", norma.get("NomeNorma") or "")
        date = f"{dm.group(3)}-{dm.group(2)}-{dm.group(1)}" if dm else None
        out.append({"kind": "veto", "id": f"veto-{v.get('Codigo')}", "code": v.get("Codigo"), "title": f"Veto {m.get('Numero')}/{m.get('Ano')}",
                    "summary": (v.get("DescricaoVeto") or m.get("Ementa") or "")[:400], "materia": f"{mv.get('Sigla')} {mv.get('Numero')}/{mv.get('Ano')}",
                    "norma": norma.get("NomeNorma"), "date": date, "days": days(date) if date else None, "deadline_days": 30,
                    "overdue": (days(date) or 0) > 30 if date else None, "responsible_position": "br-presidente-do-senado-federal",
                    "url": f"https://www.congressonacional.leg.br/materias/vetos/-/veto/detalhe/{v.get('Codigo')}"})
    for ano in range(2019, TODAY.year + 1):
        d = get(f"https://legis.senado.leg.br/dadosabertos/materia/vetos/{ano}") or {}
        for v in lst(((d.get("ListaVetosAnoCN") or {}).get("Vetos") or {}).get("Veto")): add(v)
        time.sleep(0.5)
    d = get("https://legis.senado.leg.br/dadosabertos/materia/vetos/antesrcn") or {}
    for v in lst(((d.get("VetosAntesRcnTramitandoCN") or {}).get("Vetos") or {}).get("Veto")): add(v)
    out.sort(key=lambda x: -(x["days"] or 0))
    return out

def mpvs():
    out = []
    for p in get("https://legis.senado.leg.br/dadosabertos/processo?sigla=MPV&tramitando=S") or []:
        prazos = get(f"https://legis.senado.leg.br/dadosabertos/processo/prazo?idProcesso={p.get('id')}") or []
        time.sleep(0.4)
        delib = [z for z in prazos if "Delibera" in (z.get("tipoPrazo") or "")]
        cur = sorted(delib, key=lambda z: str(z.get("inicioPrazo") or ""))[-1] if delib else None
        fim = (cur or {}).get("fimPrazo"); suspended = bool(cur and cur.get("siglaTipoFase") == "S")
        val = re.search(r"R\$\s?([\d\.]+,\d{2})", p.get("ementa") or "")
        value = float(val.group(1).replace(".", "").replace(",", ".")) if val else None
        left = -days(fim) if fim else None
        out.append({"kind": "mpv", "id": f"mpv-{p.get('codigoMateria')}", "title": p.get("identificacao"), "summary": (p.get("apelido") or p.get("ementa") or "")[:300],
                    "date": p.get("dataApresentacao"), "days": days(p.get("dataApresentacao")), "deadline": fim, "days_left": left, "suspended": suspended,
                    "prorogued": (cur or {}).get("prorrogado") == "Sim", "status": p.get("situacaoAtual"), "value": value,
                    "responsible_position": "br-presidente-da-camara-dos-deputados" if (p.get("situacaoAtual") or "").upper() not in ("SOBRESTADA",) else "br-presidente-do-senado-federal",
                    "url": f"https://www.congressonacional.leg.br/materias/medidas-provisorias/-/mpv/{p.get('codigoMateria')}"})
    out.sort(key=lambda x: (x["days_left"] if x["days_left"] is not None else 9999))
    return out

def rcps():
    out = []
    for ano in range(2023, TODAY.year + 1):
        d = get(f"https://dadosabertos.camara.leg.br/api/v2/proposicoes?siglaTipo=RCP&ano={ano}&itens=100") or {}
        for p in d.get("dados") or []:
            det = (get(f"https://dadosabertos.camara.leg.br/api/v2/proposicoes/{p['id']}") or {}).get("dados") or {}
            aut = (get(f"https://dadosabertos.camara.leg.br/api/v2/proposicoes/{p['id']}/autores") or {}).get("dados") or []
            time.sleep(0.3)
            st = det.get("statusProposicao") or {}
            sit = st.get("descricaoSituacao") or ""; desp = st.get("despacho") or ""
            status = ("indeferido" if re.search(r"indefer", desp, re.I) else "instalada" if re.search(r"criada|instala|constitu|pela CPI|CPI sobre", desp + sit, re.I) or ("Finalizada" in sit and re.search(r"CPI", desp)) else "arquivado" if re.search(r"arquiv", sit + desp, re.I) else "aguardando" if re.search(r"aguard", sit, re.I) else "outro")
            out.append({"kind": "rcp", "id": f"rcp-{p['id']}", "title": f"RCP {p['numero']}/{p['ano']}", "summary": (p.get("ementa") or "")[:300], "date": (p.get("dataApresentacao") or "")[:10],
                        "days": days(p.get("dataApresentacao")), "signatures": len(aut), "min_signatures": 171, "enough": len(aut) >= 171, "status": status, "situation": sit, "despacho": desp[:200],
                        "last_move": (st.get("dataHora") or "")[:10], "responsible_position": "br-presidente-da-camara-dos-deputados",
                        "url": f"https://www.camara.leg.br/proposicoesWeb/fichadetramitacao?idProposicao={p['id']}"})
    out.sort(key=lambda x: -(x["days"] or 0))
    return out

def main():
    cur = yaml.safe_load(open(ROOT / "data" / "omissao-curado.yaml", encoding="utf-8")) or []
    curated = []
    for c in cur:
        c = dict(c); c["days"] = days(c.get("filed_at")); c["date"] = str(c.get("filed_at")); c["curated"] = True; curated.append(c)
    data = {"generated_at": TODAY.isoformat(), "vetos": vetos(), "mpvs": mpvs(), "rcps": rcps(), "curated": curated}
    v = data["vetos"]; m = data["mpvs"]; r = data["rcps"]
    data["summary"] = {"vetos_pendentes": len(v), "vetos_vencidos": sum(1 for x in v if x.get("overdue")), "veto_mais_antigo_dias": (v[0]["days"] if v else None),
                       "mpvs_tramitando": len(m), "mpvs_ate_30_dias": sum(1 for x in m if x.get("days_left") is not None and 0 <= x["days_left"] <= 30), "mpvs_valor_em_risco": sum((x.get("value") or 0) for x in m if x.get("value") and x.get("days_left") is not None and x["days_left"] <= 30),
                       "rcps_aguardando": sum(1 for x in r if x["status"] == "aguardando"), "rcps_com_assinaturas_aguardando": sum(1 for x in r if x["status"] == "aguardando" and x["enough"]), "rcps_indeferidos": sum(1 for x in r if x["status"] == "indeferido"),
                       "curados": len(curated)}
    (ROOT / "data" / "generated" / "omissao.yaml").write_text("# GERADO por etl/omissao.py. Não edite à mão.\n" + yaml.dump(data, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    print(json.dumps(data["summary"], ensure_ascii=False))
    for x in v[:5]: print("  veto", x["title"], x["date"], x["days"], "dias |", (x["summary"] or "")[:60])
    for x in m[:8]: print("  mpv", x["title"], "prazo", x["deadline"], "faltam", x["days_left"], "|", x["status"], "|", x.get("value"))
    for x in r[:12]: print("  rcp", x["title"], x["date"], x["signatures"], "ass.", x["status"], "|", (x["summary"] or "")[:60])
if __name__ == "__main__": main()
