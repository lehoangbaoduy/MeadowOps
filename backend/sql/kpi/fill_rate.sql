-- Fill rate starter KPI (PRD Appendix A, S1-FR-3/S1-FR-11). Builder-set
-- placeholder, pending Analyst review (PRD line 207).
--
-- Simplifying assumption: proxies "met immediately from available stock
-- without backorder" as quantity_shipped / quantity_ordered across all
-- order lines - it doesn't yet join inventory_snapshot to check stock was
-- actually available at order time (no backorder detection). A real
-- fill-rate calculation needs that join; left for Unit 14.
--
-- NULLIF-guarded against an order book with zero ordered quantity.
select
    round(
        100.0 * sum(quantity_shipped) / nullif(sum(quantity_ordered), 0),
        2
    ) as fill_rate_pct
from live.sales_order_line;
