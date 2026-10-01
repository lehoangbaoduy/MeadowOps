import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/**
 * Unit 41: the frame every Overview chart sits in. `isEmpty` swaps the chart
 * for a plain sentence - an empty window must read as "nothing happened",
 * never as a flat or zero-filled chart that looks like a real result.
 */
export function ChartCard({
  title,
  description,
  isEmpty = false,
  emptyMessage = "Nothing recorded in this window yet.",
  className,
  children,
}: {
  title: string;
  description?: string;
  isEmpty?: boolean;
  emptyMessage?: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <Card className={cn("flex flex-col", className)}>
      <CardHeader>
        <CardTitle className="text-sm font-semibold">{title}</CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
      </CardHeader>
      <CardContent className="flex flex-1 flex-col justify-center">
        {isEmpty ? (
          <p className="py-10 text-center text-sm text-muted-foreground">{emptyMessage}</p>
        ) : (
          children
        )}
      </CardContent>
    </Card>
  );
}
