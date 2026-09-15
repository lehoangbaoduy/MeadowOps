"use client"

import { useEffect, useState } from "react"
import { Loader2, Sparkles } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { ATTITUDES, attitudeLabel, type Attitude } from "../data"

export type SuggestResult = { ok: true; message: string } | { ok: false; error: string }
export type SufficiencyResult =
  | { ok: true; verdict: "sufficient" | "insufficient"; suggestedPushback: string | null }
  | { ok: false; error: string }

// Unit 35 (follow-on to Unit 23, PRD 6.13): the first frontend surface for
// any of persona_chat's three Claude-backed actions - suggest-opening (new
// this unit), suggest-pushback and sufficiency-check (both built backend-
// only since Unit 23, with zero caller anywhere in this app until now).
// Which actions are offered is state-driven off the thread's own message
// history, mirroring the backend's own guards exactly rather than
// duplicating them as separate frontend rules: suggest-opening requires
// zero messages (app.services.persona_chat.ThreadAlreadyHasMessagesError),
// suggest-pushback/sufficiency-check require at least one Analyst message
// (NoAnalystMessageYetError). A thread can only ever be in one of these
// two states, never both, so the panel shows exactly one action group.
export function AiAssistPanel({
  hasMessages,
  hasAnalystMessage,
  onSuggestOpening,
  onSuggestPushback,
  onCheckSufficiency,
  onAcceptSuggestion,
}: {
  hasMessages: boolean;
  hasAnalystMessage: boolean;
  onSuggestOpening: (attitude: Attitude) => Promise<SuggestResult>;
  onSuggestPushback: (attitude: Attitude) => Promise<SuggestResult>;
  onCheckSufficiency: () => Promise<SufficiencyResult>;
  onAcceptSuggestion: (text: string) => void;
}) {
  const [attitude, setAttitude] = useState<Attitude>("neutral");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [verdict, setVerdict] = useState<{ text: string; suggestedPushback: string | null } | null>(null);

  // Code review (verification pass, this unit): hasMessages/hasAnalystMessage
  // flipping means the offered action group just changed (e.g. the Analyst's
  // first reply just arrived) - a leftover error or verdict from the
  // no-longer-offered action would otherwise stay on screen looking like it
  // still applies to the new one.
  useEffect(() => {
    setError(null);
    setVerdict(null);
  }, [hasMessages, hasAnalystMessage]);

  async function runSuggest(action: (attitude: Attitude) => Promise<SuggestResult>) {
    setPending(true);
    setError(null);
    setVerdict(null);
    try {
      const result = await action(attitude);
      if (result.ok) {
        onAcceptSuggestion(result.message);
      } else {
        setError(result.error);
      }
    } finally {
      setPending(false);
    }
  }

  async function runSufficiencyCheck() {
    setPending(true);
    setError(null);
    setVerdict(null);
    try {
      const result = await onCheckSufficiency();
      if (result.ok) {
        setVerdict({
          text: result.verdict === "sufficient" ? "Sufficient — safe to mark Completed." : "Insufficient.",
          suggestedPushback: result.suggestedPushback,
        });
      } else {
        setError(result.error);
      }
    } finally {
      setPending(false);
    }
  }

  // PRD 6.13: "the Builder decides whether to act on it" - a recommendation
  // only, never automatically applied to the composer, unlike an accepted
  // opening/pushback suggestion.
  function acceptSuggestedPushback() {
    if (verdict?.suggestedPushback) onAcceptSuggestion(verdict.suggestedPushback);
    setVerdict(null);
  }

  return (
    <div className="flex flex-col gap-2 border-b bg-muted/30 px-4 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <Sparkles className="size-4 shrink-0 text-muted-foreground" />
        <Select value={attitude} onValueChange={(value) => setAttitude(value as Attitude)}>
          <SelectTrigger className="h-8 w-36 cursor-pointer text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {ATTITUDES.map((option) => (
              <SelectItem key={option} value={option} className="cursor-pointer">
                {attitudeLabel(option)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {!hasMessages && (
          <Button
            size="sm"
            variant="outline"
            disabled={pending}
            onClick={() => runSuggest(onSuggestOpening)}
            className="cursor-pointer"
          >
            {pending && <Loader2 className="size-3 animate-spin" />}
            Suggest opening message
          </Button>
        )}
        {hasAnalystMessage && (
          <>
            <Button
              size="sm"
              variant="outline"
              disabled={pending}
              onClick={() => runSuggest(onSuggestPushback)}
              className="cursor-pointer"
            >
              {pending && <Loader2 className="size-3 animate-spin" />}
              Suggest pushback
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={pending}
              onClick={runSufficiencyCheck}
              className="cursor-pointer"
            >
              {pending && <Loader2 className="size-3 animate-spin" />}
              Check sufficiency
            </Button>
          </>
        )}
      </div>
      {error && <p className="text-xs text-destructive">{error}</p>}
      {verdict && (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span>{verdict.text}</span>
          {verdict.suggestedPushback && (
            <Button
              size="sm"
              variant="ghost"
              onClick={acceptSuggestedPushback}
              className="h-6 cursor-pointer px-2 text-xs"
            >
              Use suggested pushback
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
