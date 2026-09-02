-- Order cycle time starter KPI (PRD Appendix A, S1-FR-3). Builder-set
-- placeholder, pending Analyst review.
--
-- Average elapsed days from order placement to actual delivery, across
-- delivered shipments. Pure historical duration between two already-stored
-- dates - no wall-clock/simulation-clock reference needed.
--
-- avg() over zero matching rows already returns NULL, not an error, so no
-- explicit NULLIF is needed - but the same "no data yet" outcome applies
-- before Unit 13 populates real order/shipment history.
select
    round(avg(s.actual_delivery_date - so.order_date), 1) as avg_order_cycle_time_days
from live.sales_order so
join live.shipment s on s.sales_order_id = so.id
where s.status = 'delivered'
  and s.actual_delivery_date is not null;
