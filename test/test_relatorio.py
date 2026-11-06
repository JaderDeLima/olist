"""Testes de relatorio.py (gera relatorio.html a partir dos marts).

Banco novo em tmp_path (painel.BANCO) e saída em tmp_path (relatorio.SAIDA);
marts inventados, um por chave de painel.MARTS.
"""

import io
import re
import sys
from datetime import datetime

import duckdb
import pandas as pd
import pytest

import painel
import relatorio
from pipeline import db

MESES_PADRAO = ["2017-01-01", "2017-02-01", "2017-03-01"]


def marts_inventados(meses=MESES_PADRAO):
    return {
        "vendas_mensais": pd.DataFrame(
            {
                "mes": pd.to_datetime(meses),
                "pedidos": list(range(1, len(meses) + 1)),
                "receita": [100.0 * (i + 1) for i in range(len(meses))],
            }
        ),
        "top_categorias": pd.DataFrame({"categoria": ["a", "b"], "receita": [10.0, 20.0]}),
        "entrega_no_prazo": pd.DataFrame(
            {"entregues": [4], "no_prazo": [3], "atrasados": [1], "pct_no_prazo": [75.0]}
        ),
        "nota_por_categoria": pd.DataFrame(
            {"categoria": ["a", "b"], "nota_media": [4.0, 3.0], "posicao_pior": [2, 1]}
        ),
        "ticket_medio_por_estado": pd.DataFrame({"uf": ["SP", "RJ"], "ticket_medio": [50.0, 70.0]}),
        "mix_pagamento": pd.DataFrame({"tipo": ["cartao", "boleto"], "pct_valor": [80.0, 20.0]}),
        "vendedores_pareto": pd.DataFrame({"posicao": [1, 2], "pct_acumulado": [60.0, 100.0]}),
        "kpis": pd.DataFrame(
            {
                "ticket_medio": [1234.5],
                "pct_frete": [12.34],
                "pct_cancelados": [0.56],
                "dias_entrega": [7.8],
                "nota_media": [4.25],
            }
        ),
        "clientes_por_uf": pd.DataFrame({"uf": ["SP", "RJ"], "clientes": [5, 3]}),
    }


def preparar(tmp_path, monkeypatch, omitir=(), **trocas):
    """Cria o banco com os nove marts e aponta painel.BANCO e relatorio.SAIDA para tmp_path."""
    banco = tmp_path / "relatorio.duckdb"
    saida = tmp_path / "relatorio.html"
    dados = marts_inventados()
    dados.update(trocas)
    con = duckdb.connect(str(banco))
    try:
        db.criar_schema(con, "marts")
        for chave, df in dados.items():
            if chave not in omitir:
                db.gravar(con, df, "marts", painel.MARTS[chave])
    finally:
        con.close()
    monkeypatch.setattr(painel, "BANCO", str(banco))
    monkeypatch.setattr(relatorio, "SAIDA", saida)
    return banco, saida


def capturar_saida(monkeypatch):
    buf = io.BytesIO()
    texto = io.TextIOWrapper(buf, encoding="utf-8", newline="\n", write_through=True)
    monkeypatch.setattr(sys, "stdout", texto)
    return lambda: buf.getvalue().decode("utf-8")


class RelogioFalso:
    """Substitui datetime em relatorio: now() devolve, em ordem, os instantes dados."""

    def __init__(self, *instantes):
        self.instantes = list(instantes)

    def now(self):
        return self.instantes.pop(0)


# --- pedaços de HTML -----------------------------------------------------------


def test_cartao_escapa_html_no_nome_no_valor_e_na_definicao():
    html = relatorio.cartao(("a<b", "x&y", "<i>"))
    assert "a&lt;b" in html
    assert "x&amp;y" in html
    assert "&lt;i&gt;" in html
    assert "<i>" not in html


def test_cartao_mostra_todas_as_metricas_lado_a_lado():
    html = relatorio.cartao(("N1", "V1", "D1"), ("N2", "V2", "D2"))
    assert html.count('class="nome"') == 2
    assert html.index("N1") < html.index("N2")


