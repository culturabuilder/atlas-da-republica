# Atlas da República

Mapa navegável do governo federal brasileiro: cada órgão, cargo e colegiado da União e as relações legais
entre eles (quem elege, nomeia, sabatina, supervisiona, fiscaliza). Réplica, adaptada ao Brasil, da lógica do
[CivLab US Gov Graph](https://graph.civlab.org/us).

## Estado: Fase 2 em andamento

- `data/nodes/` e `data/edges/` — curadoria em YAML: 320 nós e as regras que geram as relações, cada uma com citação legal.
- `data/generated/siorg.yaml` — 330 órgãos e entidades e 214 colegiados nacionais importados do SIORG (`etl/siorg.py`); `parlamentares.yaml` — 594 parlamentares (Câmara e Senado). A curadoria manda; o gerado preenche o resto. Resultado: 732 nós e 976 relações.
- `data/ocupantes-oficiais.yaml` — ocupantes conferidos em páginas oficiais (Planalto, STF, TCU, TSE, STM), com data da conferência.
- `etl/` — conectores: `siorg.py`, `parlamentares.py` (Câmara e Senado), `sabatinas.py` (MSF do Senado com placar), `wikidata.py` (ocupantes via item do órgão, marcados como não verificados), `noticias.py` (8 feeds RSS com entidades e pessoas linkadas), `dou.py` (Seção 2 do Diário Oficial por órgão, com pausa de 2,5 s entre consultas; o portal bloqueia agentes desconhecidos), `orcamento.py` (despesas por órgão do Portal da Transparência, exige `PORTAL_TRANSPARENCIA_KEY` em `.env`), `dou_assinaturas.py` (dirigente atual = quem assina os atos do órgão no DOU), `wikipedia.py` (tabelas de composição atual: STJ, TST, CNJ, BC, Anatel; infocaixa das estatais), `fotos.py` (fotos 96×96 em `site/img`), `portal_cce.py` (CCE-18 por órgão; rendimento baixo, não integrado).
- `scripts/build_graph.py` — valida os YAML, funde as camadas (curadoria > oficiais > APIs > Wikidata) e gera `build/graph.br.json` e `web/graph.br.js`.
- `scripts/build_site.py` — site estático em `site/`: uma página por nó com HTML pré-renderizado, canonical, JSON-LD, sitemap e robots.
- `scripts/update.sh` e `.github/workflows/daily.yml` — atualização diária.
- `web/index.html` — protótipo da roda: quatro setores, quatro anéis, busca por sigla, legenda, tema claro/escuro,
  nós como links navegáveis por teclado.

```sh
python3 -m venv .venv && .venv/bin/pip install pyyaml
scripts/update.sh --fast                       # roda todos os conectores, o build e o site (sem SIORG completo e Wikidata)
.venv/bin/python scripts/build_graph.py
.venv/bin/python -m http.server 8765 --directory web   # abre http://localhost:8765
```

## Próximas fases

Ver o plano completo: modelo, fontes (SIORG, Portal da Transparência, Câmara, Senado, DOU), arquitetura e roadmap.

1. **Fase 1** ✓ — SIORG, Câmara e Senado, páginas por entidade com sitemap e JSON-LD (gerador estático em vez de Next.js: mesmo resultado, sem dependências).
2. **Fase 2** ✓ — sabatinas, notícias com entidades no texto, power map com fotos, DOU (atos e assinaturas), linha do tempo de mudanças com histórico diário de ocupantes (`data/generated/tenures.json`), páginas de pessoa, ocupantes de 109 dos 152 cargos.
3. **Fase 3** — aba Transição 2027 ✓, orçamento por órgão ✓, arcos de subgrupo na roda ✓, seletor de graphs com "Peça um grafo" ✓; dados do segundo graph (SP) pendentes.

## Camadas de dados e confiança

| Camada | Origem | Como aparece |
|---|---|---|
| Curadoria | `data/nodes`, `data/edges`, `data/ocupantes-oficiais.yaml` | citação legal; ocupantes com "página oficial, conferido em …" |
| APIs oficiais | SIORG, Câmara, Senado, Portal da Transparência | chip "via SIORG", partido e UF, orçamento |
| DOU (assinaturas) | `etl/dou_assinaturas.py` | "assina atos como titular", com o ato e a data como evidência |
| Wikipédia | `etl/wikipedia.py` | tabelas de composição, marcadas como fonte secundária |
| Wikidata | `etl/wikidata.py` | marcado "wikidata · pode estar desatualizado"; no Executivo só entra com início a partir de 2023 |
| Notícias e DOU | RSS e busca pública do DOU | ligados a entidades e cargos por sigla, nome e similaridade |

Pendências conhecidas: cadastro no INLABS para o Diário Oficial completo em XML; universidades e institutos federais sem reitores;
43 cargos ainda sem ocupante (segundo escalão, procuradorias, algumas fundações).

## Licenças

Código: MIT (`LICENSE`). Dados em `data/`: CC BY 4.0 (`data/LICENSE`).
