# Atlas da República

Mapa navegável do governo federal brasileiro: cada órgão, cargo e colegiado da União e as relações legais
entre eles (quem elege, nomeia, sabatina, supervisiona, fiscaliza). Réplica, adaptada ao Brasil, da lógica do
[CivLab US Gov Graph](https://graph.civlab.org/us).

## Estado: Fase 2 em andamento

- `data/nodes/` e `data/edges/` — curadoria em YAML: 320 nós e as regras que geram as relações, cada uma com citação legal.
- `data/generated/siorg.yaml` — 330 órgãos e entidades e 214 colegiados nacionais importados do SIORG (`etl/siorg.py`); `parlamentares.yaml` — 594 parlamentares (Câmara e Senado). A curadoria manda; o gerado preenche o resto. Resultado: 732 nós e 976 relações.
- `data/ocupantes-oficiais.yaml` — ocupantes conferidos em páginas oficiais (Planalto, STF, TCU, TSE, STM), com data da conferência.
- `etl/` — conectores: `siorg.py`, `parlamentares.py` (Câmara e Senado), `sabatinas.py` (MSF do Senado com placar), `wikidata.py` (ocupantes via item do órgão, marcados como não verificados), `noticias.py` (8 feeds RSS com entidades e pessoas linkadas), `dou.py` (Seção 2 do Diário Oficial por órgão).
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
2. **Fase 2** — sabatinas ✓, notícias e power map ✓, DOU Seção 2 (parcial: busca pública por órgão; o INLABS dá cobertura completa), ocupantes do Executivo (Planalto ✓; agências e autarquias ainda dependem do DOU ou de curadoria).
3. **Fase 3** — transição de governo 2027, orçamento por órgão, segundo graph (SP).

## Licenças

Código: MIT (`LICENSE`). Dados em `data/`: CC BY 4.0 (`data/LICENSE`).
