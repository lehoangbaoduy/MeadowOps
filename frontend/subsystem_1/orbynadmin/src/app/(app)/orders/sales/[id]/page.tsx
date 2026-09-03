import Link from "next/link";
import { notFound } from "next/navigation";
import { IconArrowLeft } from "@tabler/icons-react";

import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatDate, formatDateTime } from "@/lib/dashboard-format";
import { getSalesOrderDetail } from "@/lib/dashboard-api";
import type { SalesOrderDetail } from "@/types/dashboard";

export default async function SalesOrderDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const response = await getSalesOrderDetail(id);
  if (response.status === 404) {
    notFound();
  }
  const so: SalesOrderDetail = await response.json();

  return (
    <div className="space-y-6">
      <PageHeader
        title={so.so_number}
        description={`Ordered ${formatDate(so.order_date)} by ${so.customer_id}, warehouse ${so.warehouse_id}.`}
      >
        <Button variant="outline" size="sm" asChild>
          <Link href="/orders/sales">
            <IconArrowLeft className="size-4" /> Back to sales orders
          </Link>
        </Button>
      </PageHeader>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium text-muted-foreground">Lines</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Product</TableHead>
                <TableHead>Ordered</TableHead>
                <TableHead>Shipped</TableHead>
                <TableHead>Unit Price</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {so.lines.map((line) => (
                <TableRow key={line.id}>
                  <TableCell>{line.product_id}</TableCell>
                  <TableCell>{line.quantity_ordered}</TableCell>
                  <TableCell>{line.quantity_shipped}</TableCell>
                  <TableCell>${line.unit_price}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium text-muted-foreground">Shipments</CardTitle>
        </CardHeader>
        <CardContent>
          {so.shipments.length === 0 ? (
            <p className="text-sm text-muted-foreground">No shipments yet.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Carrier</TableHead>
                  <TableHead>Ship Date</TableHead>
                  <TableHead>Promised</TableHead>
                  <TableHead>Actual</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {so.shipments.map((shipment) => (
                  <TableRow key={shipment.id}>
                    <TableCell>{shipment.carrier_id}</TableCell>
                    <TableCell>{formatDate(shipment.ship_date)}</TableCell>
                    <TableCell>{formatDate(shipment.promised_delivery_date)}</TableCell>
                    <TableCell>
                      {shipment.actual_delivery_date ? formatDate(shipment.actual_delivery_date) : "—"}
                    </TableCell>
                    <TableCell className="flex items-center gap-2">
                      <Badge variant="outline">{shipment.status.replace("_", " ")}</Badge>
                      {shipment.is_late && <Badge variant="destructive">Late</Badge>}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium text-muted-foreground">Lifecycle</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>When</TableHead>
                <TableHead>From</TableHead>
                <TableHead>To</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {so.lifecycle_events.map((event, i) => (
                <TableRow key={i}>
                  <TableCell>{formatDateTime(event.occurred_at)}</TableCell>
                  <TableCell>{event.from_status ?? "—"}</TableCell>
                  <TableCell>{event.to_status}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
