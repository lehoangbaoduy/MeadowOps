"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { RefreshCw } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";

/**
 * Unit 39 (MEADOWOPS-DOM-027): re-triggers just one Builder-only note (the
 * narrative or the expected query) through its own backend route, instead of
 * the all-or-nothing draft "Regenerate". The old text is replaced, so it asks
 * first when there is something to lose.
 */
export function RegenerateButton({
  id,
  action,
  noun,
  hasExisting,
}: {
  id: string;
  action: "regenerate-narrative" | "regenerate-expected-query";
  noun: string;
  hasExisting: boolean;
}) {
  const router = useRouter();
  const [isRunning, setIsRunning] = useState(false);

  async function handleClick() {
    if (hasExisting && !window.confirm(`Replace the current ${noun} with a freshly generated one?`)) {
      return;
    }
    setIsRunning(true);
    try {
      const response = await fetch(`/api/scenarios/${id}/${action}`, { method: "POST" });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        toast.error(typeof body.detail === "string" ? body.detail : `Could not regenerate the ${noun}`);
        return;
      }
      toast.success(`New ${noun} generated`);
      router.refresh();
    } catch {
      toast.error("Could not reach the server");
    } finally {
      setIsRunning(false);
    }
  }

  return (
    <Button size="sm" variant="outline" onClick={handleClick} disabled={isRunning}>
      <RefreshCw className={isRunning ? "size-4 animate-spin" : "size-4"} />
      {isRunning ? "Generating…" : hasExisting ? `Regenerate ${noun}` : `Generate ${noun}`}
    </Button>
  );
}
