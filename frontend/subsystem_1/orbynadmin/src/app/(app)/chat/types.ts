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

export type ChatThread = {
  id: string;
  scenario_id: string;
  persona: Persona;
  created_at: string;
  unread_count: number;
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
