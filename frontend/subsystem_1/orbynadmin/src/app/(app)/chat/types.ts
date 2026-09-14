/**
 * Unit 21 (MEADOWOPS-UI-003, PRD 6.13, S1-FR-15): mirrors the backend's
 * ThreadReadWithUnread/MessageRead shapes (app/schemas/chat.py).
 */
// Mirrors app.services.chat.MAX_MESSAGE_BODY_LENGTH — a client-side cap so
// a send that will be rejected 422 by the backend is caught before the
// round trip (code review, 2026-09-03).
export const MAX_MESSAGE_BODY_LENGTH = 10_000;

export type Persona =
  | "operations_manager"
  | "procurement_manager"
  | "warehouse_manager"
  | "it_manager"
  | "operations_director"
  | "cfo";

const PERSONA_LABELS: Record<Persona, string> = {
  operations_manager: "Operations Manager",
  procurement_manager: "Procurement Manager",
  warehouse_manager: "Warehouse Manager",
  it_manager: "IT Manager",
  operations_director: "Operations Director",
  cfo: "CFO",
};

export function personaLabel(persona: string): string {
  return PERSONA_LABELS[persona as Persona] ?? persona;
}

// Unit 34: mirrors app.schemas.chat.ThreadStatus - a thread never leaves
// "completed" once app.services.evaluation.complete_thread_and_generate_
// evaluation has run (the Builder-side /complete action, Subsystem 2's
// scenario detail page), so the reflection prompt below can key off it
// directly rather than re-deriving from evaluation/portfolio state itself.
export type ThreadStatus = "open" | "completed";

export type ChatThread = {
  id: string;
  scenario_id: string;
  persona: Persona;
  status: ThreadStatus;
  created_at: string;
  // Unit 30a (MEADOWOPS-UI-003, PRD 6.1): mirrors app.schemas.chat.
  // ThreadRead/ThreadReadWithUnread — deadline_at is null once a thread has
  // no message yet or its most recent sender was the Analyst; is_overdue is
  // a moment-of-response computation the backend recomputes on every
  // response, not a stored flag.
  deadline_at: string | null;
  is_overdue: boolean;
  unread_count: number;
  // Unit 30b (MEADOWOPS-UI-004, PRD 6.1 "Drafting" bullet, catalog row
  // 31): this viewer's own not-yet-sent draft for this thread ("" if
  // none) — mirrors app.schemas.chat.ThreadReadWithUnread.draft_body.
  draft_body: string;
};

export type ChatMessage = {
  id: string;
  thread_id: string;
  sender_user_id: string;
  sender_role: "admin" | "analyst";
  body: string;
  attachment_ref: string | null;
  sent_at: string;
};
