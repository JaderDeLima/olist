"""Painel Olist - leitura, formatação e gráficos (sem streamlit).

Usado por app.py (página) e, no futuro, pelo relatório HTML. Por isso este
arquivo não importa streamlit: as mesmas funções servem aos dois.

Spec (fonte da verdade; o código é consequência dela)

P1. Leitura
    ler(marts) devolve dict chave -> DataFrame. Para cada mart, só
    SELECT * FROM marts."<nome>". Nenhuma outra SQL.
    A conexão é duckdb.connect("olist.duckdb", read_only=True), aberta e
    fechada dentro de ler(). Motivo: conexão aberta segura o arquivo, e o
    pipeline.marts não consegue gravar com o painel de pé.
    O nome do mart é o nome do arquivo em sql/marts depois do "NN_" (o prefixo
    só ordena), exatamente como o pipeline.marts o grava. Ver MARTS.

P2. Nenhum cálculo
    Proibido em painel.py e app.py: agrupar, somar, tirar média, contar, juntar
    tabelas, pivotar e qualquer conta entre colunas. Permitido: ordenar,
    filtrar linhas, head(n), renomear coluna e formatar texto.
    Motivo: número novo na tela exige um .sql novo em marts. Se faltar algum
    número, pare e diga qual mart está faltando.
    Sem exceção: o cartão de recompra, que exigia "100 - pct_clientes", não está
    no rascunho; o mart 05 continua existindo, mas a página não o lê.

P3. Layout (app.py), layout="wide" - segue design/rascunho.png
    São 12 quadros, cada um um st.container(border=True). A tela tem duas
    metades lado a lado (st.columns de 1 para 1). Título "Olist · visão da
    operação" à esquerda do cabeçalho e o botão "Recarregar dados" à direita.
    Metade esquerda, de cima para baixo:
      Linha A, dois quadros (largura 2 para 1), cada número um st.metric com o
        nome no rótulo e a definição curta em st.caption logo abaixo (a coluna
        é estreita e o rótulo do metric trunca):
        quadro largo: Ticket médio (kpis.ticket_medio, reais) e Peso do frete
          (kpis.pct_frete, 1 casa), lado a lado
        quadro pequeno: Cancelados (kpis.pct_cancelados, 2 casas)
      Linha B, duas colunas iguais:
        esquerda, quadro alto: 06 · ticket médio por UF (barras horizontais,
          maior em cima)
        direita, quadro baixo e largo: filtro de período (P5); embaixo dele,
          quadro grande: 01 · faturamento mensal (linha com marcadores)
      Linha C, dois quadros largos iguais:
        esquerdo: No prazo (entrega_no_prazo.pct_no_prazo, 1 casa) e Dias até
          entregar (kpis.dias_entrega, 1 casa), lado a lado
        direito: Nota média (kpis.nota_media, 2 casas)
    Metade direita, de cima para baixo:
      Linha D, dois quadros grandes iguais:
        02 · receita por categoria (top 10, barras horizontais, maior em cima)
        09 · concentração de vendedores (linha de pct_acumulado por posicao,
          com linha horizontal tracejada em 80)
      Linha E, três quadros altos e estreitos iguais:
        12 · clientes por UF (barras horizontais, maior em cima)
        04 · nota por categoria (as 10 primeiras por posicao_pior, pontos,
          pior em cima)
        07 · mix de pagamento (barras por pct_valor)
    Cada gráfico: título com o número do mart, uma cor só, eixo com unidade,
    width="stretch" (use_container_width está descontinuado).
    Motivo da cor única: a posição e o comprimento já dizem tudo; cor extra
    sem variável por trás é ruído.
    Marts não usados: recompra, nota_por_prazo, tempo_entrega_por_estado.

P4. Formato (funções puras, sem streamlit e sem banco)
    reais(valor, casas=2) -> "R$ 1.003.862,14"
    pct(valor, casas=1)   -> "93,2%"
    numero(valor, casas=0) -> "96.470"
    Milhar com ponto, decimal com vírgula, sempre, sem locale do sistema.
    Motivo: o resultado não pode depender da máquina de quem roda. O mesmo vale
    para os eixos dos gráficos (separators=",." do plotly e datas em %m/%Y).
    Uma função por gráfico: recebe o DataFrame e devolve a figura plotly.
    Motivo: o relatório HTML reaproveita as mesmas funções.

P5. Filtro de período
    st.select_slider com os meses de vendas_mensais, padrão jan/2017 a
    ago/2018, no quadro baixo logo acima do faturamento. Recorta só as linhas
    do gráfico de faturamento; cartões e demais gráficos não mudam, e a página
    diz isso embaixo do filtro: "os cartões valem para o período inteiro".
    Motivo: recortar linha é SELECT; recalcular cartão por período seria regra
    de negócio fora do SQL.

P6. Cache e erro
    Leitura com st.cache_data; o botão "Recarregar dados" limpa o cache.
    Sem olist.duckdb, ou faltando qualquer mart usado pela página: st.error
    dizendo quais e o comando "uv run python -m pipeline.marts", e st.stop().
    Motivo: tela quebrada sem explicação parece bug do painel, não do pipeline.
"""

from pathlib import Path

import duckdb
import plotly.express as px

BANCO = "olist.duckdb"

