"""Testes de pipeline/db.py (spec D1-D4 na docstring do módulo)."""

import duckdb
import pandas as pd
import pytest

from pipeline import db


def usar_banco_em(tmp_path, monkeypatch):
    caminho = tmp_path / "teste.duckdb"
    monkeypatch.setattr(db, "_ARQUIVO_DB", caminho)
    return caminho


def tabelas(con):
    return sorted(
        (s, t)
        for s, t in con.execute(
            "SELECT table_schema, table_name FROM information_schema.tables"
        ).fetchall()
    )


def test_caminhos_sao_absolutos_e_nao_dependem_do_diretorio_corrente(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert db.PASTA_RAW.is_absolute()
    assert db._ARQUIVO_DB.is_absolute()
    assert db.PASTA_RAW.name == "raw"
    assert db.PASTA_RAW.parent == db._ARQUIVO_DB.parent
    assert not str(db.PASTA_RAW).startswith(str(tmp_path))


def test_conectar_cria_o_arquivo_no_caminho_configurado_e_nao_no_diretorio_corrente(
    tmp_path, monkeypatch
):
    pasta_trabalho = tmp_path / "outra_pasta"
    pasta_trabalho.mkdir()
    monkeypatch.chdir(pasta_trabalho)
    caminho = usar_banco_em(tmp_path, monkeypatch)

    con = db.conectar()
    con.close()

    assert caminho.is_file()
    assert list(pasta_trabalho.iterdir()) == []


def test_conectar_devolve_conexao_aberta_e_utilizavel(tmp_path, monkeypatch):
    usar_banco_em(tmp_path, monkeypatch)
    con = db.conectar()
    assert con.execute("SELECT 41 + 1").fetchall() == [(42,)]
    con.close()


def test_conectar_duas_vezes_da_conexoes_independentes(tmp_path, monkeypatch):
    usar_banco_em(tmp_path, monkeypatch)
    a = db.conectar()
    a.close()
    b = db.conectar()
    assert a is not b
    b.close()


def test_criar_schema_cria_o_schema(tmp_path, monkeypatch):
    usar_banco_em(tmp_path, monkeypatch)
    con = db.conectar()
    db.criar_schema(con, "meu_schema")
    nomes = [r[0] for r in con.execute("SELECT schema_name FROM information_schema.schemata").fetchall()]
    con.close()
    assert "meu_schema" in nomes


def test_criar_schema_duas_vezes_nao_da_erro_e_nao_apaga_tabela(tmp_path, monkeypatch):
    usar_banco_em(tmp_path, monkeypatch)
    con = db.conectar()
    db.criar_schema(con, "s")
    db.gravar(con, pd.DataFrame({"a": [1]}), "s", "t")
    db.criar_schema(con, "s")
    linhas = con.execute('SELECT count(*) FROM "s"."t"').fetchall()
    con.close()
    assert linhas == [(1,)]


def test_gravar_devolve_a_contagem_da_tabela_gravada(tmp_path, monkeypatch):
    usar_banco_em(tmp_path, monkeypatch)
    con = db.conectar()
    db.criar_schema(con, "s")
    n = db.gravar(con, pd.DataFrame({"a": [10, 20, 30]}), "s", "t")
    con.close()
    assert n == 3


def test_gravar_mantem_valores_e_tipos_do_dataframe(tmp_path, monkeypatch):
    usar_banco_em(tmp_path, monkeypatch)
    df = pd.DataFrame({"inteiro": [1, 2], "texto": ["a", "b"], "real": [1.5, 2.5]})
    con = db.conectar()
    db.criar_schema(con, "s")
    db.gravar(con, df, "s", "t")
    tipos = dict(
        con.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 's' AND table_name = 't'"
        ).fetchall()
    )
    linhas = con.execute('SELECT * FROM "s"."t" ORDER BY inteiro').fetchall()
    con.close()
    assert tipos == {"inteiro": "BIGINT", "texto": "VARCHAR", "real": "DOUBLE"}
    assert linhas == [(1, "a", 1.5), (2, "b", 2.5)]


def test_gravar_preserva_nulo_como_nulo(tmp_path, monkeypatch):
    usar_banco_em(tmp_path, monkeypatch)
    df = pd.DataFrame({"texto": ["a", None]})
    con = db.conectar()
    db.criar_schema(con, "s")
    db.gravar(con, df, "s", "t")
    nulos = con.execute('SELECT count(*) FROM "s"."t" WHERE texto IS NULL').fetchall()
    vazios = con.execute("""SELECT count(*) FROM "s"."t" WHERE texto = ''""").fetchall()
    con.close()
    assert nulos == [(1,)]
    assert vazios == [(0,)]


def test_gravar_recria_a_tabela_em_vez_de_acrescentar(tmp_path, monkeypatch):
    usar_banco_em(tmp_path, monkeypatch)
    con = db.conectar()
    db.criar_schema(con, "s")
    db.gravar(con, pd.DataFrame({"a": [1, 2, 3]}), "s", "t")
    n = db.gravar(con, pd.DataFrame({"a": [7]}), "s", "t")
    linhas = con.execute('SELECT a FROM "s"."t"').fetchall()
    con.close()
    assert n == 1
    assert linhas == [(7,)]


def test_gravar_troca_as_colunas_quando_o_dataframe_muda(tmp_path, monkeypatch):
    usar_banco_em(tmp_path, monkeypatch)
    con = db.conectar()
    db.criar_schema(con, "s")
    db.gravar(con, pd.DataFrame({"a": [1]}), "s", "t")
    db.gravar(con, pd.DataFrame({"b": ["x"]}), "s", "t")
    colunas = [
        r[0]
        for r in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 's' AND table_name = 't'"
        ).fetchall()
    ]
    con.close()
    assert colunas == ["b"]


def test_gravar_nao_deixa_view_nem_tabela_temporaria_para_tras(tmp_path, monkeypatch):
    usar_banco_em(tmp_path, monkeypatch)
    con = db.conectar()
    db.criar_schema(con, "s")
    db.gravar(con, pd.DataFrame({"a": [1]}), "s", "t")
    restantes = tabelas(con)
    con.close()
    assert restantes == [("s", "t")]


def test_gravar_libera_o_nome_temporario_mesmo_quando_a_gravacao_falha(tmp_path, monkeypatch):
    usar_banco_em(tmp_path, monkeypatch)
    con = db.conectar()
    # Schema inexistente: o CREATE falha, e o finally tem que remover a view.
    with pytest.raises(duckdb.Error):
        db.gravar(con, pd.DataFrame({"a": [1]}), "nao_existe", "t")
    restantes = tabelas(con)
    con.close()
    assert restantes == []
