-- Days of supply starter KPI (PRD Appendix A, S1-FR-3/S1-FR-11), per
-- product/warehouse. Builder-set placeholder, pending Analyst review.
--
-- Usable inventory (latest snapshot's on-hand minus allocated) divided by
-- average daily shipment quantity over the trailing 30 simulated days.
-- Reads live.simulation_clock.simulation_date, never CURRENT_DATE/now() -
-- this is simulated time, and a query keyed to wall-clock time would be a
-- bug the moment the simulation date diverges from the real date (Unit 4
-- renamed the column for exactly this reason).
--
-- The window has both a lower AND an upper bound tied to simulation_date
-- (security review, Unit 10): a lower bound alone silently extends to
-- include everything up to "now" in the table once simulation_date falls
-- behind wall-clock time (the normal Active-Use state once Unit 13 starts
-- advancing the clock) or a future-dated transaction exists - not a crash,
-- a silently wrong number.
--
-- Degrades gracefully rather than erroring: a product/warehouse with a
-- snapshot but zero shipment activity in the window returns NULL days of
-- supply (undefined, not infinite or a divide-by-zero error) via the
-- NULLIF on the usage denominator. With no simulation_clock row at all
-- (true before Unit 4/13's clock is seeded), the `clock` CTE has zero rows,
-- so `avg_daily_usage`'s cross join with it also has zero rows - every
-- product/warehouse's days_of_supply is NULL rather than the query
-- erroring or silently using the real wall-clock date instead.
with clock as (
    select simulation_date from live.simulation_clock limit 1
),
latest_snapshot as (
    select distinct on (product_id, warehouse_id)
        product_id, warehouse_id, quantity_on_hand - quantity_allocated as usable_qty
    from live.inventory_snapshot
    order by product_id, warehouse_id, snapshot_date desc
),
avg_daily_usage as (
    select
        it.product_id, it.warehouse_id,
        abs(sum(it.quantity_delta)) / 30.0 as avg_daily_qty
    from live.inventory_transaction it, clock
    where it.transaction_type = 'shipment'
      and it.transaction_at >= clock.simulation_date - interval '30 days'
      and it.transaction_at < clock.simulation_date + interval '1 day'
    group by it.product_id, it.warehouse_id
)
select
    ls.product_id,
    ls.warehouse_id,
    round(ls.usable_qty / nullif(adu.avg_daily_qty, 0), 1) as days_of_supply
from latest_snapshot ls
left join avg_daily_usage adu using (product_id, warehouse_id);
