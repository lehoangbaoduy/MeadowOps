/**
 * Unit 16 (MEADOWOPS-API-003): hand-declared response types for the
 * dashboard API — same convention (and the same MEDIUM-flagged drift risk,
 * Unit 12c's code review) as CustomerRow: these can silently drift from
 * app/schemas/dashboard.py on a field rename with no compile-time signal.
 * Kept in one file since every dashboard page/table shares this shape
 * vocabulary, unlike master-data's four independent entities.
 */

export type ExecutiveKpi = {
  simulation_date: string;
  otif_pct: string | null;
  fill_rate_pct: string | null;
  order_cycle_time_days: string | null;
  perfect_order_rate_pct: string | null;
  computed_at: string;
};

export type ExceptionCountByCategory = {
  category: string;
  open_count: number;
};

export type ExecutiveSummary = {
  kpis: ExecutiveKpi | null;
  open_exception_counts: ExceptionCountByCategory[];
};

export type InventoryPosition = {
  product_id: string;
  warehouse_id: string;
  quantity_on_hand: number | null;
  quantity_allocated: number | null;
  days_of_supply: string | null;
  is_low_stock: boolean;
};

export type InventoryTransaction = {
  id: string;
  transaction_at: string;
  transaction_type: string;
  quantity_delta: number;
  reference_type: string | null;
  reference_id: string | null;
  source_system: string;
};

export type SupplierPerformance = {
  supplier_id: string;
  supplier_name: string;
  total_purchase_order_count: number;
  open_purchase_order_count: number;
  at_risk_purchase_order_count: number;
};

export type PurchaseOrderStatus =
  | "draft"
  | "submitted"
  | "confirmed"
  | "partially_received"
  | "received"
  | "cancelled";

export type PurchaseOrderSummary = {
  id: string;
  po_number: string;
  supplier_id: string;
  warehouse_id: string;
  order_date: string;
  expected_delivery_date: string;
  status: PurchaseOrderStatus;
  is_at_risk: boolean;
};

export type PurchaseOrderLine = {
  id: string;
  product_id: string;
  quantity_ordered: number;
  quantity_received: number;
  unit_cost: string;
};

export type PurchaseOrderLifecycleEvent = {
  from_status: PurchaseOrderStatus | null;
  to_status: PurchaseOrderStatus;
  occurred_at: string;
  simulation_date: string;
};

export type PurchaseOrderDetail = PurchaseOrderSummary & {
  lines: PurchaseOrderLine[];
  lifecycle_events: PurchaseOrderLifecycleEvent[];
};

export type SalesOrderStatus =
  | "draft"
  | "submitted"
  | "allocated"
  | "partially_shipped"
  | "shipped"
  | "cancelled";

export type SalesOrderSummary = {
  id: string;
  so_number: string;
  customer_id: string;
  warehouse_id: string;
  order_date: string;
  requested_date: string;
  promised_date: string | null;
  status: SalesOrderStatus;
};

export type SalesOrderLine = {
  id: string;
  product_id: string;
  quantity_ordered: number;
  quantity_shipped: number;
  unit_price: string;
};

export type SalesOrderLifecycleEvent = {
  from_status: SalesOrderStatus | null;
  to_status: SalesOrderStatus;
  occurred_at: string;
  simulation_date: string;
};

export type ShipmentStatus = "pending" | "in_transit" | "delivered" | "exception";

export type Shipment = {
  id: string;
  sales_order_id: string;
  carrier_id: string;
  warehouse_id: string;
  ship_date: string;
  promised_delivery_date: string;
  actual_delivery_date: string | null;
  status: ShipmentStatus;
  is_late: boolean;
};

export type SalesOrderDetail = SalesOrderSummary & {
  lines: SalesOrderLine[];
  lifecycle_events: SalesOrderLifecycleEvent[];
  shipments: Shipment[];
};

export type ExceptionFlag = {
  id: string;
  category: string;
  product_id: string | null;
  warehouse_id: string | null;
  purchase_order_id: string | null;
  shipment_id: string | null;
  simulation_date: string;
  first_detected_simulation_date: string;
  measured_value: string | null;
  threshold_value: string;
  detected_at: string;
  resolved_at: string | null;
};

export type ExceptionDrilldown = {
  flag: ExceptionFlag;
  purchase_order: PurchaseOrderSummary | null;
  shipment: Shipment | null;
  inventory: InventoryPosition | null;
};

export const EXCEPTION_CATEGORY_LABEL: Record<string, string> = {
  low_stock_days_of_supply: "Low stock",
  at_risk_po_grace_days: "At-risk PO",
  late_shipment_grace_days: "Late shipment",
};
