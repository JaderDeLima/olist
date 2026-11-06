# Pipeline Olist

Pipeline de dados e painel analítico sobre o dataset público de e-commerce brasileiro da **Olist**. O projeto lê os CSVs brutos, carrega num banco DuckDB, trata os dados, calcula indicadores de negócio em SQL e os exibe num painel (Streamlit) e num relatório HTML.

## Sobre os dados

O dataset reúne cerca de 100 mil pedidos de vendas online feitos entre 2016 e 2018 em marketplaces brasileiros, atendidos por vendedores parceiros da Olist. Cada pedido traz o cliente, os itens, os pagamentos, a entrega e a avaliação do cliente.

Os nove arquivos ficam em `raw/` (formato `.csv.gz`):

| Arquivo | Tabela | Conteúdo |
|---|---|---|
| `olist_orders_dataset` | `pedidos` | Pedido: status, datas de compra, envio, entrega e entrega prevista |
| `olist_order_items_dataset` | `itens_pedido` | Itens de cada pedido: produto, vendedor, preço e frete |
| `olist_order_payments_dataset` | `pagamentos` | Pagamentos: tipo, parcelas e valor |
| `olist_order_reviews_dataset` | `avaliacoes` | Nota (1 a 5) e comentário do cliente |
| `olist_customers_dataset` | `clientes` | Cliente: cidade, UF e CEP (`cliente_unico_id` identifica a pessoa) |
| `olist_sellers_dataset` | `vendedores` | Vendedor: cidade e UF |
| `olist_products_dataset` | `produtos` | Produto e categoria |
| `product_category_name_translation` | `traducao_categorias` | Categoria em português e inglês |
| `olist_geolocation_dataset` | `geolocalizacao` | Coordenadas por prefixo de CEP |

## Arquitetura medalhão

O projeto segue a **arquitetura medalhão** (*medallion architecture*): os dados passam por camadas de qualidade crescente, cada uma em um schema do DuckDB.

| Camada medalhão | Schema | O que contém |
|---|---|---|
| Bronze | `raw` | Cópia fiel dos arquivos, tudo como texto, sem corrigir nada |
| Silver | `refined` | Nomes em português, tipos corretos, duplicatas exatas removidas |
| Gold | `marts` | Uma tabela por pergunta de negócio, pronta para consumo |

```
raw/*.csv.gz ──► schema raw ──► schema refined ──► schema marts ──► painel / relatório
   (ingestão)     (bronze)         (silver)           (gold)         (app.py, relatorio.py)
```

1. **raw (bronze)**: cópia fiel dos arquivos. Tudo entra como texto, sem corrigir nada.
2. **refined (silver)**: nomes em português, tipos corretos (datas, `DECIMAL` para dinheiro), remoção de linhas totalmente duplicadas. Nulos e anomalias do dado são mantidos.
3. **marts (gold)**: uma tabela por pergunta de negócio, cada uma definida por um arquivo SQL em `sql/marts/`.
4. **Consumo**: o painel e o relatório apenas leem os marts. Nenhum cálculo é feito na camada de apresentação.

O banco `olist.duckdb` **não está no repositório** (passa de 100 MB, o limite do GitHub). Ele é criado na raiz do projeto ao rodar o pipeline, como mostra a seção "Como executar".

## Indicadores calculados

Salvo indicação em contrário, só entram **pedidos válidos**, ou seja, com status diferente de `canceled` e `unavailable`. Indicadores de entrega usam apenas pedidos `delivered` com data de entrega preenchida.

