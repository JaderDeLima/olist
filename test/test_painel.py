"""Testes de painel.py (spec P1, P2, P4 na docstring do módulo).

Banco novo em tmp_path (painel.BANCO apontado para ele); DataFrames inventados.
"""

from datetime import date

import duckdb
import pandas as pd
import pytest

import painel
from pipeline import db


def gravar_marts(caminho, tabelas):
    """tabelas: nome real do mart (valor de painel.MARTS) -> DataFrame."""
    con = duckdb.connect(str(caminho))
    try:
        db.criar_schema(con, "marts")
        for nome, df in tabelas.items():
            db.gravar(con, df, "marts", nome)
    finally:
        con.close()


# --- P4. Formato ---------------------------------------------------------------


def test_numero_usa_ponto_no_milhar_e_virgula_no_decimal():
    assert painel.numero(1234567.891, 2) == "1.234.567,89"


def test_numero_sem_casas_nao_tem_virgula():
    assert painel.numero(1234567) == "1.234.567"


def test_numero_abaixo_de_mil_nao_tem_ponto():
    assert painel.numero(999) == "999"
    assert painel.numero(0.5, 1) == "0,5"


def test_numero_negativo_mantem_o_sinal():
    assert painel.numero(-1234.5, 1) == "-1.234,5"


def test_numero_arredonda_para_as_casas_pedidas():
    assert painel.numero(2.678, 2) == "2,68"
    assert painel.numero(2.678, 0) == "3"


def test_reais_poe_o_prefixo_e_duas_casas_por_padrao():
    assert painel.reais(1234.5) == "R$ 1.234,50"
    assert painel.reais(0) == "R$ 0,00"


def test_reais_aceita_outro_numero_de_casas():
    assert painel.reais(1234567.891, 0) == "R$ 1.234.568"
    assert painel.reais(10, 1) == "R$ 10,0"


def test_pct_poe_o_sinal_e_uma_casa_por_padrao():
    assert painel.pct(50.04) == "50,0%"
    assert painel.pct(7.26) == "7,3%"


def test_pct_aceita_outro_numero_de_casas():
    assert painel.pct(5, 2) == "5,00%"
    assert painel.pct(1234.5, 1) == "1.234,5%"


def test_formato_nao_depende_do_locale_do_sistema():
    # mesmo número em três funções: sempre o padrão brasileiro
    assert (painel.numero(9876.5, 1), painel.reais(9876.5), painel.pct(9876.5)) == (
        "9.876,5",
        "R$ 9.876,50",
        "9.876,5%",
    )


def test_rotulo_mes_usa_abreviacao_em_portugues_e_o_ano():
    assert painel.rotulo_mes(date(2020, 1, 15)) == "jan/2020"
    assert painel.rotulo_mes(date(2021, 12, 1)) == "dez/2021"
    assert painel.rotulo_mes(pd.Timestamp("2019-03-31")) == "mar/2019"


def test_recortar_meses_inclui_as_duas_pontas_e_nao_muda_o_resto():
    df = pd.DataFrame(
        {
            "mes": pd.to_datetime(["2020-01-01", "2020-02-01", "2020-03-01", "2020-04-01"]),
            "receita": [1, 2, 3, 4],
        }
    )
    recorte = painel.recortar_meses(df, pd.Timestamp("2020-02-01"), pd.Timestamp("2020-03-01"))
    assert recorte["receita"].tolist() == [2, 3]


def test_recortar_meses_com_intervalo_fora_dos_dados_devolve_vazio():
    df = pd.DataFrame({"mes": pd.to_datetime(["2020-01-01"]), "receita": [1]})
    recorte = painel.recortar_meses(df, pd.Timestamp("2021-01-01"), pd.Timestamp("2021-12-01"))
    assert len(recorte) == 0


# --- P1. Leitura ---------------------------------------------------------------


