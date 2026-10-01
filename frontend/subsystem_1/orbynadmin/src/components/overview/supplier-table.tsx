import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { OverviewSupplier } from "@/types/dashboard";

/**
 * Unit 41: supplier reliability for the window. "On-time" is a purchase order
 * received on or before its expected delivery date; a supplier with nothing
 * received yet shows "—", never 0%.
 */
export function SupplierTable({ suppliers }: { suppliers: OverviewSupplier[] }) {
  return (
    <Card className="xl:col-span-7">
      <CardHeader>
        <CardTitle className="text-sm font-semibold">Supplier reliability</CardTitle>
        <CardDescription>
          Purchase orders received in this window, and how many arrived by their expected date
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Supplier</TableHead>
              <TableHead className="text-right">Ordered</TableHead>
              <TableHead className="text-right">Received</TableHead>
              <TableHead className="text-right">On time</TableHead>
              <TableHead className="text-right">Open now</TableHead>
              <TableHead className="text-right">At risk</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {suppliers.map((s) => (
              <TableRow key={s.supplier_id}>
                <TableCell className="font-medium">{s.supplier_name}</TableCell>
                <TableCell className="text-right tabular-nums">{s.purchase_orders_placed}</TableCell>
                <TableCell className="text-right tabular-nums">{s.purchase_orders_received}</TableCell>
                <TableCell className="text-right tabular-nums">
                  {s.on_time_receipt_pct != null ? `${s.on_time_receipt_pct}%` : "—"}
                </TableCell>
                <TableCell className="text-right tabular-nums">{s.open_purchase_orders}</TableCell>
                <TableCell className="text-right">
                  {s.at_risk_purchase_orders > 0 ? (
                    <Badge variant="destructive">{s.at_risk_purchase_orders}</Badge>
                  ) : (
                    <span className="text-muted-foreground">0</span>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
