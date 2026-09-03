import { Badge } from "@/components/ui/badge";

import type { ScenarioStatus } from "../types";

const STATUS_LABEL: Record<ScenarioStatus, string> = {
  draft: "Draft",
  approved: "Approved",
  active: "Active",
  cancelled: "Cancelled",
};

const STATUS_VARIANT: Record<ScenarioStatus, "default" | "secondary" | "destructive" | "outline"> = {
  draft: "secondary",
  approved: "default",
  active: "default",
  cancelled: "destructive",
};

export function ScenarioStatusBadge({ status }: { status: ScenarioStatus }) {
  return <Badge variant={STATUS_VARIANT[status]}>{STATUS_LABEL[status]}</Badge>;
}
