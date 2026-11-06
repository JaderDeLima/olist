"""Testes de pipeline/marts.py e de sql/marts/01 e 03 (spec e critérios na docstring).

Banco novo em tmp_path, pasta de SQL em tmp_path, tabelas de refined inventadas.
"""

import io
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from pipeline import db, marts

SQL_REAL = Path(marts.__file__).resolve().parent.parent / "sql" / "marts"


def preparar(tmp_path, monkeypatch, arquivos, com_refined=True):
    """Banco novo + pasta sql/marts em tmp_path. arquivos: nome -> texto SQL."""
    banco = tmp_path / "teste.duckdb"
    pasta = tmp_path / "sql_marts"
    pasta.mkdir()
    monkeypatch.setattr(db, "_ARQUIVO_DB", banco)
    monkeypatch.setattr(marts, "PASTA_SQL", pasta)
    if com_refined:
        con = duckdb.connect(str(banco))
        try:
            con.execute("CREATE SCHEMA refined")
            for tabela in marts.TABELAS_REFINED:
                con.execute(f"CREATE TABLE refined.{tabela} (x INTEGER)")
        finally:
            con.close()
    escrever(pasta, arquivos)
    return banco, pasta


def escrever(pasta, arquivos):
    for nome, texto in arquivos.items():
        (pasta / nome).write_text(texto, encoding="utf-8")


def consultar(banco, sql):
    con = duckdb.connect(str(banco))
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def tabelas_marts(banco):
    return sorted(
        r[0]
        for r in consultar(
            banco, "SELECT table_name FROM information_schema.tables WHERE table_schema = 'marts'"
        )
    )


def schema_marts_existe(banco):
    return consultar(
        banco, "SELECT count(*) FROM information_schema.schemata WHERE schema_name = 'marts'"
    ) == [(1,)]


def capturar_saida(monkeypatch):
    buf = io.BytesIO()
    texto = io.TextIOWrapper(buf, encoding="utf-8", newline="\n", write_through=True)
    monkeypatch.setattr(sys, "stdout", texto)
    return lambda: buf.getvalue().decode("utf-8")


# --- ler_sql -------------------------------------------------------------------


def test_ler_sql_tira_espacos_e_um_ponto_e_virgula_do_final(tmp_path):
    arquivo = tmp_path / "01_x.sql"
    arquivo.write_text("SELECT 1 AS x ;  \n\n", encoding="utf-8")
    assert marts.ler_sql(arquivo) == "SELECT 1 AS x"


def test_ler_sql_nao_mexe_no_resto_do_texto(tmp_path):
    arquivo = tmp_path / "01_x.sql"
    texto = "-- comentário; com ponto e vírgula\nSELECT 1;  2\nFROM t"
    arquivo.write_text(texto, encoding="utf-8")
    assert marts.ler_sql(arquivo) == texto


def test_ler_sql_tira_so_um_ponto_e_virgula(tmp_path):
    arquivo = tmp_path / "01_x.sql"
    arquivo.write_text("SELECT 1;;", encoding="utf-8")
    assert marts.ler_sql(arquivo) == "SELECT 1;"


# --- main: critérios de aceite -------------------------------------------------


def test_arquivo_00_teste_cria_mart_teste_com_uma_linha(tmp_path, monkeypatch):
    banco, _ = preparar(tmp_path, monkeypatch, {"00_teste.sql": "SELECT 1 AS x"})
    marts.main()
    assert consultar(banco, "SELECT x FROM marts.teste") == [(1,)]


def test_apagar_o_arquivo_faz_o_mart_sumir_na_execucao_seguinte(tmp_path, monkeypatch):
    # dois arquivos; o segundo é apagado antes da segunda execução
    banco, pasta = preparar(
        tmp_path,
        monkeypatch,
        {"00_teste.sql": "SELECT 1 AS x", "01_outro.sql": "SELECT 2 AS y"},
    )
    marts.main()
    assert tabelas_marts(banco) == ["outro", "teste"]
    (pasta / "00_teste.sql").unlink()
    marts.main()
    assert tabelas_marts(banco) == ["outro"]


