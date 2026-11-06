"""Testes de pipeline/refinar_tabelas.py: oito tabelas de raw -> refined.

Todas as linhas de entrada são inventadas pelo teste.
"""

import duckdb
import pytest

from pipeline import db, refinar_tabelas


def criar_raw(banco, omitir=()):
    con = duckdb.connect(str(banco))
    try:
        con.execute("CREATE SCHEMA raw")
        for tabela, colunas in refinar_tabelas.COLUNAS.items():
            if tabela in omitir:
                continue
            nomes = [c[0] for c in colunas]
            con.execute(
                f'CREATE TABLE raw."{tabela}" ('
                + ", ".join(f'"{n}" VARCHAR' for n in nomes)
                + ")"
            )
            valores = []
            for _, _, tipo in colunas:
                valores.append(
                    {
                        "TS": "2018-01-02 03:04:05",
                        "D": "2018-01-02 00:00:00",
                        "DEC": "10.50",
                        "INT": "3",
                    }.get(tipo, "x")
                )
            marcas = ", ".join("?" for _ in nomes)
            # a mesma linha duas vezes: uma duplicata exata por tabela
            con.executemany(f'INSERT INTO raw."{tabela}" VALUES ({marcas})', [valores, valores])
    finally:
        con.close()


def test_todas_as_oito_tabelas_vao_para_refined_sem_a_duplicata(tmp_path, monkeypatch):
    banco = tmp_path / "t.duckdb"
    monkeypatch.setattr(db, "_ARQUIVO_DB", banco)
    criar_raw(banco)
    refinar_tabelas.main()
    con = duckdb.connect(str(banco))
    try:
        for tabela, colunas in refinar_tabelas.COLUNAS.items():
            assert con.execute(f'SELECT count(*) FROM refined."{tabela}"').fetchall() == [(1,)]
            nomes = [r[0] for r in con.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='refined' AND table_name=? ORDER BY ordinal_position",
                [tabela],
            ).fetchall()]
            assert nomes == [c[1] for c in colunas]
        assert con.execute("SELECT typeof(preco) FROM refined.itens_pedido").fetchall() == [
            ("DECIMAL(10,2)",)
        ]
    finally:
        con.close()


def test_tabela_faltando_em_raw_manda_rodar_a_ingestao(tmp_path, monkeypatch, capsys):
    banco = tmp_path / "t.duckdb"
    monkeypatch.setattr(db, "_ARQUIVO_DB", banco)
    criar_raw(banco, omitir=("pedidos",))
    with pytest.raises(SystemExit):
        refinar_tabelas.main()
    texto = capsys.readouterr().out
    assert "raw.pedidos" in texto
    assert "pipeline.ingestao" in texto
