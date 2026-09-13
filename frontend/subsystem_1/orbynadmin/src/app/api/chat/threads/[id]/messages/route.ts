import { NextRequest, NextResponse } from "next/server";

import { listMessages, sendMessage } from "@/lib/chat-api";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
): Promise<NextResponse> {
  const { id } = await params;
  const response = await listMessages(id);
  return NextResponse.json(await response.json(), { status: response.status });
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
): Promise<NextResponse> {
  const { id } = await params;
  const payload = await request.json();
  // Unit 30c (MEADOWOPS-UI-005, B12 follow-on to U30): attachment_id is
  // optional - only present when the composer has an uploaded-but-not-yet-
  // sent attachment pending.
  const response = await sendMessage(id, payload.body, payload.attachment_id);
  return NextResponse.json(await response.json(), { status: response.status });
}
