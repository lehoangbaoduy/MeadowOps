import Link from "next/link";
import { notFound } from "next/navigation";
import { IconArrowLeft } from "@tabler/icons-react";

import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatDate } from "@/lib/dashboard-format";
import { getExceptionDrilldown } from "@/lib/dashboard-api";
import { EXCEPTION_CATEGORY_LABEL, type ExceptionDrilldown } from "@/types/dashboard";

export default async function ExceptionDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const response = await getExceptionDrilldown(id);
  if (response.status === 404) {
    notFound();
  }
  const drilldown: ExceptionDrilldown = await response.json();
  const { flag } = drilldown;

  return (
    <div className="space-y-6">
      <PageHeader
        title={EXCEPTION_CATEGORY_LABEL[flag.category] ?? flag.category}
        description={`First detected ${formatDate(flag.first_detected_simulation_date)}, last observed ${formatDate(flag.simulation_date)}.`}
      >
        <div className="flex items-center gap-2">
          {flag.resolved_at ? (
            <Badge variant="secondary">Resolved</Badge>
          ) : (
            <Badge variant="destructive">Open</Badge>
          )}
          <Button variant="outline" size="sm" asChild>
            <Link href="/reports">
              <IconArrowLeft className="size-4" /> Back to reports
            </Link>
          </Button>
        </div>
      </PageHeader>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium text-muted-foreground">Measurement</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
          <div>
            <p className="text-muted-foreground">Measured</p>
            <p className="font-medium tabular-nums">{flag.measured_value ?? "—"}</p>
          </div>
          <div>
            <p className="text-muted-foreground">Threshold</p>
            <p className="font-medium tabular-nums">{flag.threshold_value}</p>
          </div>
        </CardContent>
      </Card>

      {drilldown.purchase_order && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium text-muted-foreground">Purchase order</CardTitle>
          </CardHeader>
          <CardContent>
            <Link href={`/orders/${drilldown.purchase_order.id}`} className="font-medium hover:underline">
              {drilldown.purchase_order.po_number}
            </Link>
            <p className="text-sm text-muted-foreground">
              Expected {formatDate(drilldown.purchase_order.expected_delivery_date)} — status{" "}
              {drilldown.purchase_order.status}
            </p>
          </CardContent>
        </Card>
      )}

      {drilldown.shipment && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium text-muted-foreground">Shipment</CardTitle>
          </CardHeader>
          <CardContent>
            <Link href={`/orders/sales/${drilldown.shipment.sales_order_id}`} className="font-medium hover:underline">
              View sales order
            </Link>
            <p className="text-sm text-muted-foreground">
              Promised {formatDate(drilldown.shipment.promised_delivery_date)} — status{" "}
              {drilldown.shipment.status}
            </p>
          </CardContent>
        </Card>
      )}

      {drilldown.inventory && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium text-muted-foreground">Inventory position</CardTitle>
          </CardHeader>
          <CardContent>
            <Link
              href={`/inventory/${drilldown.inventory.product_id}/${drilldown.inventory.warehouse_id}`}
              className="font-medium hover:underline"
            >
              {drilldown.inventory.product_id} @ {drilldown.inventory.warehouse_id}
            </Link>
            <p className="text-sm text-muted-foreground">
              On hand {drilldown.inventory.quantity_on_hand ?? "—"}, days of supply{" "}
              {drilldown.inventory.days_of_supply ?? "—"}
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
