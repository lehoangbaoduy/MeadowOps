import Link from "next/link"
import { formatDistanceToNow } from "date-fns"
import { CheckCircle2, Inbox } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { personaLabel, type ChatThread } from "../../mail/data"

interface WorkListProps {
  threads: ChatThread[];
  scenarioTitles: Record<string, string>;
  emptyMessage: string;
  variant: "open" | "completed";
}

// Unit 39 (PRD 6.1): Open Work = conversations still in play; Completed Work
// = closed threads (their evaluation is generated at close). Both come from
// the real thread list, with the scenario title joined from the scenario list.
export function WorkList({ threads, scenarioTitles, emptyMessage, variant }: WorkListProps) {
  if (threads.length === 0) {
    const Icon = variant === "open" ? Inbox : CheckCircle2;
    return (
      <div className="flex flex-col items-center justify-center gap-2 rounded-lg border py-10 text-center">
        <Icon className="size-6 text-muted-foreground opacity-50" />
        <p className="text-sm font-medium">{emptyMessage}</p>
      </div>
    );
  }

  return (
    <ul className="flex flex-col divide-y rounded-lg border">
      {threads.map((thread) => (
        <li key={thread.id} className="flex items-start gap-3 px-4 py-3 text-sm">
          <div className="flex-1 space-y-0.5">
            <p className="font-medium">{scenarioTitles[thread.scenario_id] ?? "Scenario"}</p>
            <p className="text-xs text-muted-foreground">
              {personaLabel(thread.persona)} · started{" "}
              {formatDistanceToNow(new Date(thread.created_at), { addSuffix: true })}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-3">
            {variant === "open" && thread.is_overdue && (
              <Badge variant="destructive">Overdue</Badge>
            )}
            {variant === "open" && thread.unread_count > 0 && (
              <Badge variant="secondary">{thread.unread_count} unread</Badge>
            )}
            <Link href="/mail" className="text-xs text-primary hover:underline">
              Open
            </Link>
          </div>
        </li>
      ))}
    </ul>
  );
}