def test_ler_devolve_um_dataframe_por_chave_com_as_linhas_do_mart(tmp_path, monkeypatch):
    banco = tmp_path / "painel.duckdb"
    monkeypatch.setattr(painel, "BANCO", str(banco))
    gravar_marts(
        banco,
        {
            "kpis": pd.DataFrame({"ticket_medio": [10.5]}),
            "clientes_por_uf": pd.DataFrame({"uf": ["SP", "RJ"], "clientes": [3, 2]}),
        },
    )
    dados = painel.ler({"kpis": "kpis", "clientes_por_uf": "clientes_por_uf"})
    assert set(dados) == {"kpis", "clientes_por_uf"}
    assert dados["kpis"]["ticket_medio"].tolist() == [10.5]
    assert dados["clientes_por_uf"].to_dict("list") == {"uf": ["SP", "RJ"], "clientes": [3, 2]}


def test_ler_usa_o_nome_real_da_tabela_e_nao_a_chave(tmp_path, monkeypatch):
    # a chave do código difere do nome da tabela (que pode ter espaço e acento)
    banco = tmp_path / "painel.duckdb"
    monkeypatch.setattr(painel, "BANCO", str(banco))
    gravar_marts(banco, {" Ticket médio por estado": pd.DataFrame({"uf": ["SP"], "ticket_medio": [1.5]})})
    dados = painel.ler({"ticket_medio_por_estado": " Ticket médio por estado"})
    assert dados["ticket_medio_por_estado"]["uf"].tolist() == ["SP"]


def test_ler_sem_banco_levanta_banco_ausente_e_nao_cria_o_arquivo(tmp_path, monkeypatch):
    banco = tmp_path / "nao_existe.duckdb"
    monkeypatch.setattr(painel, "BANCO", str(banco))
    with pytest.raises(painel.BancoAusente):
        painel.ler({"kpis": "kpis"})
    assert not banco.exists()


def test_ler_com_mart_faltando_levanta_marts_ausentes_listando_todos(tmp_path, monkeypatch):
    banco = tmp_path / "painel.duckdb"
    monkeypatch.setattr(painel, "BANCO", str(banco))
    gravar_marts(banco, {"kpis": pd.DataFrame({"x": [1]})})
    with pytest.raises(painel.MartsAusentes) as erro:
        painel.ler({"kpis": "kpis", "a": "mart_a", "b": " mart_b"})
    assert erro.value.nomes == ["marts.mart_a", "marts.mart_b"]
    assert "marts.mart_a, marts.mart_b" in str(erro.value)


def test_ler_fecha_a_conexao_e_o_arquivo_pode_ser_regravado_em_seguida(tmp_path, monkeypatch):
    banco = tmp_path / "painel.duckdb"
    monkeypatch.setattr(painel, "BANCO", str(banco))
    gravar_marts(banco, {"kpis": pd.DataFrame({"x": [1]})})
    painel.ler({"kpis": "kpis"})
    gravar_marts(banco, {"kpis": pd.DataFrame({"x": [1, 2]})})
    assert len(painel.ler({"kpis": "kpis"})["kpis"]) == 2


# --- Gráficos: uma função por gráfico, devolve figura plotly --------------------


def pontos(fig):
    return len(fig.data[0].x)


def test_grafico_faturamento_tem_um_ponto_por_mes_e_marcadores():
    df = pd.DataFrame(
        {
            "mes": pd.to_datetime(["2020-03-01", "2020-01-01", "2020-02-01"]),
            "receita": [30.0, 10.0, 20.0],
        }
    )
    fig = painel.grafico_faturamento(df)
    assert pontos(fig) == 3
    assert fig.data[0].mode == "lines+markers"
    assert fig.layout.title.text.startswith("01")


def test_grafico_faturamento_ordena_os_meses_do_mais_antigo_para_o_mais_novo():
    df = pd.DataFrame(
        {
            "mes": pd.to_datetime(["2020-03-01", "2020-01-01", "2020-02-01"]),
            "receita": [30.0, 10.0, 20.0],
        }
    )
    fig = painel.grafico_faturamento(df)
    assert list(fig.data[0].y) == [10.0, 20.0, 30.0]


def test_grafico_categorias_tem_um_ponto_por_linha_com_o_maior_em_cima():
    df = pd.DataFrame({"categoria": ["a", "b", "c"], "receita": [5.0, 50.0, 20.0]})
    fig = painel.grafico_categorias(df)
    assert pontos(fig) == 3
    assert fig.data[0].orientation == "h"
    assert fig.data[0].y[0] == "b"
    assert fig.layout.yaxis.autorange == "reversed"
    assert fig.layout.title.text.startswith("02")


