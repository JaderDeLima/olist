"""Testes de pipeline/ingestao.py (spec 1-7 na docstring do módulo).

Os CSV são escritos pelo próprio teste em tmp_path; raw/ e olist.duckdb do
projeto nunca são tocados.
"""

import gzip
import io
import sys

import duckdb
import pytest

from pipeline import db, ingestao

CSV_MINIMO = "a,b\n1,x\n"


def escrever_csv_gz(caminho, texto):
    with gzip.open(caminho, "wt", encoding="utf-8", newline="") as f:
        f.write(texto)


def preparar(tmp_path, monkeypatch, **conteudos):
    """Cria os nove .csv.gz em tmp_path/raw e aponta o db para tmp_path.

    conteudos: tabela (nome em português) -> texto CSV; as demais recebem CSV_MINIMO.
    """
    pasta = tmp_path / "raw"
    pasta.mkdir()
    for arquivo, tabela in ingestao.TABELAS.items():
        escrever_csv_gz(pasta / arquivo, conteudos.get(tabela, CSV_MINIMO))
    banco = tmp_path / "teste.duckdb"
    monkeypatch.setattr(db, "PASTA_RAW", pasta)
    monkeypatch.setattr(db, "_ARQUIVO_DB", banco)
    return pasta, banco


def capturar_saida(monkeypatch):
    buf = io.BytesIO()
    texto = io.TextIOWrapper(buf, encoding="utf-8", newline="\n", write_through=True)
    monkeypatch.setattr(sys, "stdout", texto)
    return lambda: buf.getvalue().decode("utf-8")


def consultar(banco, sql):
    con = duckdb.connect(str(banco))
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def test_formatar_usa_ponto_como_separador_de_milhar():
    assert ingestao.formatar(1234567) == "1.234.567"
    assert ingestao.formatar(1000) == "1.000"
    assert ingestao.formatar(999) == "999"
    assert ingestao.formatar(0) == "0"


def test_csv_vira_tabela_com_as_mesmas_linhas(tmp_path, monkeypatch):
    # três pedidos no CSV de pedidos; os outros oito arquivos têm uma linha cada
    pedidos = "id,status\np1,delivered\np2,canceled\np3,shipped\n"
    _, banco = preparar(tmp_path, monkeypatch, pedidos=pedidos)
    ingestao.main()
    linhas = consultar(banco, "SELECT id, status FROM raw.pedidos ORDER BY id")
    assert linhas == [("p1", "delivered"), ("p2", "canceled"), ("p3", "shipped")]


def test_os_nove_arquivos_viram_as_nove_tabelas_em_portugues(tmp_path, monkeypatch):
    _, banco = preparar(tmp_path, monkeypatch)
    ingestao.main()
    nomes = {
        r[0]
        for r in consultar(
            banco, "SELECT table_name FROM information_schema.tables WHERE table_schema = 'raw'"
        )
    }
    assert nomes == {
        "pedidos",
        "itens_pedido",
        "pagamentos",
        "avaliacoes",
        "clientes",
        "vendedores",
        "produtos",
        "traducao_categorias",
        "geolocalizacao",
    }


def test_campo_vazio_vira_nulo_mas_texto_NA_e_null_continuam_texto(tmp_path, monkeypatch):
    # linha com campo vazio, com "NA" e com "null": só o vazio pode virar nulo
    pedidos = "id,vazio,na,nulo\np1,,NA,null\n"
    _, banco = preparar(tmp_path, monkeypatch, pedidos=pedidos)
    ingestao.main()
    linha = consultar(banco, "SELECT vazio IS NULL, na, nulo FROM raw.pedidos")
    assert linha == [(True, "NA", "null")]


def test_toda_coluna_entra_como_texto(tmp_path, monkeypatch):
    # número, data e decimal no CSV: nada pode ser inferido
    pedidos = "id,qtd,data,valor\n1,2,2018-01-05 10:00:00,12.50\n"
    _, banco = preparar(tmp_path, monkeypatch, pedidos=pedidos)
    ingestao.main()
    tipos = consultar(
        banco,
        "SELECT DISTINCT data_type FROM information_schema.columns "
        "WHERE table_schema = 'raw' AND table_name = 'pedidos'",
    )
    valores = consultar(banco, "SELECT id, qtd, data, valor FROM raw.pedidos")
    assert tipos == [("VARCHAR",)]
    assert valores == [("1", "2", "2018-01-05 10:00:00", "12.50")]