def test_faixa_poe_as_colunas_e_junta_os_quadros_na_ordem():
    html = relatorio.faixa("2fr 1fr", "<p>um</p>", "<p>dois</p>")
    assert "grid-template-columns:2fr 1fr" in html
    assert html.index("um") < html.index("dois")


def test_graficos_numera_na_ordem_e_so_o_primeiro_carrega_o_plotly():
    g = relatorio.Graficos()
    df = pd.DataFrame({"uf": ["SP"], "clientes": [1]})
    primeiro = g(painel.grafico_clientes_uf(df), 300)
    segundo = g(painel.grafico_clientes_uf(df), 300)
    assert 'id="g01"' in primeiro
    assert 'id="g02"' in segundo
    assert "cdn.plot.ly" in primeiro
    assert "cdn.plot.ly" not in segundo


# --- main: geração do arquivo --------------------------------------------------


def test_gera_o_arquivo_dentro_de_tmp_path(tmp_path, monkeypatch):
    _, saida = preparar(tmp_path, monkeypatch)
    capturar_saida(monkeypatch)
    relatorio.main()
    assert saida.is_file()
    assert saida.parent == tmp_path
    html = saida.read_text(encoding="utf-8")
    assert html.startswith("<!doctype html>")
    assert "Olist · visão da operação" in html


def test_informa_o_caminho_do_arquivo_gerado(tmp_path, monkeypatch):
    _, saida = preparar(tmp_path, monkeypatch)
    texto = capturar_saida(monkeypatch)
    relatorio.main()
    assert str(saida.resolve()) in texto()
    assert "KB" in texto()


def test_cartoes_mostram_os_numeros_dos_marts_formatados(tmp_path, monkeypatch):
    # kpis e entrega_no_prazo inventados: 1234,5 / 12,34 / 0,56 / 7,8 / 4,25 / 75,0
    _, saida = preparar(tmp_path, monkeypatch)
    capturar_saida(monkeypatch)
    relatorio.main()
    html = saida.read_text(encoding="utf-8")
    assert "R$ 1.234,50" in html
    assert "12,3%" in html
    assert "0,56%" in html
    assert "7,8" in html
    assert "4,25" in html
    assert "75,0%" in html


def test_pagina_tem_os_sete_graficos_em_ids_fixos(tmp_path, monkeypatch):
    _, saida = preparar(tmp_path, monkeypatch)
    capturar_saida(monkeypatch)
    relatorio.main()
    html = saida.read_text(encoding="utf-8")
    ids = re.findall(r'<div id="(g\d\d)"', html)
    assert ids == [f"g{i:02d}" for i in range(1, 8)]


def test_pagina_diz_que_os_cartoes_valem_para_o_periodo_inteiro(tmp_path, monkeypatch):
    _, saida = preparar(tmp_path, monkeypatch)
    capturar_saida(monkeypatch)
    relatorio.main()
    assert "Os cartões valem para o período inteiro." in saida.read_text(encoding="utf-8")


def test_periodo_sem_jan_2017_e_ago_2018_usa_as_pontas_dos_dados(tmp_path, monkeypatch):
    # meses inventados jan/mar/mai de 2017: ago/2018 não existe, então o fim é a última ponta
    _, saida = preparar(
        tmp_path,
        monkeypatch,
        vendas_mensais=marts_inventados(["2017-05-01", "2017-01-01", "2017-03-01"])["vendas_mensais"],
    )
    capturar_saida(monkeypatch)
    relatorio.main()
    html = saida.read_text(encoding="utf-8")
    assert "Período do faturamento: jan/2017 a mai/2017." in html
    # no JSON o plotly escreve a barra como o texto \u002f
    assert re.search(r"Faturamento mensal \(jan(/|\\u002f)2017 a mai(/|\\u002f)2017\)", html)


