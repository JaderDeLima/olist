-- 07_mix_pagamento.sql
-- Quanto do dinheiro pago entra por cartão, boleto, voucher e débito?
-- Grão final: um tipo de pagamento.
-- Só pedidos válidos (status fora de 'canceled' e 'unavailable').
--
-- Grão de origem: refined.pagamentos tem PK (pedido_id, pagamento_seq).
-- Um pedido pago com dois vouchers e um cartão tem 3 linhas.
-- Por isso:
--   * pagamentos = count(*)                  -> linhas de pagamento (parcelas/meios usados)
--   * pedidos    = count(distinct pedido_id) -> pedidos distintos que usaram o tipo
--
-- Por que a soma de valor (R$ 15.739.137,01) é MAIOR que a receita do mart 01?
--   O mart 01 soma só itens_pedido.preco (produtos). O valor pago inclui também
--   frete, e os juros de parcelamento no cartão. Pagamento = preço + frete + juros.
--
-- Por que a soma de pedidos passa de 98.206 pedidos válidos com pagamento?
--   Um pedido pode usar mais de um tipo (ex.: voucher + cartão). Ele é contado
--   uma vez em cada tipo, então a soma da coluna pedidos conta o mesmo pedido
--   várias vezes. Dentro de cada tipo não há duplicidade (count distinct).
--   Não some a coluna pedidos: ela não é aditiva entre os tipos.
SELECT
    pg.tipo,
    count(*)                                            AS pagamentos,
    count(DISTINCT pg.pedido_id)                        AS pedidos,
    round(sum(pg.valor), 2)                             AS valor,
    -- % do valor total (janela sobre o resultado já agrupado), uma casa.
    round(100.0 * sum(pg.valor) / sum(sum(pg.valor)) OVER (), 1) AS pct_valor
FROM refined.pagamentos AS pg
JOIN refined.pedidos    AS p ON p.pedido_id = pg.pedido_id
WHERE p.status NOT IN ('canceled', 'unavailable')
GROUP BY pg.tipo
ORDER BY valor DESC