def test_cep_com_zero_a_esquerda_continua_com_o_zero(tmp_path, monkeypatch):
    # CEP começando com zero: se fosse inferido como número, viraria "1037"
    clientes = "cliente,cep\nc1,01037\n"
    _, banco = preparar(tmp_path, monkeypatch, clientes=clientes)
    ingestao.main()
    assert consultar(banco, "SELECT cep FROM raw.clientes") == [("01037",)]


def test_acentos_chegam_em_utf8(tmp_path, monkeypatch):
    # cidade com acento: encoding utf-8 declarado, não adivinhado
    clientes = "cliente,cidade\nc1,São Paulo\n"
    _, banco = preparar(tmp_path, monkeypatch, clientes=clientes)
    ingestao.main()
    assert consultar(banco, "SELECT cidade FROM raw.clientes") == [("São Paulo",)]


def test_linha_duplicada_no_csv_nao_e_removida(tmp_path, monkeypatch):
    # linha idêntica repetida: dedup só acontece na etapa 2, não aqui
    pedidos = "id,status\np1,delivered\np1,delivered\n"
    _, banco = preparar(tmp_path, monkeypatch, pedidos=pedidos)
    ingestao.main()
    assert consultar(banco, "SELECT count(*) FROM raw.pedidos") == [(2,)]


def test_reexecutar_recria_a_tabela_em_vez_de_acrescentar(tmp_path, monkeypatch):
    pedidos = "id,status\np1,delivered\np2,canceled\n"
    _, banco = preparar(tmp_path, monkeypatch, pedidos=pedidos)
    ingestao.main()
    ingestao.main()
    assert consultar(banco, "SELECT count(*) FROM raw.pedidos") == [(2,)]


def test_saida_tem_uma_linha_por_tabela_e_uma_de_total(tmp_path, monkeypatch):
    # pedidos com 3 linhas + 8 tabelas com 1 linha = 11
    pedidos = "id\np1\np2\np3\n"
    preparar(tmp_path, monkeypatch, pedidos=pedidos)
    saida = capturar_saida(monkeypatch)
    ingestao.main()
    linhas = saida().splitlines()
    assert len(linhas) == 10
    assert "raw.pedidos: 3 linhas" in linhas
    assert "raw.geolocalizacao: 1 linhas" in linhas
    assert linhas[-1] == "Total: 11 registros"


def test_saida_da_segunda_execucao_e_igual_a_da_primeira(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    saida = capturar_saida(monkeypatch)
    ingestao.main()
    primeira = saida()
    capturar_saida_2 = capturar_saida(monkeypatch)
    ingestao.main()
    assert capturar_saida_2() == primeira


def test_arquivo_faltando_encerra_com_systemexit(tmp_path, monkeypatch):
    pasta, _ = preparar(tmp_path, monkeypatch)
    (pasta / "olist_sellers_dataset.csv.gz").unlink()
    saida = capturar_saida(monkeypatch)
    with pytest.raises(SystemExit) as erro:
        ingestao.main()
    assert erro.value.code == 1
    texto = saida()
    assert "olist_sellers_dataset.csv.gz" in texto
    assert str(pasta) in texto


def test_arquivo_faltando_lista_todos_os_que_faltam(tmp_path, monkeypatch):
    pasta, _ = preparar(tmp_path, monkeypatch)
    (pasta / "olist_sellers_dataset.csv.gz").unlink()
    (pasta / "olist_orders_dataset.csv.gz").unlink()
    saida = capturar_saida(monkeypatch)
    with pytest.raises(SystemExit):
        ingestao.main()
    texto = saida()
    assert "olist_sellers_dataset.csv.gz" in texto
    assert "olist_orders_dataset.csv.gz" in texto


def test_arquivo_faltando_nao_abre_o_banco_nem_ingere_parcialmente(tmp_path, monkeypatch):
    pasta, banco = preparar(tmp_path, monkeypatch)
    (pasta / "olist_sellers_dataset.csv.gz").unlink()
    with pytest.raises(SystemExit):
        ingestao.main()
    assert not banco.exists()
