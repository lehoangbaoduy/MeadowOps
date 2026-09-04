import { NextResponse } from "next/server";

import { mintWsTicket } from "@/lib/chat-api";

/**
 * The one route in this proxy family the browser calls directly (not via a
 * TanStack Query hook hitting a server component) — see
 * src/app/(dashboard)/mail/use-chat-socket.ts. Ticket is single-use and
 * expires in 20s server-side, so this is minted fresh on every connect
 * attempt, never cached or reused across reconnects.
 */
export async function POST(): Promise<NextResponse> {
  const response = await mintWsTicket();
  return NextResponse.json(await response.json(), { status: response.status });
}
