"""Etapa 2 - Transformação: schema raw -> schema refined (todas as nove tabelas).

Este módulo trata raw.geolocalizacao -> refined.geolocalizacao e, em seguida,
chama pipeline/refinar_tabelas.py, que trata as outras oito tabelas.
O texto abaixo descreve as regras da geolocalizacao.

Executar com:  uv run python -m pipeline.transformacao

1. Escopo
   Lê de raw.geolocalizacao, escreve em refined.geolocalizacao. Nunca escreve em
   raw: nenhuma linha de raw é alterada ou apagada. As outras oito tabelas de raw
   ficam de fora. Motivo: decisão do dono do projeto, esta etapa trata só a
   geolocalização.
2. Nomes
   Mantidos os nomes originais de raw, sem renomear nenhuma coluna:
   geolocation_zip_code_prefix, geolocation_lat, geolocation_lng,
   geolocation_city, geolocation_state. Motivo: decisão do dono do projeto.
3. Tipos
   geolocation_lat e geolocation_lng -> DOUBLE. Motivo: decisão do dono do
   projeto; são coordenadas, não dinheiro.
   geolocation_zip_code_prefix, geolocation_city, geolocation_state -> VARCHAR,
   sem conversão. Motivo do CEP: é identificador, nunca é somado, e como número
   perderia o zero à esquerda (ex.: "01037").
   Não há datas, dinheiro nem contagens nesta tabela.
   A conversão é feita em SQL pelo DuckDB (CAST), disparada pelo Python. Motivo: o
   dado já está no banco.
4. Conversão que falha
   Para tudo. Só CAST, que estoura; nunca TRY_CAST. Informa tabela, coluna e um
   exemplo do valor e encerra com sys.exit(1). Motivo: decisão do dono do projeto;
   um nulo fabricado pela conversão fica indistinguível de um nulo verdadeiro.
5. Duplicatas
   Remove de refined somente linha 100% idêntica (as cinco colunas iguais, comparadas
   como texto de raw, antes da conversão); mantém uma cópia. Mesmo CEP com
   coordenadas ou cidade diferentes NÃO é duplicata e permanece. Motivo: decisão
   do dono do projeto; não existe chave natural nesta tabela, o CEP se repete por
   desenho do dataset.
6. Nulos
   Nulo continua nulo: nenhum nulo é preenchido e nenhuma linha é descartada por ter
   nulo. Motivo: decisão do dono do projeto ("usar null").
7. Saída
   Informa que raw.geolocalizacao está sendo enviada para refined.geolocalizacao;
   depois: linhas lidas de raw, linhas gravadas em refined, e se alguma linha foi
   removida (quantas, por duplicata) ou que nenhuma foi. Abaixo, as colunas com nulo
   e a contagem. Contagens vêm do banco, milhar com ponto. stdout reconfigurado
   para utf-8 porque o Prompt de Comando do Windows embaralha acentos.
8. Reexecução
   CREATE OR REPLACE TABLE, nunca acrescenta: rodar dez vezes = rodar uma.
9. Erro
   Se raw.geolocalizacao não existir: informa, manda rodar
   "uv run python -m pipeline.ingestao" e encerra com sys.exit(1).

Critérios de aceite
   a. refined.geolocalizacao tem 5 colunas, com os mesmos nomes e ordem de raw.
   b. Tipos em information_schema: lat e lng = DOUBLE; as demais = VARCHAR.
   c. count(refined) = count(DISTINCT *) de raw.geolocalizacao, e a diferença
      count(raw) - count(refined) é exatamente o número de duplicatas informado.
   d. Nenhuma linha de refined tem CEP com menos de 5 caracteres por perda de zero
      (CEP continua VARCHAR: "01037" não vira "1037").
   e. count(raw.geolocalizacao) é o mesmo antes e depois da execução.
   f. Segunda execução imprime as mesmas contagens da primeira.
"""

import re
import sys

import duckdb

from pipeline import db, refinar_tabelas

ORIGEM = "raw"
DESTINO = "refined"
TABELA = "geolocalizacao"

