"""Etapa 3 - Marts: sql/marts/*.sql -> schema marts.

Executar com:  uv run python -m pipeline.marts

1. Escopo
   Lê de refined, escreve no schema marts. Nunca escreve em raw nem em refined.
   O schema marts é apagado e recriado a cada execução (DROP SCHEMA IF EXISTS
   marts CASCADE). Motivo: um mart cujo arquivo foi apagado não pode continuar
   existindo no banco.
2. Um arquivo, uma tabela
   Lê todos os sql/marts/*.sql em ordem alfabética. Nome da tabela = nome do
   arquivo sem a extensão e sem o prefixo numérico:
     sql/marts/01_vendas_mensais.sql -> marts.vendas_mensais
   Executa: CREATE TABLE marts.<nome> AS <conteúdo do arquivo>. Tira espaços e um
   ponto e vírgula do final do conteúdo, e nada mais. O Python não altera, não
   monta e não completa a SQL. Motivo: a regra de negócio mora inteira no .sql.
3. Saída na tela
   Uma linha por mart, com a contagem vinda do banco, milhar com ponto:
     ✓ marts.vendas_mensais        24 linhas
   Linha final com o número de marts e o total de linhas. stdout reconfigurado
   para utf-8. Motivo: o Prompt de Comando do Windows embaralha acentos.
4. Erro
   a. Antes de tudo: se faltar qualquer tabela de refined (pedidos, itens_pedido,
      produtos, traducao_categorias, avaliacoes, clientes), lista quais, manda
      rodar "uv run python -m pipeline.transformacao" e encerra com sys.exit(1).
      Motivo: sem a entrada, todo erro seguinte seria confuso.
   b. Se sql/marts/ não tiver nenhum arquivo: avisa e sys.exit(1). Motivo: um
      schema marts vazio parece sucesso e esvazia o dashboard.
   c. Antes de executar qualquer SQL: arquivo sem prefixo NN_ ou dois arquivos que
      dão o mesmo nome de tabela -> lista quais e sys.exit(1). Motivo: nome
      ambíguo não pode sobrescrever mart em silêncio.
   d. Se um .sql falhar: mostra o nome do arquivo e a mensagem do DuckDB, não
      executa os seguintes, sys.exit(1). Motivo: os seguintes podem depender dele.
   e. Se um mart voltar com zero linhas: mostra o nome e sys.exit(1). Motivo: mart
      vazio é quase sempre um JOIN que não casou, e dashboard vazio parece
      negócio parado.
   f. Tudo roda numa transação só: se qualquer passo falhar (inclusive o mart
      vazio), marts volta a ser o da última execução que deu certo. Motivo: um
      schema pela metade quebra o dashboard sem avisar.

Critérios de aceite
   - Com sql/marts/00_teste.sql contendo "SELECT 1 AS x", cria marts.teste com
     1 linha.
   - Apagar o arquivo e rodar de novo faz marts.teste desaparecer.
   - Arquivo com erro de sintaxe para tudo, mostra o nome do arquivo, e marts
     continua exatamente como estava.
   - Arquivo teste.sql, sem prefixo, para antes de executar qualquer SQL.
   - Rodar duas vezes seguidas imprime exatamente a mesma coisa.
"""

import re
import sys
from collections import defaultdict
from pathlib import Path

import duckdb

from pipeline import db

ORIGEM = "refined"
DESTINO = "marts"
PASTA_SQL = Path(__file__).resolve().parent.parent / "sql" / "marts"
TABELAS_REFINED = [
    "pedidos",
    "itens_pedido",
    "produtos",
    "traducao_categorias",
    "avaliacoes",
    "clientes",
]
PADRAO_ARQUIVO = re.compile(r"^\d+_(.+)\.sql$")


def formatar(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def verificar_entrada(con: duckdb.DuckDBPyConnection) -> None:
    existentes = {
        linha[0]
        for linha in con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = ?",
            [ORIGEM],
        ).fetchall()
    }
    faltando = [t for t in TABELAS_REFINED if t not in existentes]
    if faltando:
        print(f"Tabelas faltando em {ORIGEM}: {', '.join(faltando)}")
        print("Rode primeiro: uv run python -m pipeline.transformacao")
        sys.exit(1)


def listar_marts() -> list[tuple[Path, str]]:
    """Devolve (arquivo, nome da tabela) em ordem alfabética, já validado."""
    arquivos = sorted(PASTA_SQL.glob("*.sql"), key=lambda p: p.name)
    if not arquivos:
        print(f"Nenhum arquivo .sql em {PASTA_SQL}")
        sys.exit(1)

    sem_prefixo = [a.name for a in arquivos if not PADRAO_ARQUIVO.match(a.name)]
    por_nome = defaultdict(list)
    for a in arquivos:
        m = PADRAO_ARQUIVO.match(a.name)
        if m:
            por_nome[m.group(1)].append(a.name)
    repetidos = {n: fs for n, fs in por_nome.items() if len(fs) > 1}

    if sem_prefixo or repetidos:
        if sem_prefixo:
            print("Arquivos sem prefixo NN_:")
            for nome in sem_prefixo:
                print(f"  {nome}")
        for tabela, fs in repetidos.items():
            print(f"Arquivos que dão a mesma tabela {DESTINO}.{tabela}: {', '.join(fs)}")
        sys.exit(1)

    return [(a, PADRAO_ARQUIVO.match(a.name).group(1)) for a in arquivos]


def ler_sql(arquivo: Path) -> str:
    # Só espaços e um ';' do final saem; o resto do texto é do .sql.
    sql = arquivo.read_text(encoding="utf-8").rstrip()
    if sql.endswith(";"):
        sql = sql[:-1].rstrip()
    return sql


def construir(con: duckdb.DuckDBPyConnection, marts: list[tuple[Path, str]]) -> list[tuple[str, int]]:
    resultado = []
    con.execute(f"DROP SCHEMA IF EXISTS {DESTINO} CASCADE")
    db.criar_schema(con, DESTINO)
    for arquivo, tabela in marts:
        destino = f'{DESTINO}."{tabela}"'
        try:
            con.execute(f"CREATE TABLE {destino} AS {ler_sql(arquivo)}")
        except duckdb.Error as e:
            print(f"Erro em {arquivo.name}: {e}")
            sys.exit(1)
        linhas = con.execute(f"SELECT count(*) FROM {destino}").fetchall()[0][0]
        if linhas == 0:
            print(f"Mart vazio: {DESTINO}.{tabela} ({arquivo.name}) voltou com zero linhas")
            sys.exit(1)
        resultado.append((f"{DESTINO}.{tabela}", linhas))
    return resultado


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")

    con = db.conectar()
    try:
        verificar_entrada(con)
        marts = listar_marts()

        con.execute("BEGIN TRANSACTION")
        try:
            resultado = construir(con, marts)
            con.execute("COMMIT")
        except BaseException:
            # sys.exit também é BaseException: o rollback vale para todo caminho de falha.
            con.execute("ROLLBACK")
            raise
    finally:
        con.close()

    # A saída só sai após o commit: nada de "✓" para mart que acabou revertido.
    largura = max(len(nome) for nome, _ in resultado)
    largura_n = max(len(formatar(n)) for _, n in resultado)
    for nome, n in resultado:
        print(f"✓ {nome:<{largura}}  {formatar(n):>{largura_n}} linhas")
    total = sum(n for _, n in resultado)
    print(f"{len(resultado)} marts, {formatar(total)} linhas no total")


if __name__ == "__main__":
    main()
