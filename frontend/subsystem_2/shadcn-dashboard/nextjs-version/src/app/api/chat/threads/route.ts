import { NextRequest, NextResponse } from "next/server";

import { createThread, listThreads } from "@/lib/chat-api";

export async function GET(): Promise<NextResponse> {
  const response = await listThreads();
  return NextResponse.json(await response.json(), { status: response.status });
}

export async function POST(request: NextRequest): Promise<NextResponse> {
  const payload = await request.json();
  const response = await createThread(payload.scenario_id, payload.persona);
  return NextResponse.json(await response.json(), { status: response.status });
}
