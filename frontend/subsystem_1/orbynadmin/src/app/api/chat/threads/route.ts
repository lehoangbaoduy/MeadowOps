import { NextResponse } from "next/server";

import { listThreads } from "@/lib/chat-api";

export async function GET(): Promise<NextResponse> {
  const response = await listThreads();
  return NextResponse.json(await response.json(), { status: response.status });
}
