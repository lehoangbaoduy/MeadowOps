import Link from "next/link";
import { notFound } from "next/navigation";
import { IconArrowLeft } from "@tabler/icons-react";

import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatDate, formatDateTime } from "@/lib/dashboard-format";
import { getPurchaseOrderDetail } from "@/lib/dashboard-api";
import type { PurchaseOrderDetail } from "@/types/dashboard";

export default async function OrderDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const response = await getPurchaseOrderDetail(id);
  if (response.status === 404) {
    notFound();
  }
  const po: PurchaseOrderDetail = await response.json();

  return (
    <div className="space-y-6">
      <PageHeader title={po.po_number} description={`Ordered ${formatDate(po.order_date)} from ${po.supplier_id}, warehouse ${po.warehouse_id}.`}>
        <div className="flex items-center gap-2">
          {po.is_at_risk && <Badge variant="destructive">At risk</Badge>}
          <Button variant="outline" size="sm" asChild>
            <Link href="/orders">
              <IconArrowLeft className="size-4" /> Back to orders
            </Link>
          </Button>
        </div>
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
                <TableHead>Received</TableHead>
                <TableHead>Unit Cost</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {po.lines.map((line) => (
                <TableRow key={line.id}>
                  <TableCell>{line.product_id}</TableCell>
                  <TableCell>{line.quantity_ordered}</TableCell>
                  <TableCell>{line.quantity_received}</TableCell>
                  <TableCell>${line.unit_cost}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
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
              {po.lifecycle_events.map((event, i) => (
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