def test_nome_da_tabela_e_o_do_arquivo_sem_extensao_e_sem_prefixo(tmp_path, monkeypatch):
    banco, _ = preparar(
        tmp_path,
        monkeypatch,
        {"01_vendas_mensais.sql": "SELECT 1 AS x", "12_clientes_por_uf.sql": "SELECT 1 AS x"},
    )
    marts.main()
    assert tabelas_marts(banco) == ["clientes_por_uf", "vendas_mensais"]


def test_arquivo_sem_prefixo_para_antes_de_executar_qualquer_sql(tmp_path, monkeypatch):
    # teste.sql sem NN_; 00_ok.sql é válido e viria antes na ordem alfabética
    banco, _ = preparar(
        tmp_path, monkeypatch, {"00_ok.sql": "SELECT 1 AS x", "teste.sql": "SELECT 1 AS x"}
    )
    saida = capturar_saida(monkeypatch)
    with pytest.raises(SystemExit) as erro:
        marts.main()
    assert erro.value.code == 1
    assert "teste.sql" in saida()
    assert not schema_marts_existe(banco)


def test_dois_arquivos_com_o_mesmo_nome_de_tabela_param_antes_de_executar(tmp_path, monkeypatch):
    banco, _ = preparar(
        tmp_path, monkeypatch, {"01_vendas.sql": "SELECT 1 AS x", "02_vendas.sql": "SELECT 2 AS x"}
    )
    saida = capturar_saida(monkeypatch)
    with pytest.raises(SystemExit) as erro:
        marts.main()
    texto = saida()
    assert erro.value.code == 1
    assert "01_vendas.sql" in texto
    assert "02_vendas.sql" in texto
    assert not schema_marts_existe(banco)


def test_pasta_sem_nenhum_sql_encerra(tmp_path, monkeypatch):
    banco, _ = preparar(tmp_path, monkeypatch, {})
    saida = capturar_saida(monkeypatch)
    with pytest.raises(SystemExit) as erro:
        marts.main()
    assert erro.value.code == 1
    assert "Nenhum arquivo .sql" in saida()
    assert not schema_marts_existe(banco)


def test_faltando_tabela_de_refined_lista_quais_e_manda_rodar_a_transformacao(
    tmp_path, monkeypatch
):
    banco, _ = preparar(tmp_path, monkeypatch, {"01_a.sql": "SELECT 1 AS x"})
    con = duckdb.connect(str(banco))
    con.execute("DROP TABLE refined.clientes")
    con.execute("DROP TABLE refined.avaliacoes")
    con.close()
    saida = capturar_saida(monkeypatch)
    with pytest.raises(SystemExit) as erro:
        marts.main()
    texto = saida()
    assert erro.value.code == 1
    assert "avaliacoes" in texto
    assert "clientes" in texto
    assert "pedidos" not in texto
    assert "uv run python -m pipeline.transformacao" in texto
    assert not schema_marts_existe(banco)


def test_sem_schema_refined_tambem_encerra(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch, {"01_a.sql": "SELECT 1 AS x"}, com_refined=False)
    capturar_saida(monkeypatch)
    with pytest.raises(SystemExit) as erro:
        marts.main()
    assert erro.value.code == 1


def test_mart_vazio_encerra_e_deixa_o_schema_marts_como_estava(tmp_path, monkeypatch):
    # primeira execução boa; depois um segundo arquivo que devolve zero linhas
    banco, pasta = preparar(tmp_path, monkeypatch, {"00_teste.sql": "SELECT 1 AS x"})
    marts.main()
    escrever(pasta, {"01_vazio.sql": "SELECT 1 AS x WHERE false"})
    saida = capturar_saida(monkeypatch)
    with pytest.raises(SystemExit) as erro:
        marts.main()
    assert erro.value.code == 1
    assert "01_vazio.sql" in saida()
    assert tabelas_marts(banco) == ["teste"]
    assert consultar(banco, "SELECT x FROM marts.teste") == [(1,)]