| # | Mart | O que responde | Como é calculado |
|---|---|---|---|
| 01 | `vendas_mensais` | Quanto vendemos por mês? | Pedidos distintos e receita (soma de `preco` dos itens) agrupados pelo mês da compra. A receita não inclui frete. |
| 02 | `top_categorias` | Quais categorias mais vendem? | Por categoria (nome em inglês): pedidos distintos, itens e receita, em ordem decrescente de receita. Produto sem categoria vira `sem_categoria`. A coluna de pedidos não soma entre categorias, pois um pedido pode ter várias. |
| 03 | `entrega_no_prazo` | Quanto chegou no prazo? | Entre os pedidos entregues, conta os que chegaram até a data prevista (`data_entrega <= data_entrega_prevista`) e os atrasados. `% no prazo = no prazo / entregues × 100`. |
| 04 | `nota_por_categoria` | Que nota cada categoria recebe? | Média das avaliações de cada pedido, depois média por categoria. Só categorias com pelo menos 100 pedidos avaliados. Ranqueia da pior para a melhor. |
| 05 | `recompra` | Quantos clientes voltaram a comprar? | Conta pedidos válidos por pessoa (`cliente_unico_id`) e mostra quantos clientes têm 1, 2, 3... pedidos, com o percentual de cada faixa. |
| 06 | `ticket_medio_por_estado` | Qual o ticket médio por estado? | Soma o preço dos itens por pedido, depois tira a média dos pedidos de cada UF do cliente. |
| 07 | `mix_de_pagamento` | Como o dinheiro entra? | Por tipo de pagamento (cartão, boleto, voucher, débito): linhas de pagamento, pedidos distintos, valor e `% do valor total`. O valor pago é maior que a receita do mart 01 porque inclui frete e juros de parcelamento. A coluna de pedidos não soma entre tipos. |
| 08 | `a_nota_de_quem_recebeu_atrasado` | O atraso derruba a nota? | Compara pedidos no prazo e atrasados: nota média e `% de notas baixas` (nota ≤ 2). |
| 09 | `concentracao_de_vendedores` | Quantos vendedores fazem 80% da receita? | Ordena os vendedores da maior para a menor receita e calcula o `% acumulado` da receita total (curva de Pareto). |
| 10 | `tempo_de_entrega_por_estado` | Quanto tempo leva a entrega? | Dias de calendário entre a compra e a entrega ao cliente, com média e mediana por UF. |
| 11 | `kpis` | Cartões de resumo do painel | Ver abaixo. |
| 12 | `clientes_por_uf` | Quantos clientes tem cada estado? | Pessoas distintas (`cliente_unico_id`) com pedido válido em cada UF. |

### KPIs do painel (mart 11)

- **Ticket médio**: média da receita por pedido (soma dos preços dos itens). Também calcula a mediana.
- **Peso do frete**: `frete / (receita + frete) × 100`.
- **Cancelados**: `pedidos cancelados / todos os pedidos × 100`.
- **Tempo de entrega**: média e mediana de dias entre compra e entrega, nos pedidos entregues.
- **Nota média**: média de todas as avaliações.

### Decisões de cálculo

- **Receita** é sempre a soma de `preco` dos itens, sem frete. O frete é tratado à parte.
- **Cliente** é a pessoa (`cliente_unico_id`), não o `cliente_id`, que muda a cada pedido.
- **Um pedido, uma nota**: quando um pedido tem mais de uma avaliação, usa-se a média delas.
- **Chegar no dia previsto conta como no prazo.**
- Cada arquivo SQL documenta o seu grão (o que representa uma linha) no cabeçalho.

## Estrutura do projeto

```
raw/                  CSVs originais (.csv.gz)
pipeline/
  db.py               conexão com o DuckDB e gravação de tabelas
  ingestao.py         etapa 1: raw/*.csv.gz -> schema raw
  transformacao.py    etapa 2: raw -> refined (geolocalização e chamada do módulo abaixo)
  refinar_tabelas.py  etapa 2: raw -> refined das outras oito tabelas
  marts.py            etapa 3: sql/marts/*.sql -> schema marts
sql/marts/            um arquivo SQL por indicador
painel.py             leitura, formatação e gráficos (sem Streamlit)
app.py                painel interativo em Streamlit
relatorio.py          gera relatorio.html
ui.py                 explorador do banco no navegador (DuckDB UI)
test/                 testes automatizados (pytest)
olist.duckdb          banco gerado pelo pipeline (não versionado, ver .gitignore)
```

## Como executar

Requisitos: Python 3.14 ou superior e [uv](https://docs.astral.sh/uv/).

```bash
uv sync                               # instala as dependências

uv run python -m pipeline.ingestao    # 1. carrega os CSVs no schema raw
uv run python -m pipeline.transformacao  # 2. gera o schema refined
uv run python -m pipeline.marts       # 3. calcula os indicadores

uv run streamlit run app.py           # painel interativo
uv run python relatorio.py            # relatório estático (relatorio.html)
uv run python ui.py                   # explorar o banco (http://localhost:4213)
```

As etapas são idempotentes: rodar várias vezes dá o mesmo resultado. O arquivo `olist.duckdb` aceita um único processo de escrita, então feche o painel ou o `ui.py` antes de rodar o pipeline de novo.

## Testes

```bash
uv run pytest                 # roda os testes
uv run pytest --cov           # com cobertura (mínimo de 60%)
uv run ruff check .           # lint
```

## Tecnologias

Python, DuckDB, pandas, Plotly, Streamlit, pytest e ruff.

## Fonte dos dados

[Brazilian E-Commerce Public Dataset by Olist](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce), disponibilizado no Kaggle sob licença CC BY-NC-SA 4.0.
