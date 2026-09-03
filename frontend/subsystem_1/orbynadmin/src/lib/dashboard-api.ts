import { cookies } from "next/headers";

import { SESSION_COOKIE } from "@/lib/session";

/**
 * Unit 16 (MEADOWOPS-API-003): server-side proxy for the dashboard's five
 * S1-FR-5 views, same convention as src/lib/admin-api.ts — every dashboard
 * page is an async Server Component that calls one of these directly
 * (reads the httpOnly session cookie via next/headers, forwards it as the
 * real Builder bearer token), so no browser-facing /api/admin/dashboard/*
 * proxy route is needed the way Unit 8's client-side CRUD dialogs require
 * one — these views never write.
 */
async function dashboardFetch(path: string): Promise<Response> {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!token) {
    return Response.json({ detail: "Not authenticated" }, { status: 401 });
  }

  const baseUrl = process.env.MEADOWOPS_API_BASE_URL;
  if (!baseUrl) {
    return Response.json({ detail: "Server is not configured" }, { status: 500 });
  }

  return fetch(`${baseUrl}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
    // Every view here reflects the live simulation state — never serve a
    // stale cached read back to the Builder.
    cache: "no-store",
  });
}

function toQuery(params: Record<string, string | undefined>): string {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined) as [string, string][];
  if (entries.length === 0) return "";
  return `?${new URLSearchParams(entries).toString()}`;
}

export function getExecutiveSummary(): Promise<Response> {
  return dashboardFetch("/api/v1/dashboard/executive");
}

export function getExecutiveTrend(): Promise<Response> {
  return dashboardFetch("/api/v1/dashboard/executive/trend");
}

export function listInventoryPositions(params: { warehouseId?: string } = {}): Promise<Response> {
  return dashboardFetch(`/api/v1/dashboard/inventory${toQuery({ warehouse_id: params.warehouseId })}`);
}

export function listInventoryTransactions(productId: string, warehouseId: string): Promise<Response> {
  return dashboardFetch(
    `/api/v1/dashboard/inventory/${encodeURIComponent(productId)}/${encodeURIComponent(warehouseId)}/transactions`
  );
}

export function listSupplierPerformance(): Promise<Response> {
  return dashboardFetch("/api/v1/dashboard/suppliers");
}

export function listSupplierPurchaseOrders(supplierId: string): Promise<Response> {
  return dashboardFetch(`/api/v1/dashboard/suppliers/${encodeURIComponent(supplierId)}/purchase-orders`);
}

export function listPurchaseOrders(): Promise<Response> {
  return dashboardFetch("/api/v1/dashboard/orders/purchase");
}

export function getPurchaseOrderDetail(purchaseOrderId: string): Promise<Response> {
  return dashboardFetch(`/api/v1/dashboard/orders/purchase/${encodeURIComponent(purchaseOrderId)}`);
}

export function listSalesOrders(): Promise<Response> {
  return dashboardFetch("/api/v1/dashboard/orders/sales");
}

export function getSalesOrderDetail(salesOrderId: string): Promise<Response> {
  return dashboardFetch(`/api/v1/dashboard/orders/sales/${encodeURIComponent(salesOrderId)}`);
}

export function listShipments(): Promise<Response> {
  return dashboardFetch("/api/v1/dashboard/shipments");
}

export function listExceptions(params: { category?: string; includeResolved?: boolean } = {}): Promise<Response> {
  return dashboardFetch(
    `/api/v1/dashboard/exceptions${toQuery({
      category: params.category,
      include_resolved: params.includeResolved ? "true" : undefined,
    })}`
  );
}

export function getExceptionDrilldown(exceptionFlagId: string): Promise<Response> {
  return dashboardFetch(`/api/v1/dashboard/exceptions/${encodeURIComponent(exceptionFlagId)}`);
}
