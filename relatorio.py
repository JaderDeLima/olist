"""Relatório HTML do painel Olist. Executar com:  uv run python relatorio.py

Gera relatorio.html (arquivo único) com as mesmas faixas do app.py, na mesma
ordem. Lê, formata e desenha só com painel.py; não importa streamlit.
O arquivo não fala com o banco: o rodapé diz de quando são os dados.
"""

import sys
from datetime import datetime
from html import escape
from pathlib import Path

import painel

COMANDO = "uv run python -m pipeline.marts"
SAIDA = Path("relatorio.html")

# Alturas iguais às do app.py, para o mesmo desenho.
ALT = {"ticket_uf": 400, "faturamento": 250, "categorias": 330, "pareto": 330, "terceiro": 360}

CSS = """
body{font-family:system-ui,Segoe UI,Arial,sans-serif;margin:0;padding:16px 24px;background:#f6f7f9;color:#1f2933}
h1{font-size:1.6rem;margin:0 0 16px}
.metades{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.faixa{display:grid;gap:12px;margin-bottom:12px}
.quadro{background:#fff;border:1px solid #d9dde3;border-radius:8px;padding:8px 12px;min-width:0}
.cartao{display:flex;gap:16px;padding:12px 16px}
.cartao div{flex:1}
.nome{font-size:.85rem;color:#52606d}
.valor{font-size:1.8rem;font-weight:600}
.def{font-size:.75rem;color:#7b8794}
.nota{font-size:.8rem;color:#7b8794;margin:4px 0}
footer{margin-top:16px;font-size:.8rem;color:#7b8794}
@media(max-width:900px){.metades{grid-template-columns:1fr}}
"""


def cartao(*metricas):
    itens = "".join(
        f'<div><div class="nome">{escape(n)}</div><div class="valor">{escape(v)}</div>'
        f'<div class="def">{escape(d)}</div></div>'
        for n, v, d in metricas
    )
    return f'<div class="quadro cartao">{itens}</div>'


class Graficos:
    """Numera os gráficos (g01, g02...); só o primeiro carrega o plotly do CDN."""

    def __init__(self):
        self.n = 0

    def __call__(self, figura, altura):
        self.n += 1
        html = figura.update_layout(height=altura).to_html(
            full_html=False,
            include_plotlyjs="cdn" if self.n == 1 else False,
            div_id=f"g{self.n:02d}",
        )
        return f'<div class="quadro">{html}</div>'


def faixa(colunas, *quadros):
    return f'<div class="faixa" style="grid-template-columns:{colunas}">{"".join(quadros)}</div>'


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        d = painel.ler(painel.MARTS)
    except painel.BancoAusente:
        sys.exit(f"Não encontrei {painel.BANCO}. Rode: {COMANDO}")
    except painel.MartsAusentes as e:
        sys.exit(f"Faltam marts: {', '.join(e.nomes)}. Rode: {COMANDO}")

    kpis = d["kpis"].iloc[0]
    prazo = d["entrega_no_prazo"].iloc[0]
    g = Graficos()

    # Período padrão do app.py: jan/2017 a ago/2018, ou as pontas se faltarem.
    meses = d["vendas_mensais"].sort_values("mes")["mes"].tolist()
    rotulos = [painel.rotulo_mes(m) for m in meses]
    inicio = "jan/2017" if "jan/2017" in rotulos else rotulos[0]
    fim = "ago/2018" if "ago/2018" in rotulos else rotulos[-1]
    recorte = painel.recortar_meses(
        d["vendas_mensais"], meses[rotulos.index(inicio)], meses[rotulos.index(fim)]
    )
    fig_fat = painel.grafico_faturamento(recorte)
    fig_fat.update_layout(title={"text": f"01 · Faturamento mensal ({inicio} a {fim})"})

    # Ordem de desenho = ordem de numeração dos ids (g01...), fixa entre execuções.
    esquerda = [
        # Linha A
        faixa(
            "2fr 1fr",
            cartao(
                ("Ticket médio", painel.reais(kpis["ticket_medio"]), "receita por pedido"),
                ("Peso do frete", painel.pct(kpis["pct_frete"], 1), "frete no total pago"),
            ),
            cartao(("Cancelados", painel.pct(kpis["pct_cancelados"], 2), "% de todos os pedidos")),
        ),
        # Linha B
        faixa(
            "1fr 1fr",
            g(painel.grafico_ticket_uf(d["ticket_medio_por_estado"]), ALT["ticket_uf"]),
            g(fig_fat, ALT["faturamento"])
            + f'<p class="nota">Período do faturamento: {inicio} a {fim}. '
            "Os cartões valem para o período inteiro.</p>",
        ),
        # Linha C
        faixa(
            "1fr 1fr",
            cartao(
                ("No prazo", painel.pct(prazo["pct_no_prazo"], 1), "% das entregas"),
                ("Dias até entregar", painel.numero(kpis["dias_entrega"], 1), "média da compra à entrega"),
            ),
            cartao(("Nota média", painel.numero(kpis["nota_media"], 2), "avaliações de 1 a 5")),
        ),
    ]
    direita = [
        # Linha D
        faixa(
            "1fr 1fr",
            g(painel.grafico_categorias(d["top_categorias"]), ALT["categorias"]),
            g(painel.grafico_pareto(d["vendedores_pareto"]), ALT["pareto"]),
        ),
        # Linha E
        faixa(
            "1fr 1fr 1fr",
            g(painel.grafico_clientes_uf(d["clientes_por_uf"]), ALT["terceiro"]),
            g(painel.grafico_nota_categoria(d["nota_por_categoria"]), ALT["terceiro"]),
            g(painel.grafico_pagamento(d["mix_pagamento"]), ALT["terceiro"]),
        ),
    ]

    gerado = datetime.now().strftime("%d/%m/%Y %H:%M")
    pagina = f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Olist · visão da operação</title>
<style>{CSS}</style>
</head>
<body>
<h1>Olist · visão da operação</h1>
<div class="metades">
<section>{"".join(esquerda)}</section>
<section>{"".join(direita)}</section>
</div>
<footer>Dados de {gerado}</footer>
</body>
</html>
"""
    SAIDA.write_text(pagina, encoding="utf-8")
    print(f"{SAIDA.resolve()}  ({SAIDA.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
