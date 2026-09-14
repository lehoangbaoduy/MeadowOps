import { NextResponse } from "next/server";

import { listThreadsForScenario } from "@/lib/chat-api";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
): Promise<NextResponse> {
  const { id } = await params;
  const response = await listThreadsForScenario(id);
  return NextResponse.json(await response.json(), { status: response.status });
}
