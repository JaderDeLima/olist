"""Etapa 2 - Transformação (oito tabelas): schema raw -> schema refined.

Chamado por pipeline/transformacao.py, que também trata a geolocalizacao.
Para rodar só esta parte:  uv run python -m pipeline.refinar_tabelas

1. Escopo
   Lê de raw, escreve em refined. Nunca escreve em raw. Entram oito tabelas:
   pedidos, itens_pedido, pagamentos, clientes, vendedores, produtos,
   traducao_categorias, avaliacoes. geolocalizacao fica de fora.
   Motivo: nenhum mart do curso usa; não se limpa o que ninguém vai ler.
2. Nomes
   Colunas renomeadas para português snake_case pelo mapa COLUNAS abaixo, completo
   e literal: nenhuma coluna fora do mapa, nenhuma descartada.
   Motivo: é o vocabulário que será digitado de memória nos JOINs da aula 3.
3. Tipos
   Datas com hora -> TIMESTAMP, formato declarado '%Y-%m-%d %H:%M:%S'.
   data_entrega_prevista e data_criacao -> DATE. Motivo: em data_entrega_prevista
   a hora é 00:00:00 nas 99.441 linhas; em data_criacao é 00:00:00 em 99.139 das
   99.224 avaliações e 01:00:00 nas outras 85 (horário de verão, não horário de
   verdade). Guardar a hora seria inventar precisão.
   Dinheiro (preco, frete, valor) -> DECIMAL(10,2). Motivo: DOUBLE não representa
   centavos com exatidão, e soma de dinheiro tem que fechar.
   Contagens e medidas -> INTEGER.
   Todo o resto continua VARCHAR, inclusive cep_prefixo. Motivo: 23.995 clientes
   têm CEP começando com zero; CEP é identificador, nunca é somado, e como número
   perderia o zero.
   A conversão é feita em SQL pelo DuckDB (strptime, CAST), disparada pelo Python.
   Motivo: o dado já está no banco; não há por que trazê-lo para a memória só
   para converter tipo.
4. Conversão que falha
   Para tudo. Só strptime e CAST, que estouram; nunca try_strptime, TRY_CAST ou
   errors="coerce". Informa tabela, coluna e um exemplo do valor e encerra com
   sys.exit(1). Motivo: um nulo fabricado pela conversão fica indistinguível de
   um nulo verdadeiro do dado, para sempre.
5. Duplicatas
   Chave por tabela em CHAVES. Linha inteira repetida: mantém uma e conta quantas
   saíram. Chave repetida com conteúdo diferente: para, mostra a chave e as linhas
   conflitantes, sys.exit(1). Motivo: escolher em silêncio é decidir sem dizer que
   decidiu. Em avaliacoes, avaliacao_id sozinho não é chave: o mesmo id aparece em
   mais de um pedido.
6. Nulos
   Nenhuma linha é apagada por ter nulo; nenhum nulo é preenchido. Motivo: nas
   datas de pedidos o nulo é informação (cancelado não tem data de entrega); os
   610 produtos sem categoria continuam sem categoria, pois rótulo é decisão de
   mart; avaliação sem texto é a regra. Anomalias de negócio também ficam (8
   pedidos delivered sem data_entrega, 166 com data_envio antes de data_compra,
   pedidos com mais de uma avaliação). refined não corrige fato; quem decide o que
   fazer com ele é a pergunta que o mart responde.
7. Saída
   Uma linha por tabela (entram -> saem, duplicatas) e, abaixo, indentadas, as
   colunas com nulo e a contagem. Linha final com o total. Contagens vêm do banco,
   milhar com ponto. stdout reconfigurado para utf-8 porque o Prompt de Comando do
   Windows embaralha acentos por padrão.
8. Reexecução
   CREATE OR REPLACE TABLE, nunca acrescenta: rodar dez vezes = rodar uma.
9. Erro
   Antes de transformar, verifica as oito tabelas de entrada em raw. Faltando
   alguma: lista quais, manda rodar "uv run python -m pipeline.ingestao" e
   encerra com sys.exit(1). Motivo: transformar parte do dado em silêncio gera um
   mart errado que parece certo.
"""

import re
import sys

import duckdb

from pipeline import db

ORIGEM = "raw"
DESTINO = "refined"

FMT_TS = "%Y-%m-%d %H:%M:%S"