def test_grafico_categorias_mostra_so_as_dez_maiores():
    df = pd.DataFrame(
        {"categoria": [f"c{i}" for i in range(12)], "receita": [float(i) for i in range(12)]}
    )
    fig = painel.grafico_categorias(df)
    assert pontos(fig) == 10
    assert "c0" not in fig.data[0].y
    assert "c1" not in fig.data[0].y
    assert fig.data[0].y[0] == "c11"


def test_grafico_pagamento_tem_um_ponto_por_linha_com_o_maior_primeiro():
    df = pd.DataFrame({"tipo": ["boleto", "cartao", "voucher"], "pct_valor": [20.0, 70.0, 10.0]})
    fig = painel.grafico_pagamento(df)
    assert pontos(fig) == 3
    assert fig.data[0].x[0] == "cartao"
    assert fig.layout.title.text.startswith("07")
    assert fig.layout.yaxis.ticksuffix == "%"


def test_grafico_ticket_uf_tem_um_ponto_por_linha_com_o_maior_em_cima():
    df = pd.DataFrame({"uf": ["SP", "RJ", "MG", "BA"], "ticket_medio": [100.0, 300.0, 200.0, 50.0]})
    fig = painel.grafico_ticket_uf(df)
    assert pontos(fig) == 4
    assert list(fig.data[0].y) == ["RJ", "MG", "SP", "BA"]
    assert fig.layout.title.text.startswith("06")


def test_grafico_clientes_uf_tem_um_ponto_por_linha_com_o_maior_em_cima():
    df = pd.DataFrame({"uf": ["SP", "RJ"], "clientes": [4, 9]})
    fig = painel.grafico_clientes_uf(df)
    assert pontos(fig) == 2
    assert list(fig.data[0].y) == ["RJ", "SP"]
    assert fig.layout.title.text.startswith("12")


def test_grafico_nota_categoria_tem_um_ponto_por_linha_com_a_pior_em_cima():
    df = pd.DataFrame(
        {"categoria": ["x", "y", "z"], "nota_media": [4.5, 2.0, 3.0], "posicao_pior": [3, 1, 2]}
    )
    fig = painel.grafico_nota_categoria(df)
    assert pontos(fig) == 3
    assert list(fig.data[0].y) == ["y", "z", "x"]
    assert fig.layout.yaxis.autorange == "reversed"
    assert fig.layout.title.text.startswith("04")


def test_grafico_nota_categoria_mostra_so_as_dez_piores():
    df = pd.DataFrame(
        {
            "categoria": [f"c{i}" for i in range(12)],
            "nota_media": [3.0] * 12,
            "posicao_pior": list(range(1, 13)),
        }
    )
    fig = painel.grafico_nota_categoria(df)
    assert pontos(fig) == 10
    assert "c10" not in fig.data[0].y
    assert "c11" not in fig.data[0].y


def test_grafico_pareto_tem_um_ponto_por_posicao_e_linha_tracejada_em_80():
    df = pd.DataFrame({"posicao": [3, 1, 2], "pct_acumulado": [100.0, 40.0, 70.0]})
    fig = painel.grafico_pareto(df)
    assert pontos(fig) == 3
    assert list(fig.data[0].x) == [1, 2, 3]
    assert list(fig.data[0].y) == [40.0, 70.0, 100.0]
    assert len(fig.layout.shapes) == 1
    assert fig.layout.shapes[0].y0 == painel.LIMITE_PARETO == 80
    assert fig.layout.shapes[0].line.dash == "dash"
    assert fig.layout.title.text.startswith("09")


def test_todo_grafico_usa_uma_cor_so_e_separadores_brasileiros():
    df_uf = pd.DataFrame({"uf": ["SP"], "clientes": [1]})
    fig = painel.grafico_clientes_uf(df_uf)
    assert fig.data[0].marker.color == painel.COR
    assert fig.layout.separators == ",."
    assert fig.layout.showlegend is False
    assert fig.layout.height == painel.ALTURA


def test_grafico_com_dataframe_vazio_devolve_figura_sem_pontos():
    df = pd.DataFrame({"uf": pd.Series([], dtype="str"), "clientes": pd.Series([], dtype="int64")})
    fig = painel.grafico_clientes_uf(df)
    assert len(fig.data[0].x) == 0
