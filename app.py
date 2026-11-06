"""Página do painel Olist. Executar com:  uv run streamlit run app.py

A spec (inclusive o layout, que segue design/rascunho.png) está na docstring de
painel.py. Aqui só se desenha a página.
"""

import streamlit as st

import painel

st.set_page_config(page_title="Olist · visão da operação", layout="wide")

COMANDO = "uv run python -m pipeline.marts"
ALTURA_CARTAO = 150
ALTURA_FILTRO = 130


@st.cache_data
def carregar():
    return painel.ler(painel.MARTS)


def botao_recarregar():
    if st.button("Recarregar dados"):
        st.cache_data.clear()
        st.rerun()


def cartao(coluna, *metricas):
    """Um quadro com um ou mais números (nome, valor, definição) lado a lado."""
    with coluna.container(border=True, height=ALTURA_CARTAO):
        lugares = st.columns(len(metricas)) if len(metricas) > 1 else [st.container()]
        for lugar, (nome, valor, definicao) in zip(lugares, metricas):
            lugar.metric(nome, valor)
            lugar.caption(definicao)


def quadro(coluna, figura, altura):
    # A altura do gráfico é escolhida aqui para que as duas metades fechem
    # alinhadas, como no rascunho.
    with coluna.container(border=True):
        st.plotly_chart(figura.update_layout(height=altura), width="stretch")


try:
    d = carregar()
except painel.BancoAusente:
    st.error(f"Não encontrei {painel.BANCO}. Rode: {COMANDO}")
    botao_recarregar()
    st.stop()
except painel.MartsAusentes as e:
    st.error(f"Faltam marts: {', '.join(e.nomes)}. Rode: {COMANDO}")
    botao_recarregar()
    st.stop()

# --- Cabeçalho --------------------------------------------------------------

titulo, recarregar = st.columns([5, 1], vertical_alignment="center")
titulo.title("Olist · visão da operação")
with recarregar:
    botao_recarregar()

kpis = d["kpis"].iloc[0]
prazo = d["entrega_no_prazo"].iloc[0]

esquerda, direita = st.columns(2)

# --- Metade esquerda --------------------------------------------------------

with esquerda:
    # Linha A
    a_largo, a_pequeno = st.columns([2, 1])
    cartao(
        a_largo,
        ("Ticket médio", painel.reais(kpis["ticket_medio"]), "receita por pedido"),
        ("Peso do frete", painel.pct(kpis["pct_frete"], 1), "frete no total pago"),
    )
    cartao(a_pequeno, ("Cancelados", painel.pct(kpis["pct_cancelados"], 2), "% de todos os pedidos"))

    # Linha B
    alto, centro = st.columns(2)
    quadro(alto, painel.grafico_ticket_uf(d["ticket_medio_por_estado"]), 400)

    meses = d["vendas_mensais"].sort_values("mes")["mes"].tolist()
    rotulos = [painel.rotulo_mes(m) for m in meses]
    # Se jan/2017 ou ago/2018 não estiverem no mart, cai para as pontas.
    padrao = ("jan/2017" if "jan/2017" in rotulos else rotulos[0],
              "ago/2018" if "ago/2018" in rotulos else rotulos[-1])
    with centro:
        with st.container(border=True, height=ALTURA_FILTRO):
            inicio, fim = st.select_slider("Período do faturamento", options=rotulos, value=padrao)
            st.caption("os cartões valem para o período inteiro")
        recorte = painel.recortar_meses(
            d["vendas_mensais"], meses[rotulos.index(inicio)], meses[rotulos.index(fim)]
        )
        quadro(st.container(), painel.grafico_faturamento(recorte), 250)

    # Linha C
    c_esq, c_dir = st.columns(2)
    cartao(
        c_esq,
        ("No prazo", painel.pct(prazo["pct_no_prazo"], 1), "% das entregas"),
        ("Dias até entregar", painel.numero(kpis["dias_entrega"], 1), "média da compra à entrega"),
    )
    cartao(c_dir, ("Nota média", painel.numero(kpis["nota_media"], 2), "avaliações de 1 a 5"))

# --- Metade direita ---------------------------------------------------------

with direita:
    # Linha D
    d1, d2 = st.columns(2)
    quadro(d1, painel.grafico_categorias(d["top_categorias"]), 330)
    quadro(d2, painel.grafico_pareto(d["vendedores_pareto"]), 330)

    # Linha E
    e1, e2, e3 = st.columns(3)
    quadro(e1, painel.grafico_clientes_uf(d["clientes_por_uf"]), 360)
    quadro(e2, painel.grafico_nota_categoria(d["nota_por_categoria"]), 360)
    quadro(e3, painel.grafico_pagamento(d["mix_pagamento"]), 360)