def test_mart_vazio_na_primeira_execucao_nao_deixa_mart_nenhum(tmp_path, monkeypatch):
    banco, _ = preparar(
        tmp_path,
        monkeypatch,
        {"00_bom.sql": "SELECT 1 AS x", "01_vazio.sql": "SELECT 1 AS x WHERE false"},
    )
    capturar_saida(monkeypatch)
    with pytest.raises(SystemExit):
        marts.main()
    assert tabelas_marts(banco) == []


def test_erro_de_sintaxe_para_mostra_o_arquivo_e_marts_continua_como_estava(tmp_path, monkeypatch):
    banco, pasta = preparar(
        tmp_path, monkeypatch, {"00_teste.sql": "SELECT 1 AS x", "01_outro.sql": "SELECT 5 AS y"}
    )
    marts.main()
    # agora 00 muda de valor e 01 ganha erro de sintaxe: nada pode ter mudado
    escrever(pasta, {"00_teste.sql": "SELECT 99 AS x", "01_outro.sql": "SELEC 5 FROMM"})
    saida = capturar_saida(monkeypatch)
    with pytest.raises(SystemExit) as erro:
        marts.main()
    assert erro.value.code == 1
    assert "01_outro.sql" in saida()
    assert tabelas_marts(banco) == ["outro", "teste"]
    assert consultar(banco, "SELECT x FROM marts.teste") == [(1,)]
    assert consultar(banco, "SELECT y FROM marts.outro") == [(5,)]


def test_erro_em_um_arquivo_reverte_os_marts_ja_criados_na_mesma_execucao(tmp_path, monkeypatch):
    # 01 cria o mart; 02 quebra; o resultado final não pode ter nem o 01
    banco, _ = preparar(
        tmp_path,
        monkeypatch,
        {
            "01_a.sql": "SELECT 1 AS x",
            "02_quebrado.sql": "SELEC",
            "03_c.sql": "SELECT 3 AS x",
        },
    )
    texto = capturar_saida(monkeypatch)
    with pytest.raises(SystemExit):
        marts.main()
    assert "02_quebrado.sql" in texto()
    assert tabelas_marts(banco) == []


def test_mart_pode_ler_um_mart_anterior(tmp_path, monkeypatch):
    # execução na ordem alfabética: o 02 usa a tabela criada pelo 01
    banco, _ = preparar(
        tmp_path,
        monkeypatch,
        {"01_base.sql": "SELECT 4 AS x", "02_derivado.sql": "SELECT x * 2 AS dobro FROM marts.base"},
    )
    marts.main()
    assert consultar(banco, "SELECT dobro FROM marts.derivado") == [(8,)]


# --- main: saída ---------------------------------------------------------------


def test_saida_tem_uma_linha_por_mart_na_ordem_alfabetica_e_um_total(tmp_path, monkeypatch):
    preparar(
        tmp_path,
        monkeypatch,
        {
            "02_b.sql": "SELECT 1 AS x UNION ALL SELECT 2 UNION ALL SELECT 3",
            "01_a.sql": "SELECT 1 AS x UNION ALL SELECT 2",
        },
    )
    saida = capturar_saida(monkeypatch)
    marts.main()
    assert saida().splitlines() == [
        "✓ marts.a  2 linhas",
        "✓ marts.b  3 linhas",
        "2 marts, 5 linhas no total",
    ]


def test_saida_usa_ponto_de_milhar_na_contagem(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch, {"01_grande.sql": "SELECT range AS x FROM range(1500)"})
    saida = capturar_saida(monkeypatch)
    marts.main()
    assert saida().splitlines() == [
        "✓ marts.grande  1.500 linhas",
        "1 marts, 1.500 linhas no total",
    ]