# chave usada no código -> nome real da tabela em marts (nome do arquivo depois
# do "NN_"). O primeiro espaço de " Ticket médio por estado" vem do arquivo
# 06_ Ticket médio por estado.sql e é mantido de propósito.
MARTS = {
    "vendas_mensais": "vendas_mensais",
    "top_categorias": "top_categorias",
    "entrega_no_prazo": "entrega_no_prazo",
    "nota_por_categoria": "nota_por_categoria",
    "ticket_medio_por_estado": " Ticket médio por estado",
    "mix_pagamento": "Mix de pagamento",
    "vendedores_pareto": "Concentração de vendedores",
    "kpis": "kpis",
    "clientes_por_uf": "clientes_por_uf",
}

COR = "#2a6f97"
ALTURA = 420
LIMITE_PARETO = 80


class BancoAusente(Exception):
    """olist.duckdb não existe."""


class MartsAusentes(Exception):
    """Algum mart usado pela página não existe; .nomes lista quais."""

    def __init__(self, nomes):
        super().__init__(", ".join(nomes))
        self.nomes = nomes


# --- 1. Leitura -------------------------------------------------------------


def ler(marts):
    """marts: dict chave -> nome da tabela. Devolve dict chave -> DataFrame."""
    if not Path(BANCO).exists():
        raise BancoAusente(BANCO)

    dados, faltando = {}, []
    con = duckdb.connect(BANCO, read_only=True)
    try:
        for chave, nome in marts.items():
            try:
                dados[chave] = con.execute(f'SELECT * FROM marts."{nome}"').df()
            except duckdb.CatalogException:
                faltando.append(f"marts.{nome.strip()}")
    finally:
        con.close()

    if faltando:
        raise MartsAusentes(faltando)
    return dados


# --- 2. Formato -------------------------------------------------------------


def numero(valor, casas=0):
    # Formata no padrão americano e troca os separadores; não usa locale.
    texto = f"{valor:,.{casas}f}"
    return texto.translate(str.maketrans(",.", ".,"))


def reais(valor, casas=2):
    return "R$ " + numero(valor, casas)


def pct(valor, casas=1):
    return numero(valor, casas) + "%"


_MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def rotulo_mes(data):
    return f"{_MESES[data.month - 1]}/{data.year}"


def recortar_meses(df, inicio, fim):
    """Filtra linhas de vendas_mensais entre dois meses, inclusive."""
    return df[(df["mes"] >= inicio) & (df["mes"] <= fim)]


# --- 3. Gráficos ------------------------------------------------------------


def _acabamento(fig, titulo, x, y, ticksuffix_y=None):
    fig.update_traces(marker_color=COR)
    fig.update_layout(
        title={"text": titulo, "font_size": 14},
        showlegend=False,
        separators=",.",
        height=ALTURA,
        margin={"l": 10, "r": 10, "t": 50, "b": 10},
    )
    fig.update_xaxes(title=x)
    fig.update_yaxes(title=y, ticksuffix=ticksuffix_y)
    return fig


def _barras_horizontais(df, rotulo, valor, titulo, titulo_x):
    # Já ordenado do maior para o menor; o eixo invertido põe o primeiro em cima.
    fig = px.bar(df, x=valor, y=rotulo, orientation="h")
    fig.update_yaxes(autorange="reversed")
    return _acabamento(fig, titulo, titulo_x, None)


def grafico_faturamento(df):
    fig = px.line(df.sort_values("mes"), x="mes", y="receita", markers=True)
    fig.update_traces(line_color=COR)
    fig.update_xaxes(tickformat="%m/%Y")
    fig = _acabamento(fig, "01 · Faturamento mensal", "Mês", "Receita (R$)")
    fig.update_yaxes(tickformat=",.0f")
    return fig


def grafico_categorias(df):
    top = df.sort_values("receita", ascending=False).head(10)
    fig = _barras_horizontais(top, "categoria", "receita", "02 · Receita por categoria (top 10)", "Receita (R$)")
    fig.update_xaxes(tickformat=",.0f")
    return fig


def grafico_pagamento(df):
    ordenado = df.sort_values("pct_valor", ascending=False)
    fig = px.bar(ordenado, x="tipo", y="pct_valor")
    return _acabamento(fig, "07 · Mix de pagamento", "Tipo de pagamento", "% do valor pago", "%")


def grafico_ticket_uf(df):
    ordenado = df.sort_values("ticket_medio", ascending=False)
    fig = _barras_horizontais(ordenado, "uf", "ticket_medio", "06 · Ticket médio por UF", "Ticket médio (R$)")
    fig.update_xaxes(tickformat=",.0f")
    return fig


def grafico_clientes_uf(df):
    ordenado = df.sort_values("clientes", ascending=False)
    fig = _barras_horizontais(ordenado, "uf", "clientes", "12 · Clientes por UF", "Clientes")
    fig.update_xaxes(tickformat=",.0f")
    return fig


def grafico_nota_categoria(df):
    piores = df.sort_values("posicao_pior").head(10)
    fig = px.scatter(piores, x="nota_media", y="categoria")
    fig.update_traces(marker_size=12)
    fig.update_yaxes(autorange="reversed")
    return _acabamento(fig, "04 · Nota por categoria (piores)", "Nota média (1 a 5)", None)


def grafico_pareto(df):
    fig = px.line(df.sort_values("posicao"), x="posicao", y="pct_acumulado")
    fig.update_traces(line_color=COR)
    fig.add_hline(
        y=LIMITE_PARETO,
        line_dash="dash",
        line_color=COR,
        annotation_text=f"{LIMITE_PARETO}%",
    )
    return _acabamento(
        fig,
        "09 · Concentração de vendedores",
        "Vendedores (do maior para o menor em receita)",
        "% acumulado da receita",
        "%",
    )