def test_periodo_fora_de_2017_e_2018_usa_primeiro_e_ultimo_mes(tmp_path, monkeypatch):
    _, saida = preparar(
        tmp_path,
        monkeypatch,
        vendas_mensais=marts_inventados(["2020-07-01", "2020-08-01", "2020-09-01"])["vendas_mensais"],
    )
    capturar_saida(monkeypatch)
    relatorio.main()
    assert "Período do faturamento: jul/2020 a set/2020." in saida.read_text(encoding="utf-8")


def test_periodo_padrao_recorta_o_faturamento_entre_jan_2017_e_ago_2018(tmp_path, monkeypatch):
    # dez/2016 e set/2018 existem nos dados mas ficam fora do recorte padrão
    meses = ["2016-12-01", "2017-01-01", "2018-08-01", "2018-09-01"]
    _, saida = preparar(
        tmp_path, monkeypatch, vendas_mensais=marts_inventados(meses)["vendas_mensais"]
    )
    capturar_saida(monkeypatch)
    relatorio.main()
    html = saida.read_text(encoding="utf-8")
    assert "Período do faturamento: jan/2017 a ago/2018." in html
    assert "2017-01-01T00:00:00" in html
    assert "2018-08-01T00:00:00" in html
    assert "2016-12-01T00:00:00" not in html
    assert "2018-09-01T00:00:00" not in html


# --- main: rodar duas vezes ----------------------------------------------------


def rodape_neutro(html):
    return re.sub(r"<footer>.*?</footer>", "<footer></footer>", html, flags=re.DOTALL)


def test_rodar_duas_vezes_muda_so_o_rodape(tmp_path, monkeypatch):
    _, saida = preparar(tmp_path, monkeypatch)
    capturar_saida(monkeypatch)
    monkeypatch.setattr(
        relatorio,
        "datetime",
        RelogioFalso(datetime(2020, 1, 2, 10, 30), datetime(2020, 1, 2, 11, 45)),
    )
    relatorio.main()
    primeiro = saida.read_text(encoding="utf-8")
    relatorio.main()
    segundo = saida.read_text(encoding="utf-8")
    assert primeiro != segundo
    assert "Dados de 02/01/2020 10:30" in primeiro
    assert "Dados de 02/01/2020 11:45" in segundo
    assert rodape_neutro(primeiro) == rodape_neutro(segundo)


def test_segunda_execucao_sobrescreve_o_arquivo_em_vez_de_acrescentar(tmp_path, monkeypatch):
    _, saida = preparar(tmp_path, monkeypatch)
    capturar_saida(monkeypatch)
    relatorio.main()
    tamanho = saida.stat().st_size
    relatorio.main()
    assert saida.stat().st_size == tamanho
    assert saida.read_text(encoding="utf-8").count("<!doctype html>") == 1


# --- main: erros ---------------------------------------------------------------


def test_sem_banco_encerra_dizendo_qual_arquivo_e_o_comando(tmp_path, monkeypatch):
    saida = tmp_path / "relatorio.html"
    monkeypatch.setattr(painel, "BANCO", str(tmp_path / "nao_existe.duckdb"))
    monkeypatch.setattr(relatorio, "SAIDA", saida)
    capturar_saida(monkeypatch)
    with pytest.raises(SystemExit) as erro:
        relatorio.main()
    assert "nao_existe.duckdb" in str(erro.value.code)
    assert relatorio.COMANDO in str(erro.value.code)
    assert not saida.exists()


def test_mart_faltando_encerra_listando_quais_faltam_e_nao_gera_arquivo(tmp_path, monkeypatch):
    _, saida = preparar(tmp_path, monkeypatch, omitir=("kpis", "mix_pagamento"))
    capturar_saida(monkeypatch)
    with pytest.raises(SystemExit) as erro:
        relatorio.main()
    mensagem = str(erro.value.code)
    assert "marts.kpis" in mensagem
    assert "marts." + painel.MARTS["mix_pagamento"] in mensagem
    assert relatorio.COMANDO in mensagem
    assert not saida.exists()
