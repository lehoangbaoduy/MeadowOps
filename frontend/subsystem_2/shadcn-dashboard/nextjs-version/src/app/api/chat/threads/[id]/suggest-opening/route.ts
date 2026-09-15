import { NextRequest, NextResponse } from "next/server";

import { suggestOpening } from "@/lib/chat-api";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
): Promise<NextResponse> {
  const { id } = await params;
  const payload = await request.json();
  const response = await suggestOpening(id, payload.attitude);
  return NextResponse.json(await response.json(), { status: response.status });
}
