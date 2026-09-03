"use client";

import { useEffect } from "react";
import { AlertTriangle } from "lucide-react";

import { Button } from "@/components/ui/button";

/**
 * Unit 20a (MEADOWOPS-UI-002): code review, MEDIUM — nothing under
 * `(dashboard)` had an error boundary before this unit added its first
 * real data-fetching pages (`scenarios/[id]/page.tsx` throws on a
 * non-404 backend error response). Without this, any such error degraded
 * to Next.js's default unstyled error screen instead of an in-app state
 * with a way back.
 */
export default function DashboardError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="flex flex-col items-center justify-center gap-3 px-4 py-24 text-center">
      <AlertTriangle className="size-8 text-destructive" />
      <p className="text-sm font-medium">Something went wrong loading this page.</p>
      <p className="max-w-sm text-sm text-muted-foreground">{error.message}</p>
      <Button onClick={reset}>Try again</Button>
    </div>
  );
}
