-- Perfect order rate starter KPI (PRD Appendix A, S1-FR-3). Builder-set
-- placeholder, pending Analyst review.
--
-- Honest gap, not hidden: PRD Appendix A defines this as OTIF plus "no
-- defined process/fulfillment errors," but no process-error concept
-- (wrong-item, damaged, invoice-error, etc.) exists anywhere in the current
-- schema - there is nothing to distinguish it from OTIF yet. This starter
-- query is therefore identical to otif.sql's computation, not a distinct
-- metric, until a later unit models a real error signal to subtract from
-- it. Kept as its own file (not just reusing otif.sql) so the Analyst
-- reviewing S1-FR-11 sees this gap explicitly, in the place PRD Appendix A
-- itself calls out as a separate KPI, rather than it hiding as a comment
-- inside otif.sql.
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
    ) as perfect_order_rate_pct
from order_fulfillment;
