-- Qual o ticket médio por estado?
-- Grão final: uma UF.
-- Ticket médio = receita do pedido (somada primeiro) e depois a média por pedido.
-- Só pedidos válidos.
WITH receita_por_pedido AS (
    -- Grão: um pedido (item -> pedido).
    SELECT
        p.pedido_id,
        p.cliente_id,
        sum(i.preco) AS receita
    FROM refined.pedidos      AS p
    JOIN refined.itens_pedido AS i ON i.pedido_id = p.pedido_id
    WHERE p.status NOT IN ('canceled', 'unavailable')
    GROUP BY p.pedido_id, p.cliente_id
)
-- Grão: uma UF (pedido -> UF).
SELECT
    c.uf,
    count(*)                    AS pedidos,
    round(avg(r.receita), 2)    AS ticket_medio
FROM receita_por_pedido AS r
JOIN refined.clientes   AS c ON c.cliente_id = r.cliente_id
GROUP BY c.uf
ORDER BY ticket_medio DESC
