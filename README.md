# Atlas da República

Mapa navegável do governo federal brasileiro: cada órgão, cargo e colegiado da União e as relações legais
entre eles (quem elege, nomeia, sabatina, supervisiona, fiscaliza). Réplica, adaptada ao Brasil, da lógica do
[CivLab US Gov Graph](https://graph.civlab.org/us).

## Estado: Fase 1 em andamento (SIORG conectado)

- `data/nodes/` e `data/edges/` — curadoria em YAML: 320 nós e as regras que geram as relações, cada uma com citação legal.
- `data/generated/siorg.yaml` — 330 órgãos e entidades e 214 colegiados nacionais importados do SIORG (`etl/siorg.py`); `parlamentares.yaml` — 594 parlamentares (Câmara e Senado). A curadoria manda; o gerado preenche o resto. Resultado: 732 nós e 976 relações.
- `scripts/build_graph.py` — valida os YAML e gera `build/graph.br.json` e `web/graph.br.js`.
- `web/index.html` — protótipo da roda: quatro setores, quatro anéis, busca por sigla, legenda, tema claro/escuro,
  nós como links navegáveis por teclado.

```sh
python3 -m venv .venv && .venv/bin/pip install pyyaml
.venv/bin/python etl/siorg.py --no-full        # baixa órgãos/entidades do SIORG (~1,3 MB); sem --no-full baixa também a estrutura completa (150 MB)
.venv/bin/python scripts/build_graph.py
.venv/bin/python -m http.server 8765 --directory web   # abre http://localhost:8765
```

## Próximas fases

Ver o plano completo: modelo, fontes (SIORG, Portal da Transparência, Câmara, Senado, DOU), arquitetura e roadmap.

1. **Fase 1** — ETL do Executivo (SIORG ✓, Portal da Transparência), parlamentares (Câmara e Senado), Next.js com páginas por entidade e sitemap.
2. **Fase 2** — DOU Seção 2 → mudanças (vagas, interinos), notícias com entidades linkadas, power map.
3. **Fase 3** — transição de governo 2027, orçamento por órgão, segundo graph (SP).

## Licenças

Código: MIT (`LICENSE`). Dados em `data/`: CC BY 4.0 (`data/LICENSE`).
