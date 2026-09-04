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
  const response = await sendMessage(id, payload.body);
  return NextResponse.json(await response.json(), { status: response.status });
}