def test_rodar_duas_vezes_seguidas_imprime_exatamente_a_mesma_coisa(tmp_path, monkeypatch):
    preparar(
        tmp_path,
        monkeypatch,
        {"01_a.sql": "SELECT 1 AS x", "02_b.sql": "SELECT 1 AS x UNION ALL SELECT 2"},
    )
    primeira = capturar_saida(monkeypatch)
    marts.main()
    texto_1 = primeira()
    segunda = capturar_saida(monkeypatch)
    marts.main()
    assert segunda() == texto_1
    assert texto_1 != ""


# --- sql/marts/01_vendas_mensais.sql e 03_entrega_no_prazo.sql ------------------


def refined_inventado(tmp_path):
    """Banco com refined.pedidos e refined.itens_pedido vazios, nos tipos da etapa 2."""
    banco = tmp_path / "sql.duckdb"
    con = duckdb.connect(str(banco))
    con.execute("CREATE SCHEMA refined")
    con.execute(
        "CREATE TABLE refined.pedidos ("
        "pedido_id VARCHAR, cliente_id VARCHAR, status VARCHAR, data_compra TIMESTAMP, "
        "data_aprovacao TIMESTAMP, data_envio TIMESTAMP, data_entrega TIMESTAMP, "
        "data_entrega_prevista DATE)"
    )
    con.execute(
        "CREATE TABLE refined.itens_pedido ("
        "pedido_id VARCHAR, item_seq INTEGER, produto_id VARCHAR, vendedor_id VARCHAR, "
        "data_limite_envio TIMESTAMP, preco DECIMAL(10,2), frete DECIMAL(10,2))"
    )
    con.close()
    return banco


def pedido(banco, pedido_id, status, compra=None, entrega=None, prevista=None):
    con = duckdb.connect(str(banco))
    con.execute(
        "INSERT INTO refined.pedidos (pedido_id, status, data_compra, data_entrega, "
        "data_entrega_prevista) VALUES (?, ?, ?, ?, ?)",
        [pedido_id, status, compra, entrega, prevista],
    )
    con.close()


def item(banco, pedido_id, seq, preco):
    con = duckdb.connect(str(banco))
    con.execute(
        "INSERT INTO refined.itens_pedido (pedido_id, item_seq, preco) VALUES (?, ?, ?)",
        [pedido_id, seq, Decimal(preco)],
    )
    con.close()


def rodar_mart(banco, arquivo):
    con = duckdb.connect(str(banco))
    try:
        return con.execute(marts.ler_sql(SQL_REAL / arquivo)).fetchall()
    finally:
        con.close()


MART_01 = "01_vendas_mensais.sql"
MART_03 = "03_entrega_no_prazo.sql"
JAN = datetime(2018, 1, 5, 10, 0)


def test_pedido_com_dois_itens_conta_uma_vez(tmp_path):
    # P1 tem dois itens (10,00 + 20,50): um pedido, receita 30,50
    banco = refined_inventado(tmp_path)
    pedido(banco, "P1", "delivered", compra=JAN)
    item(banco, "P1", 1, "10.00")
    item(banco, "P1", 2, "20.50")
    assert rodar_mart(banco, MART_01) == [(date(2018, 1, 1), 1, Decimal("30.50"))]


def test_cancelado_fica_fora_da_receita(tmp_path):
    # P2 cancelado com item de 99,00: não entra nem na receita nem na contagem
    banco = refined_inventado(tmp_path)
    pedido(banco, "P1", "delivered", compra=JAN)
    item(banco, "P1", 1, "10.00")
    pedido(banco, "P2", "canceled", compra=JAN)
    item(banco, "P2", 1, "99.00")
    assert rodar_mart(banco, MART_01) == [(date(2018, 1, 1), 1, Decimal("10.00"))]


def test_indisponivel_fica_fora_da_receita(tmp_path):
    # P2 unavailable com item de 77,00
    banco = refined_inventado(tmp_path)
    pedido(banco, "P1", "delivered", compra=JAN)
    item(banco, "P1", 1, "10.00")
    pedido(banco, "P2", "unavailable", compra=JAN)
    item(banco, "P2", 1, "77.00")
    assert rodar_mart(banco, MART_01) == [(date(2018, 1, 1), 1, Decimal("10.00"))]


