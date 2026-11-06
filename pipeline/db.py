"""Módulo de conexão compartilhado pelas etapas do pipeline.

Expõe exatamente: PASTA_RAW, conectar(), criar_schema(con, nome), gravar(con, df, schema, tabela).

D1. Caminhos
    PASTA_RAW e olist.duckdb são resolvidos a partir deste arquivo (a pasta acima
    de pipeline/), nunca do diretório corrente. Motivo: rodar o script de outra
    pasta não pode criar um olist.duckdb vazio no lugar errado, o que pareceria
    uma ingestão quebrada.
D2. Três funções e uma constante, nada mais
    Este módulo não lê CSV, não conhece nome de tabela, não imprime e não converte
    tipo. Motivo: as etapas 2, 3 e 4 importam este arquivo; regra de negócio
    escondida aqui valeria para todas sem aparecer em nenhuma spec.
D3. gravar
    Recria a tabela (CREATE OR REPLACE TABLE) com as colunas e tipos do DataFrame,
    sem alterar nada, e não deixa view ou tabela temporária para trás. Devolve
    SELECT count(*) da tabela recém-gravada. Motivo: a contagem exibida tem que ser
    a do que foi gravado, não a do que estava na memória.
D4. Conexão
    conectar() devolve a conexão aberta; quem chama fecha. Sem conexão global.
    Importar este módulo não abre banco nem cria arquivo.
"""

from pathlib import Path

import duckdb
import pandas as pd

_RAIZ = Path(__file__).resolve().parent.parent
PASTA_RAW = _RAIZ / "raw"
_ARQUIVO_DB = _RAIZ / "olist.duckdb"


def conectar() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(_ARQUIVO_DB))


def criar_schema(con: duckdb.DuckDBPyConnection, nome: str) -> None:
    con.execute(f'CREATE SCHEMA IF NOT EXISTS "{nome}"')


def gravar(
    con: duckdb.DuckDBPyConnection, df: pd.DataFrame, schema: str, tabela: str
) -> int:
    destino = f'"{schema}"."{tabela}"'
    # fetchall() esgota o resultado; sem isso a conexão fica "ocupada" na chamada seguinte.
    # A view só existe durante esta chamada; o finally garante a remoção.
    con.register("_df_gravar", df)
    try:
        con.execute(f"CREATE OR REPLACE TABLE {destino} AS SELECT * FROM _df_gravar").fetchall()
    finally:
        con.unregister("_df_gravar")
    return con.execute(f"SELECT count(*) FROM {destino}").fetchall()[0][0]