# Tipos: V = VARCHAR (sem conversão), TS = TIMESTAMP, D = DATE, DEC = DECIMAL(10,2),
# INT = INTEGER. Cada item: coluna em raw, coluna em refined, tipo.
COLUNAS = {
    "pedidos": [
        ("order_id", "pedido_id", "V"),
        ("customer_id", "cliente_id", "V"),
        ("order_status", "status", "V"),
        ("order_purchase_timestamp", "data_compra", "TS"),
        ("order_approved_at", "data_aprovacao", "TS"),
        ("order_delivered_carrier_date", "data_envio", "TS"),
        ("order_delivered_customer_date", "data_entrega", "TS"),
        ("order_estimated_delivery_date", "data_entrega_prevista", "D"),
    ],
    "itens_pedido": [
        ("order_id", "pedido_id", "V"),
        ("order_item_id", "item_seq", "INT"),
        ("product_id", "produto_id", "V"),
        ("seller_id", "vendedor_id", "V"),
        ("shipping_limit_date", "data_limite_envio", "TS"),
        ("price", "preco", "DEC"),
        ("freight_value", "frete", "DEC"),
    ],
    "pagamentos": [
        ("order_id", "pedido_id", "V"),
        ("payment_sequential", "pagamento_seq", "INT"),
        ("payment_type", "tipo", "V"),
        ("payment_installments", "parcelas", "INT"),
        ("payment_value", "valor", "DEC"),
    ],
    "clientes": [
        ("customer_id", "cliente_id", "V"),
        ("customer_unique_id", "cliente_unico_id", "V"),
        ("customer_zip_code_prefix", "cep_prefixo", "V"),
        ("customer_city", "cidade", "V"),
        ("customer_state", "uf", "V"),
    ],
    "vendedores": [
        ("seller_id", "vendedor_id", "V"),
        ("seller_zip_code_prefix", "cep_prefixo", "V"),
        ("seller_city", "cidade", "V"),
        ("seller_state", "uf", "V"),
    ],
    "produtos": [
        ("product_id", "produto_id", "V"),
        ("product_category_name", "categoria", "V"),
        ("product_name_lenght", "tamanho_nome", "INT"),
        ("product_description_lenght", "tamanho_descricao", "INT"),
        ("product_photos_qty", "qtd_fotos", "INT"),
        ("product_weight_g", "peso_g", "INT"),
        ("product_length_cm", "comprimento_cm", "INT"),
        ("product_height_cm", "altura_cm", "INT"),
        ("product_width_cm", "largura_cm", "INT"),
    ],
    "traducao_categorias": [
        ("product_category_name", "categoria", "V"),
        ("product_category_name_english", "categoria_en", "V"),
    ],
    "avaliacoes": [
        ("review_id", "avaliacao_id", "V"),
        ("order_id", "pedido_id", "V"),
        ("review_score", "nota", "INT"),
        ("review_comment_title", "titulo", "V"),
        ("review_comment_message", "comentario", "V"),
        ("review_creation_date", "data_criacao", "D"),
        ("review_answer_timestamp", "data_resposta", "TS"),
    ],
}

# Chaves em nomes de raw (a deduplicação roda antes da conversão).
CHAVES = {
    "pedidos": ["order_id"],
    "itens_pedido": ["order_id", "order_item_id"],
    "pagamentos": ["order_id", "payment_sequential"],
    "clientes": ["customer_id"],
    "vendedores": ["seller_id"],
    "produtos": ["product_id"],
    "traducao_categorias": ["product_category_name"],
    "avaliacoes": ["review_id", "order_id"],
}


def formatar(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def expressao(coluna: str, tipo: str) -> str:
    c = f'"{coluna}"'
    if tipo == "TS":
        return f"strptime({c}, '{FMT_TS}')"
    if tipo == "D":
        # A origem traz data e hora; o formato é o mesmo, a hora é descartada no CAST.
        return f"CAST(strptime({c}, '{FMT_TS}') AS DATE)"
    if tipo == "DEC":
        return f"CAST({c} AS DECIMAL(10,2))"
    if tipo == "INT":
        return f"CAST({c} AS INTEGER)"
    return c


def verificar_entrada(con: duckdb.DuckDBPyConnection) -> None:
    existentes = {
        r[0]
        for r in con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = ?",
            [ORIGEM],
        ).fetchall()
    }
    faltando = [t for t in COLUNAS if t not in existentes]
    if faltando:
        print(f"Tabelas faltando em {ORIGEM}:")
        for t in faltando:
            print(f"  - {ORIGEM}.{t}")
        print('Rode primeiro: uv run python -m pipeline.ingestao')
        sys.exit(1)


