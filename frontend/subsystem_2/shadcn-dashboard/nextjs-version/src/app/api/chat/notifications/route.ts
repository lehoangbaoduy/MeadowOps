import { NextResponse } from "next/server";

import { listNotifications } from "@/lib/chat-api";

export async function GET(): Promise<NextResponse> {
  const response = await listNotifications();
  return NextResponse.json(await response.json(), { status: response.status });
}
