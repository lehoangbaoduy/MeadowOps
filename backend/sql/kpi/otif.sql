-- OTIF (on-time, in-full) starter KPI (PRD Appendix A, S1-FR-3/S1-FR-11).
-- Builder-set placeholder, pending Analyst review (PRD line 207) - not
-- treated as final.
--
-- Qualifying orders = sales orders with at least one shipment. "In full" =
-- every line on the order shipped at least the ordered quantity. "On time"
-- = at least one of the order's shipments was delivered on or before its
-- promised delivery date.
--
-- Simplifying assumption (documented, not hidden): treats each sales order
-- as having a single delivery event. An order split across multiple
-- shipments is a real scenario this schema supports but this starter query
-- doesn't yet disambiguate per-shipment - left for Unit 14's real KPI
-- engine.
--
-- NULLIF-guarded: with no delivered shipments (true of the seeded baseline
-- data before Unit 13's order flow runs), this returns NULL - "no data
-- yet" - never a divide-by-zero error.
with order_fulfillment as (
    select
        so.id as sales_order_id,
        bool_and(sol.quantity_shipped >= sol.quantity_ordered) as is_in_full,
        bool_or(
            s.actual_delivery_date is not null
            and s.actual_delivery_date <= s.promised_delivery_date
        ) as is_on_time,
        bool_or(s.status = 'delivered') as is_delivered
    from live.sales_order so
    join live.sales_order_line sol on sol.sales_order_id = so.id
    left join live.shipment s on s.sales_order_id = so.id
    group by so.id
)
select
    round(
        100.0 * count(*) filter (where is_delivered and is_in_full and is_on_time)
        / nullif(count(*) filter (where is_delivered), 0),
        2
    ) as otif_pct
from order_fulfillment;
