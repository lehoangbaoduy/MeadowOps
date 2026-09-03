"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Search } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import {
  COMPETENCY_CLUSTER_OPTIONS,
  DIFFICULTY_TIER_OPTIONS,
  SCENARIO_TYPE_OPTIONS,
  type ExceptionFlag,
} from "../../types";

function describeException(flag: ExceptionFlag): string {
  const bits = [
    flag.product_id ? `product ${flag.product_id}` : null,
    flag.warehouse_id ? `warehouse ${flag.warehouse_id}` : null,
    flag.purchase_order_id ? `PO ${flag.purchase_order_id.slice(0, 8)}` : null,
    flag.shipment_id ? `shipment ${flag.shipment_id.slice(0, 8)}` : null,
  ].filter(Boolean);
  return bits.length > 0 ? bits.join(", ") : "no linked entity";
}

export function CreateScenarioForm({ exceptions }: { exceptions: ExceptionFlag[] }) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [scenarioType, setScenarioType] = useState<string>("");
  const [competencyCluster, setCompetencyCluster] = useState<string>("");
  const [difficultyTier, setDifficultyTier] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return exceptions;
    return exceptions.filter((flag) =>
      [flag.category, flag.product_id, flag.warehouse_id]
        .filter((v): v is string => Boolean(v))
        .some((v) => v.toLowerCase().includes(needle))
    );
  }, [exceptions, query]);

  const canSubmit =
    Boolean(selectedId) &&
    title.trim().length > 0 &&
    Boolean(scenarioType) &&
    Boolean(competencyCluster) &&
    Boolean(difficultyTier);

  async function handleSubmit() {
    if (!canSubmit || !selectedId) return;
    setError(null);
    setIsSubmitting(true);
    try {
      const response = await fetch("/api/scenarios", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          exception_flag_id: selectedId,
          scenario_type: scenarioType,
          competency_cluster: competencyCluster,
          difficulty_tier: difficultyTier,
          title: title.trim(),
        }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        setError(typeof body.detail === "string" ? body.detail : "Could not create scenario");
        return;
      }
      toast.success("Scenario created");
      router.push(`/scenarios/${body.id}`);
      router.refresh();
    } catch {
      setError("Could not reach the server");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card>
        <CardContent className="space-y-4">
          <div>
            <Label className="mb-2">1. Select an open exception</Label>
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
              <Input
                placeholder="Filter by category, product, or warehouse…"
                className="pl-8"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>
          </div>

          {filtered.length === 0 ? (
            <p className="rounded-lg border py-8 text-center text-sm text-muted-foreground">
              {exceptions.length === 0
                ? "No open exceptions right now."
                : "No exceptions match that filter."}
            </p>
          ) : (
            <RadioGroup
              value={selectedId ?? undefined}
              onValueChange={setSelectedId}
              className="max-h-96 space-y-2 overflow-y-auto"
            >
              {filtered.map((flag) => (
                <Label
                  key={flag.id}
                  htmlFor={flag.id}
                  className="flex cursor-pointer items-start gap-3 rounded-lg border p-3 has-[[data-state=checked]]:border-primary has-[[data-state=checked]]:bg-accent"
                >
                  <RadioGroupItem value={flag.id} id={flag.id} className="mt-1" />
                  <div className="grid gap-1">
                    <span className="text-sm font-medium">{flag.category}</span>
                    <span className="text-xs text-muted-foreground">
                      {describeException(flag)}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      measured {flag.measured_value ?? "—"} vs threshold {flag.threshold_value} ·
                      first detected {flag.first_detected_simulation_date}
                    </span>
                  </div>
                </Label>
              ))}
            </RadioGroup>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="space-y-4">
          <Label className="mb-2">2. Scenario details</Label>

          <div className="grid gap-2">
            <Label htmlFor="title">Title</Label>
            <Input
              id="title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Late shipment root cause"
            />
          </div>

          <div className="grid gap-2">
            <Label>Scenario type</Label>
            <Select value={scenarioType} onValueChange={setScenarioType}>
              <SelectTrigger className="w-full">
                <SelectValue placeholder="Select a type" />
              </SelectTrigger>
              <SelectContent>
                {SCENARIO_TYPE_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="grid gap-2">
            <Label>Competency cluster</Label>
            <Select value={competencyCluster} onValueChange={setCompetencyCluster}>
              <SelectTrigger className="w-full">
                <SelectValue placeholder="Select a competency" />
              </SelectTrigger>
              <SelectContent>
                {COMPETENCY_CLUSTER_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="grid gap-2">
            <Label>Difficulty tier</Label>
            <Select value={difficultyTier} onValueChange={setDifficultyTier}>
              <SelectTrigger className="w-full">
                <SelectValue placeholder="Select a difficulty" />
              </SelectTrigger>
              <SelectContent>
                {DIFFICULTY_TIER_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {error && <p className="text-sm text-destructive">{error}</p>}

          <Button
            className="w-full"
            disabled={!canSubmit || isSubmitting}
            onClick={handleSubmit}
          >
            {isSubmitting ? "Creating…" : "Create scenario"}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
