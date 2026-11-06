"""Etapa 1 - Ingestão: raw/*.csv.gz -> schema raw do olist.duckdb.

Executar com:  uv run python -m pipeline.ingestao

1. Escopo e nomes
   Schema de destino: raw. Os nove arquivos viram tabelas com nomes em português
   (mapa em TABELAS). Motivo: é o vocabulário que será digitado de memória nos
   JOINs das próximas etapas.
2. Proibições
   Nenhuma conversão de tipo, linha descartada/deduplicada, coluna renomeada ou
   valor corrigido/preenchido/normalizado. Data continua texto, nulo continua nulo.
   Motivo: a fronteira entre "o dado que chegou" e "o dado que eu decidi" tem que
   existir em algum lugar, e é a passagem de raw para refined (etapa 2). Corrigir
   aqui apagaria essa fronteira.
3. Reexecução
   A tabela é recriada (CREATE OR REPLACE), nunca acrescentada: rodar dez vezes
   dá o mesmo resultado que rodar uma. É o que permite errar sem medo.
4. Leitura
   encoding utf-8 declarado, nunca adivinhado. .csv.gz lido direto, sem
   descompactar. Campo vazio vira nulo, não string vazia.
5. Tipagem
   Toda coluna entra como texto (dtype=str), sem inferência. Motivo: a inferência
   leria CEP com zero à esquerda como número e o zero sumiria sem aviso. A
   conversão é decisão registrada da etapa 2.
6. Saída
   Uma linha por tabela (nome qualificado + contagem vinda do banco, milhar com
   ponto) e uma linha de total. É o único instrumento de conferência desta etapa.
   stdout reconfigurado para utf-8 porque o Prompt de Comando do Windows embaralha
   acentos por padrão.
7. Erro
   Antes de abrir o banco, verifica os nove arquivos. Faltando algum: lista os
   que faltam, informa a pasta e encerra com sys.exit(1). Não ingere parcialmente.
   Motivo: oito de nove tabelas em silêncio gera um dashboard errado que parece
   certo.
"""

import sys

import pandas as pd

from pipeline import db

SCHEMA = "raw"

TABELAS = {
    "olist_orders_dataset.csv.gz": "pedidos",
    "olist_order_items_dataset.csv.gz": "itens_pedido",
    "olist_order_payments_dataset.csv.gz": "pagamentos",
    "olist_order_reviews_dataset.csv.gz": "avaliacoes",
    "olist_customers_dataset.csv.gz": "clientes",
    "olist_sellers_dataset.csv.gz": "vendedores",
    "olist_products_dataset.csv.gz": "produtos",
    "product_category_name_translation.csv.gz": "traducao_categorias",
    "olist_geolocation_dataset.csv.gz": "geolocalizacao",
}


def formatar(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def ler(arquivo: str) -> pd.DataFrame:
    # keep_default_na=False + na_values=[""]: só o campo vazio vira nulo. Sem isso o
    # pandas também trataria textos como "NA" ou "null" como nulo, o que seria
    # corrigir valor (proibido nesta etapa).
    return pd.read_csv(
        db.PASTA_RAW / arquivo,
        dtype=str,
        encoding="utf-8",
        keep_default_na=False,
        na_values=[""],
    )


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")

    faltando = [a for a in TABELAS if not (db.PASTA_RAW / a).is_file()]
    if faltando:
        print(f"Arquivos faltando em {db.PASTA_RAW}:")
        for a in faltando:
            print(f"  - {a}")
        sys.exit(1)

    con = db.conectar()
    try:
        db.criar_schema(con, SCHEMA)
        total = 0
        for arquivo, tabela in TABELAS.items():
            n = db.gravar(con, ler(arquivo), SCHEMA, tabela)
            total += n
            print(f"{SCHEMA}.{tabela}: {formatar(n)} linhas")
        print(f"Total: {formatar(total)} registros")
    finally:
        con.close()


if __name__ == "__main__":
    main()
