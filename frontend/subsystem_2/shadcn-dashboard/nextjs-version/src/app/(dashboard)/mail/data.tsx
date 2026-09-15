/**
 * Unit 21 (MEADOWOPS-UI-003, PRD 6.13, DD-25): mirrors the backend's
 * ThreadReadWithUnread/MessageRead shapes (app/schemas/chat.py) exactly —
 * this file replaces the original template's fabricated `Mail`/`Account`/
 * `Contact` types (Unit 7 already stripped the fake data itself; this
 * strips the types that described it).
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

export const PERSONAS: Persona[] = [
  "operations_manager",
  "procurement_manager",
  "warehouse_manager",
  "it_manager",
  "operations_director",
  "cfo",
];

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

// Unit 35 (follow-on to Unit 23): mirrors app.domain.persona_chat.Attitude
// exactly (backend/app/schemas/chat.py's own Attitude Literal, which
// app.api.chat's suggest-pushback/suggest-opening routes validate against) —
// this is the first frontend surface for the attitude concept; Unit 23's
// own backend work never had a UI to feed it from.
export type Attitude = "neutral" | "frustrated" | "urgent" | "skeptical" | "appreciative";

export const ATTITUDES: Attitude[] = ["neutral", "frustrated", "urgent", "skeptical", "appreciative"];

const ATTITUDE_LABELS: Record<Attitude, string> = {
  neutral: "Neutral",
  frustrated: "Frustrated",
  urgent: "Urgent",
  skeptical: "Skeptical",
  appreciative: "Appreciative",
};

export function attitudeLabel(attitude: string): string {
  return ATTITUDE_LABELS[attitude as Attitude] ?? attitude;
}

export type ChatThread = {
  id: string;
  scenario_id: string;
  persona: Persona;
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

export type NotificationKind = "deadline_approaching" | "deadline_missed";

const NOTIFICATION_LABELS: Record<NotificationKind, string> = {
  deadline_approaching: "Response due soon",
  deadline_missed: "Response overdue",
};

export function notificationLabel(kind: string): string {
  return NOTIFICATION_LABELS[kind as NotificationKind] ?? kind;
}

// Mirrors app.schemas.chat.NotificationRead. The Builder (admin role)
// receives deadline_missed rows only — app.services.notifications.
// _recipient_ids notifies the Builder when a thread goes overdue, and
// notifies the Analyst separately (Subsystem 1) when one is approaching.
export type Notification = {
  id: string;
  thread_id: string;
  kind: NotificationKind;
  created_at: string;
  read_at: string | null;
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

export type ScenarioOption = {
  id: string;
  title: string;
};