# Coluna (mesmo nome em raw e refined) e tipo: V = VARCHAR, DBL = DOUBLE.
COLUNAS = [
    ("geolocation_zip_code_prefix", "V"),
    ("geolocation_lat", "DBL"),
    ("geolocation_lng", "DBL"),
    ("geolocation_city", "V"),
    ("geolocation_state", "V"),
]


def formatar(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def expressao(coluna: str, tipo: str) -> str:
    c = f'"{coluna}"'
    return f"CAST({c} AS DOUBLE)" if tipo == "DBL" else c


def verificar_entrada(con: duckdb.DuckDBPyConnection) -> None:
    existe = con.execute(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema = ? AND table_name = ?",
        [ORIGEM, TABELA],
    ).fetchall()[0][0]
    if not existe:
        print(f"Tabela faltando: {ORIGEM}.{TABELA}")
        print("Rode primeiro: uv run python -m pipeline.ingestao")
        sys.exit(1)


def diagnosticar_conversao(con: duckdb.DuckDBPyConnection, erro: Exception) -> None:
    # O erro do CREATE não diz qual coluna falhou; reavalia coluna a coluna
    # (count() força a avaliação) até uma estourar.
    for coluna, tipo in COLUNAS:
        if tipo == "V":
            continue
        try:
            con.execute(
                f'SELECT count({expressao(coluna, tipo)}) FROM {ORIGEM}."{TABELA}"'
            ).fetchall()
        except duckdb.Error as e:
            achado = re.search(r'"([^"]*)"', str(e))
            exemplo = achado.group(1) if achado else str(e)
            print(
                f"Falha de conversão em {ORIGEM}.{TABELA}, coluna {coluna} "
                f"({tipo}): valor {exemplo!r}"
            )
            sys.exit(1)
    print(f"Falha de conversão em {ORIGEM}.{TABELA}: {erro}")
    sys.exit(1)


def transformar(con: duckdb.DuckDBPyConnection) -> tuple[int, int]:
    entram = con.execute(f'SELECT count(*) FROM {ORIGEM}."{TABELA}"').fetchall()[0][0]

    print(f"Enviando {ORIGEM}.{TABELA} -> {DESTINO}.{TABELA} ...")
    selecao = ", ".join(f'{expressao(c, t)} AS "{c}"' for c, t in COLUNAS)
    try:
        # DISTINCT na subconsulta: dedup sobre o texto de raw, antes do CAST.
        con.execute(
            f'CREATE OR REPLACE TABLE {DESTINO}."{TABELA}" AS '
            f'SELECT {selecao} FROM (SELECT DISTINCT * FROM {ORIGEM}."{TABELA}")'
        ).fetchall()
    except duckdb.Error as e:
        diagnosticar_conversao(con, e)

    saem = con.execute(f'SELECT count(*) FROM {DESTINO}."{TABELA}"').fetchall()[0][0]
    return entram, saem


def descrever_nulos(con: duckdb.DuckDBPyConnection) -> str:
    nomes = [c for c, _ in COLUNAS]
    contagens = ", ".join(f'count(*) - count("{n}")' for n in nomes)
    valores = con.execute(f'SELECT {contagens} FROM {DESTINO}."{TABELA}"').fetchall()[0]
    com_nulo = [f"{n} {formatar(v)}" for n, v in zip(nomes, valores) if v > 0]
    return "  nulos mantidos: " + ", ".join(com_nulo) if com_nulo else ""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")

    con = db.conectar()
    try:
        verificar_entrada(con)
        db.criar_schema(con, DESTINO)
        entram, saem = transformar(con)
        print(f"{ORIGEM}.{TABELA}: {formatar(entram)} linhas lidas")
        print(f"{DESTINO}.{TABELA}: {formatar(saem)} linhas gravadas")
        removidas = entram - saem
        if removidas:
            print(f"  {formatar(removidas)} linhas removidas por duplicata (linha idêntica)")
        else:
            print("  nenhuma linha removida")
        nulos = descrever_nulos(con)
        if nulos:
            print(nulos)
        refinar_tabelas.executar(con)
    finally:
        con.close()


if __name__ == "__main__":
    main()
