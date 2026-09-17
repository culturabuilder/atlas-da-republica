# Dados do Atlas da República

Fonte da verdade da Fase 0. Tudo aqui é curado à mão e versionado. A partir da Fase 1, o ETL
(SIORG, Portal da Transparência, Câmara, Senado, DOU) preenche `people`, `employee_count` e os
órgãos de nível 3 e 4 que não estão listados.

## Convenções

- `id`: prefixo `br-` + slug do nome. É estável para sempre; renomear um órgão muda `name`, não `id`.
- `type`: `constituency | elected | department | dept_head | commission | advisory` (mesmos do CivLab).
- `subtype` (departments): `orgao_presidencia | ministerio | orgao_singular | autarquia | agencia_reguladora |
  fundacao | empresa_publica | sociedade_economia_mista | forca_armada | tribunal | conselho | casa_legislativa | orgao_legislativo | ministerio_publico | defensoria | advocacia`.
- `sector`: `legislativo | executivo | judiciario | essenciais`.
- `ring`: 1 a 4 (ver `layout.yaml`).
- `parent`: órgão ao qual está integrado ou vinculado. O build deriva a aresta:
  `integra` quando o filho é administração direta, `supervisiona` quando é indireta.
- `cite`: dispositivo legal que fundamenta o nó ou a aresta. `cite_url` aponta para o Planalto.
- `verified`: `false` até um pesquisador conferir a citação na fonte. Padrão da Fase 0 é `false`.

## Cargos (`dept_head`)

- `head_of`: órgão chefiado. O build deriva a aresta `chefia`.
- `nomeado_por`: id de quem nomeia. O build deriva `nomeia`.
- `sabatina`: `true` quando depende de aprovação do Senado (CF art. 52 III e IV). O build deriva `sabatina`.
- `seats`: número de vagas quando o cargo é colegiado (11 ministros do STF, 9 do TCU).
- `people`: lista de ocupantes `{id, name, started_at, entry_mode, acting, image_url, party}`. Vazia na Fase 0.

## Arestas explícitas (`edges/*.yaml`)

Só as que não se derivam de `parent`, `head_of`, `nomeado_por` e `sabatina`:
`elege`, `fiscaliza`, `aconselha`, `membro_nato`, `indica` e casos especiais de `nomeia`.
