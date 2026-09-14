"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { IconPlus } from "@tabler/icons-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { ENTITY_TYPE_OPTIONS, type EntityType } from "@/types/ledger";

function extractErrorMessage(body: unknown): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (
      detail &&
      typeof detail === "object" &&
      "errors" in detail &&
      Array.isArray((detail as { errors: unknown }).errors)
    ) {
      return (detail as { errors: string[] }).errors.join("; ");
    }
  }
  return "Request failed";
}

/**
 * Unit 34 (PRD 4.4/6.6 step 10): the write half of the Activity page -
 * `entity_type`/`entity_id` are free-form here (this app has no unified
 * cross-entity picker), matching app/schemas/ledger.py's own free-text
 * `entity_id: str` - the backend does not validate it against master data
 * either (DecisionEvent is a log, not a foreign key to Product/Supplier/
 * etc., same reasoning as PRD 9.2's "callback scenario referencing a
 * since-deactivated entity" edge case: the ledger must keep working even
 * when the entity it names no longer exists).
 */
export function ProposeDecisionDialog() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [entityType, setEntityType] = useState<EntityType | "">("");
  const [entityId, setEntityId] = useState("");
  const [title, setTitle] = useState("");
  const [summary, setSummary] = useState("");
  const [pending, setPending] = useState(false);

  const canSubmit =
    Boolean(entityType) && entityId.trim().length > 0 && title.trim().length > 0 && summary.trim().length > 0;

  async function handleSubmit() {
    if (!canSubmit) return;
    setPending(true);
    try {
      const response = await fetch("/api/ledger/decisions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          entity_type: entityType,
          entity_id: entityId.trim(),
          title: title.trim(),
          summary: summary.trim(),
        }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        toast.error(extractErrorMessage(body));
        return;
      }
      toast.success("Decision proposed");
      setOpen(false);
      setEntityType("");
      setEntityId("");
      setTitle("");
      setSummary("");
      router.refresh();
    } catch {
      toast.error("Could not reach the server");
    } finally {
      setPending(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <IconPlus className="size-4" />
          Propose Decision
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Propose a decision</DialogTitle>
        </DialogHeader>
        <div className="grid gap-4">
          <div className="grid gap-2">
            <Label>Entity type</Label>
            <Select value={entityType} onValueChange={(v) => setEntityType(v as EntityType)}>
              <SelectTrigger className="w-full">
                <SelectValue placeholder="Select an entity type" />
              </SelectTrigger>
              <SelectContent>
                {ENTITY_TYPE_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="entity_id">Entity ID</Label>
            <Input id="entity_id" value={entityId} onChange={(e) => setEntityId(e.target.value)} />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="decision_title">Title</Label>
            <Input id="decision_title" value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="decision_summary">Summary</Label>
            <Textarea
              id="decision_summary"
              rows={4}
              value={summary}
              onChange={(e) => setSummary(e.target.value)}
            />
          </div>
        </div>
        <DialogFooter>
          <Button onClick={handleSubmit} disabled={pending || !canSubmit}>
            {pending ? "Proposing…" : "Propose"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
