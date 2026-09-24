# Atlas da República

Site: https://atlasdarepublica.org · Código MIT · Dados CC BY 4.0

Mapa navegável do governo federal brasileiro: cada órgão, cargo e colegiado da União e as relações legais
entre eles (quem elege, nomeia, sabatina, supervisiona, fiscaliza). Réplica, adaptada ao Brasil, da lógica do
[CivLab US Gov Graph](https://graph.civlab.org/us).

## Estado: Fase 2 em andamento

- `data/nodes/` e `data/edges/` — curadoria em YAML: 320 nós e as regras que geram as relações, cada uma com citação legal.
- `data/generated/siorg.yaml` — órgãos, entidades e colegiados nacionais importados do SIORG (`etl/siorg.py`); `parlamentares.yaml` — 594 parlamentares (Câmara e Senado). A curadoria manda; o gerado preenche o resto.

<!-- ATLAS:NUMEROS -->
<!-- Gerado por scripts/build_graph.py a cada build. Não edite à mão. -->
| O que o grafo tem hoje | |
|---|---|
| Nós e relações | **1365** nós · **2002** relações, cada uma com citação legal |
| Pessoas | **1147** ocupando **1159** de **1306** cadeiras |
| Cargos de chefia | **408** de **545** com ocupante (137 vazios) |
| Órgãos sem cargo de chefia mapeado | **27** (tribunais regionais, estatais, universidades) |
| Colegiados sem composição registrada | **220** de **270** |
| Nomeações sem data de posse | **347** de **543** |

Atualizado em 2026-09-24.
<!-- /ATLAS:NUMEROS -->
- `data/ocupantes-oficiais.yaml` — ocupantes conferidos em páginas oficiais (Planalto, STF, TCU, TSE, STM), com data da conferência.
- `etl/` — conectores: `siorg.py`, `parlamentares.py` (Câmara e Senado), `comissoes.py` (Mesa do Senado, 17 comissões permanentes do Senado, 30 da Câmara e 4 mistas, com presidência, titulares e suplentes), `sabatinas.py` (MSF do Senado com placar), `wikidata.py` (ocupantes via item do órgão, marcados como não verificados), `noticias.py` (8 feeds RSS com entidades e pessoas linkadas), `dou.py` (Seção 2 do Diário Oficial: percorre todas as páginas da busca pública por verbo, com o cursor da própria busca e pausa de 2,5 s; aceita `--from/--to` para recuperar períodos), `orcamento.py` (despesas por órgão do Portal da Transparência, exige `PORTAL_TRANSPARENCIA_KEY` em `.env`), `dou_assinaturas.py` (dirigente atual = quem assina os atos do órgão no DOU), `wikipedia.py` (tabelas de composição atual: STJ, TST, CNJ, BC, Anatel; infocaixa das estatais), `fotos.py` (fotos 96×96 em `site/img`), `portal_cce.py` (CCE-18 por órgão; rendimento baixo, não integrado), `nascimentos.py` (data de nascimento no Wikidata para cargos vitalícios e TCU; o build calcula a aposentadoria compulsória aos 75), `omissao.py` (placar da omissão: vetos sem votação, MPs perto de caducar, pedidos de CPI com assinaturas sem despacho, casos curados em `data/omissao-curado.yaml`), `arrecadacao.py` (arrecadômetro: receitas do Portal da Transparência por dia, IPCA e população do IBGE, juros do Banco Central), `atividade.py` (presença em votações nominais e cota parlamentar por deputado e senador, arquivos em lote da Câmara e API do Senado), `temas.py` (temas curados em `data/temas.yaml`: atenção nas notícias e na Wikipédia cruzada com a situação dos processos nas duas Casas), `emendas.py` (emendas parlamentares do Portal da Transparência: por autor, ano e município, salto em ano eleitoral, por habitante), `renuncias.py` (gastos tributários da planilha oficial da Receita, por função e por benefício, comparados ao orçamento dos ministérios), `teto.py` (folha do Executivo federal: servidores com abate-teto e verbas indenizatórias por órgão, só agregados), `proposicoes.py` (proposições apresentadas, projetos, requerimentos, relatorias e normas geradas no ano legislativo, por arquivos em lote da Câmara e API do Senado), `gabinetes.py` e `gabinetes_senado.py` (equipe por gabinete, folha (estimada na Câmara pela tabela de níveis; real no Senado pela folha mensal), cotas, auxílio-moradia e imóvel funcional no Senado, custo do mandato e medianas por Casa), `viagens.py` (viagens a serviço do ano por ocupante e por órgão), `cartao.py` (cartão corporativo por mês, por órgão e por unidade gestora; o portador do extrato é servidor de execução, então não há bloco por ocupante), `remuneracao.py` (remuneração mensal dos ocupantes de cargos do Executivo na folha do SIAPE), `doadores.py` (receitas de campanha de 2022 por origem e maiores fontes; pessoas físicas só a partir de R$ 50 mil), `patrimonio.py` (bens declarados ao TSE em 2018 e 2022, variação nominal e real), `votos.py` e `candidaturas.py` (TSE: votação por município dos eleitos em 2022 e candidaturas 2022/2024 dos ocupantes; os zips do TSE precisam ser baixados à mão em `build/cache-tse/` porque o CDN bloqueia acesso automatizado; a saída gerada fica versionada).
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
2. **Fase 2** ✓ — sabatinas, notícias com entidades no texto, power map com fotos, DOU (atos e assinaturas), linha do tempo de mudanças com histórico diário de ocupantes (`data/generated/tenures.json`), páginas de pessoa e ocupantes (números atuais no quadro acima).
3. **Fase 3** — aba Transição 2027 ✓, orçamento por órgão ✓, arcos de subgrupo na roda ✓, seletor de graphs com "Peça um grafo" ✓; dados do segundo graph (SP) pendentes.

## Camadas de dados e confiança

| Camada | Origem | Como aparece |
|---|---|---|
| Curadoria | `data/nodes`, `data/edges`, `data/ocupantes-oficiais.yaml` | citação legal; ocupantes com "página oficial, conferido em …" |
| APIs oficiais | SIORG, Câmara, Senado, Portal da Transparência | chip "via SIORG", partido e UF, orçamento |
| DOU (assinaturas) | `etl/dou_assinaturas.py` | "assina atos como titular", com o ato e a data como evidência |
| Wikipédia | `etl/wikipedia.py` | tabelas de composição, marcadas como fonte secundária |
| Wikidata | `etl/wikidata.py` | histórico de ocupantes de cada cargo (bloco "Quem ocupou este cargo"); como camada de ocupante atual, entra só quando nenhuma fonte anterior preencheu o cargo |
| Notícias e DOU | RSS e busca pública do DOU | ligados a entidades e cargos por sigla, nome e similaridade |

Pendências conhecidas, medidas em 22/09/2026 e detalhadas por `scripts/eval_lacunas.py`: órgãos que existem no grafo sem cargo de chefia
(tribunais regionais, empresas públicas, sociedades de economia mista, universidades e institutos federais); colegiados do Executivo sem
composição registrada; ocupantes de nomeação sem data de posse; cadastro no INLABS para o Diário Oficial completo em XML.

## Licenças

Código: MIT (`LICENSE`). Dados em `data/`: CC BY 4.0 (`data/LICENSE`).

## Área educativa

`/como-funciona/` é uma visita guiada por rolagem: a mesma roda da home acende setores, anéis, nós e ligações a cada passo do texto. Conteúdo em `data/como-funciona.yaml` (10 capítulos, 50 passos, cada um com citação legal e o estado da roda), glossário em `data/glossario.yaml`, dados vivos calculados no build por `scripts/build_como_funciona.py` (chamado por `build_site.py`). A roda e os tokens de tema ficam em `web/atlas.js` e `web/atlas.css`, compartilhados pela home.

## Desempenho

A home e a área educativa saem do build com a roda já em SVG (`scripts/render_wheel.js` executa `atlas.js` no Node, sem DOM) e com os primeiros cartões no HTML; o CSS da roda é embutido e as fontes carregam sem bloquear a renderização. Páginas de nó e de pessoa desenham a roda no cliente para manter o site leve.

## Outras páginas e saídas do build

- `/comparar/` (`scripts/build_comparar.py`): rankings por medida, Casa, UF e partido, e comparador lado a lado de dois parlamentares, sempre contra a mediana da Casa.
- `/dados/` (`scripts/build_dados.py`): CSV e JSON de nós, ligações, pessoas, ocupantes, mudanças, omissão, temas, arrecadação, emendas, gabinetes, patrimônio e viagens, com licença CC BY 4.0.
- `/metodologia/` (`web/metodologia.html`): fonte, periodicidade e o que é estimativa em cada bloco, e o que fica de fora.
- `/feeds/*.xml` (`scripts/build_feeds.py`): RSS de mudanças de cargo, prazos vencendo, temas e notícias.
- `/og/<id>.png` (`scripts/build_og.py`): imagem de compartilhamento por pessoa e órgão, referenciada nas metas Open Graph de cada página.
