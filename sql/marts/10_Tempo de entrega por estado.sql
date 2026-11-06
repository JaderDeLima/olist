-- Qual o tempo de entrega por estado?
-- Grão final: uma UF do cliente.
-- Tempo = dias de calendário da compra até a entrega ao cliente (não da data de envio).
-- Denominador: delivered com data de entrega (o mesmo do mart 03).
SELECT
    c.uf,
    count(*)                                                   AS entregues,
    round(avg(date_diff('day', p.data_compra, p.data_entrega)), 1) AS dias_medio,
    median(date_diff('day', p.data_compra, p.data_entrega))    AS dias_mediana
FROM refined.pedidos  AS p
JOIN refined.clientes AS c ON c.cliente_id = p.cliente_id
WHERE p.status = 'delivered'
  AND p.data_entrega IS NOT NULL
GROUP BY c.uf
ORDER BY dias_medio
