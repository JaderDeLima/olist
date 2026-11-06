-- Quanto vendemos por mÊs?
-- Grão: Um mês d compra.
select 
   date_trunc('month', p.data_compra)::date as mes,
   count(distinct p.pedido_id) as pedidos,
   sum(i.preco) as receita
from refined.pedidos as p
join refined.itens_pedido as i on i.pedido_id = p.pedido_id
where p.status not in ('canceled', 'unavailable')
group by mes
order by mes