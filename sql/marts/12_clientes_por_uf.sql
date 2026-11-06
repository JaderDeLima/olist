-- Quantos clientes tem cada estado?
-- Grão: uma UF. Cliente é a pessoa (cliente_unico_id), como no mart 05.
-- Só pedidos válidos. Quem comprou de UFs diferentes conta em cada uma.
SELECT
    c.uf,
    count(DISTINCT c.cliente_unico_id) AS clientes
FROM refined.pedidos  AS p
JOIN refined.clientes AS c ON c.cliente_id = p.cliente_id
WHERE p.status NOT IN ('canceled', 'unavailable')
GROUP BY c.uf
ORDER BY clientes DESC
