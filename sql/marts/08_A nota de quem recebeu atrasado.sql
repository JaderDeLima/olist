-- A nota de quem recebeu atrasado: o atraso derruba a nota?
-- Grão: situação da entrega (no_prazo ou atrasado), duas linhas.
-- Denominador: igual ao mart 03 (delivered com data de entrega).
-- Chegar no dia previsto é no prazo. Cada pedido conta uma vez,
-- com a média das suas avaliações (mart 04).
WITH nota_pedido AS (
    SELECT pedido_id, avg(nota) AS nota
    FROM refined.avaliacoes
    GROUP BY pedido_id
),
entregas AS (
    SELECT
        pedido_id,
        CASE
            WHEN data_entrega::DATE <= data_entrega_prevista THEN 'no_prazo'
            ELSE 'atrasado'
        END AS situacao
    FROM refined.pedidos
    WHERE status = 'delivered'
      AND data_entrega IS NOT NULL
)
SELECT
    e.situacao,
    count(*)                                              AS pedidos_avaliados,
    round(avg(n.nota), 2)                                 AS nota_media,
    round(100.0 * sum(CASE WHEN n.nota <= 2 THEN 1 ELSE 0 END)
          / count(*), 1)                                  AS pct_nota_baixa
FROM entregas   AS e
JOIN nota_pedido AS n ON n.pedido_id = e.pedido_id
GROUP BY e.situacao
ORDER BY e.situacao DESC