def verificar_conflitos(con: duckdb.DuckDBPyConnection, tabela: str) -> None:
    chave = CHAVES[tabela]
    lista = ", ".join(f'"{c}"' for c in chave)
    base = f'(SELECT DISTINCT * FROM {ORIGEM}."{tabela}")'
    conflitos = con.execute(
        f"SELECT {lista} FROM {base} GROUP BY {lista} HAVING count(*) > 1"
    ).fetchall()
    if not conflitos:
        return
    valores = conflitos[0]
    # IS NOT DISTINCT FROM: chave com nulo também casa.
    filtro = " AND ".join(f'"{c}" IS NOT DISTINCT FROM ?' for c in chave)
    linhas = con.execute(f"SELECT * FROM {base} WHERE {filtro}", list(valores)).fetchall()
    cols = [d[0] for d in con.description]
    print(
        f"Chave repetida com conteúdo diferente em {ORIGEM}.{tabela} "
        f"({formatar(len(conflitos))} chave(s) em conflito). Primeira:"
    )
    print("  " + ", ".join(f"{c}={v!r}" for c, v in zip(chave, valores)))
    for linha in linhas:
        print("  " + ", ".join(f"{c}={v!r}" for c, v in zip(cols, linha)))
    sys.exit(1)


def diagnosticar_conversao(
    con: duckdb.DuckDBPyConnection, tabela: str, erro: Exception
) -> None:
    # O erro do CREATE não diz qual coluna falhou; reavalia a conversão coluna a
    # coluna (count() força a avaliação) até uma estourar.
    for bruta, nova, tipo in COLUNAS[tabela]:
        if tipo == "V":
            continue
        try:
            con.execute(
                f'SELECT count({expressao(bruta, tipo)}) FROM {ORIGEM}."{tabela}"'
            ).fetchall()
        except duckdb.Error as e:
            achado = re.search(r'"([^"]*)"', str(e))
            exemplo = achado.group(1) if achado else str(e)
            print(
                f"Falha de conversão em {ORIGEM}.{tabela}, coluna {bruta} "
                f"({nova}, {tipo}): valor {exemplo!r}"
            )
            sys.exit(1)
    print(f"Falha de conversão em {ORIGEM}.{tabela}: {erro}")
    sys.exit(1)


def transformar(con: duckdb.DuckDBPyConnection, tabela: str) -> tuple[int, int, str]:
    entram = con.execute(f'SELECT count(*) FROM {ORIGEM}."{tabela}"').fetchall()[0][0]
    verificar_conflitos(con, tabela)

    selecao = ", ".join(
        f'{expressao(bruta, tipo)} AS "{nova}"' for bruta, nova, tipo in COLUNAS[tabela]
    )
    try:
        con.execute(
            f'CREATE OR REPLACE TABLE {DESTINO}."{tabela}" AS '
            f'SELECT {selecao} FROM (SELECT DISTINCT * FROM {ORIGEM}."{tabela}")'
        ).fetchall()
    except duckdb.Error as e:
        diagnosticar_conversao(con, tabela, e)

    saem = con.execute(f'SELECT count(*) FROM {DESTINO}."{tabela}"').fetchall()[0][0]
    return entram, saem, tabela


def descrever_nulos(con: duckdb.DuckDBPyConnection, tabela: str) -> str:
    novas = [nova for _, nova, _ in COLUNAS[tabela]]
    contagens = ", ".join(f'count(*) - count("{n}")' for n in novas)
    valores = con.execute(f'SELECT {contagens} FROM {DESTINO}."{tabela}"').fetchall()[0]
    com_nulo = [f"{n} {formatar(v)}" for n, v in zip(novas, valores) if v > 0]
    return "    nulos mantidos: " + ", ".join(com_nulo) if com_nulo else ""


def executar(con: duckdb.DuckDBPyConnection) -> None:
    verificar_entrada(con)
    db.criar_schema(con, DESTINO)
    total = 0
    for tabela in COLUNAS:
        entram, saem, _ = transformar(con, tabela)
        total += saem
        nome = f"{DESTINO}.{tabela}"
        print(
            f"{nome:<27}{formatar(entram):>8} -> {formatar(saem)} linhas"
            f"  ({formatar(entram - saem)} duplicatas)"
        )
        nulos = descrever_nulos(con, tabela)
        if nulos:
            print(nulos)
    print(f"Total: {formatar(total)} linhas")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    con = db.conectar()
    try:
        executar(con)
    finally:
        con.close()


if __name__ == "__main__":
    main()
