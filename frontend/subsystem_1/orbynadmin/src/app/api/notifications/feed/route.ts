import { NextResponse } from "next/server";

import { listNotificationFeed } from "@/lib/chat-api";

export async function GET(): Promise<NextResponse> {
  const response = await listNotificationFeed();
  return NextResponse.json(await response.json().catch(() => ({})), { status: response.status });
}
