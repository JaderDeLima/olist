-- Que fração dos vendedores faz 80% da receita?
-- Grão: um vendedor com venda válida, do maior para o menor em receita.
-- Venda válida: mesmo filtro do mart 01 (status fora de canceled e unavailable),
-- então a soma de receita bate com a do mart 01.
WITH receita_vendedor AS (
    SELECT
        i.vendedor_id,
        sum(i.preco) AS receita
    FROM refined.pedidos       AS p
    JOIN refined.itens_pedido  AS i ON i.pedido_id = p.pedido_id
    WHERE p.status NOT IN ('canceled', 'unavailable')
    GROUP BY i.vendedor_id
),
ranking AS (
    SELECT
        r.vendedor_id,
        v.uf,
        r.receita,
        -- vendedor_id desempata receitas idênticas: ordem fixa e acumulado único
        row_number() OVER (ORDER BY r.receita DESC, r.vendedor_id) AS posicao,
        sum(r.receita) OVER (ORDER BY r.receita DESC, r.vendedor_id) AS receita_acumulada,
        sum(r.receita) OVER ()                                       AS receita_total
    FROM receita_vendedor  AS r
    JOIN refined.vendedores AS v ON v.vendedor_id = r.vendedor_id
)
SELECT
    vendedor_id,
    uf,
    receita,
    posicao,
    round(100.0 * receita_acumulada / receita_total, 2) AS pct_acumulado
FROM ranking
ORDER BY posicao