def test_pedido_sem_item_nao_aparece_na_receita(tmp_path):
    # P2 em março sem nenhum item: o JOIN o exclui e março não existe
    banco = refined_inventado(tmp_path)
    pedido(banco, "P1", "delivered", compra=JAN)
    item(banco, "P1", 1, "10.00")
    pedido(banco, "P2", "delivered", compra=datetime(2018, 3, 1, 9, 0))
    assert rodar_mart(banco, MART_01) == [(date(2018, 1, 1), 1, Decimal("10.00"))]


def test_pedidos_do_mesmo_mes_somam_e_meses_saem_em_ordem(tmp_path):
    # fevereiro inserido antes de janeiro; janeiro tem dois pedidos (dia 5 e dia 28)
    banco = refined_inventado(tmp_path)
    pedido(banco, "F1", "delivered", compra=datetime(2018, 2, 3, 8, 0))
    item(banco, "F1", 1, "1.10")
    pedido(banco, "J1", "delivered", compra=JAN)
    item(banco, "J1", 1, "10.00")
    pedido(banco, "J2", "shipped", compra=datetime(2018, 1, 28, 23, 59))
    item(banco, "J2", 1, "5.25")
    assert rodar_mart(banco, MART_01) == [
        (date(2018, 1, 1), 2, Decimal("15.25")),
        (date(2018, 2, 1), 1, Decimal("1.10")),
    ]


def test_entrega_as_15h_do_dia_previsto_esta_no_prazo(tmp_path):
    # chegou no dia previsto, à tarde: no prazo
    banco = refined_inventado(tmp_path)
    pedido(
        banco, "P1", "delivered",
        entrega=datetime(2018, 1, 10, 15, 0), prevista=date(2018, 1, 10),
    )
    assert rodar_mart(banco, MART_03) == [(1, 1, 0, 100.0)]


def test_entrega_um_dia_depois_do_previsto_esta_atrasada(tmp_path):
    # chegou 00:01 do dia seguinte ao previsto
    banco = refined_inventado(tmp_path)
    pedido(
        banco, "P1", "delivered",
        entrega=datetime(2018, 1, 11, 0, 1), prevista=date(2018, 1, 10),
    )
    assert rodar_mart(banco, MART_03) == [(1, 0, 1, 0.0)]


def test_entrega_antes_do_previsto_esta_no_prazo(tmp_path):
    banco = refined_inventado(tmp_path)
    pedido(
        banco, "P1", "delivered",
        entrega=datetime(2018, 1, 5, 9, 0), prevista=date(2018, 1, 10),
    )
    assert rodar_mart(banco, MART_03) == [(1, 1, 0, 100.0)]


def test_so_delivered_com_data_de_entrega_entra_no_denominador(tmp_path):
    # A: no prazo; B: no prazo; C: atrasado; D: no prazo (3 de 4 = 75%)
    # E: delivered sem data de entrega (fora); F: canceled com data (fora)
    banco = refined_inventado(tmp_path)
    prevista = date(2018, 1, 10)
    pedido(banco, "A", "delivered", entrega=datetime(2018, 1, 3, 8, 0), prevista=prevista)
    pedido(banco, "B", "delivered", entrega=datetime(2018, 1, 10, 15, 0), prevista=prevista)
    pedido(banco, "C", "delivered", entrega=datetime(2018, 1, 12, 8, 0), prevista=prevista)
    pedido(banco, "D", "delivered", entrega=datetime(2018, 1, 9, 8, 0), prevista=prevista)
    pedido(banco, "E", "delivered", entrega=None, prevista=prevista)
    pedido(banco, "F", "canceled", entrega=datetime(2018, 1, 1, 8, 0), prevista=prevista)
    assert rodar_mart(banco, MART_03) == [(4, 3, 1, 75.0)]
