import { NextResponse } from "next/server";

import { completeThread } from "@/lib/chat-api";

export async function POST(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
): Promise<NextResponse> {
  const { id } = await params;
  const response = await completeThread(id);
  return NextResponse.json(await response.json(), { status: response.status });
}
