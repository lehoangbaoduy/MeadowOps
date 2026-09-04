import { NextResponse } from "next/server";

import { markThreadRead } from "@/lib/chat-api";

export async function POST(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
): Promise<NextResponse> {
  const { id } = await params;
  const response = await markThreadRead(id);
  if (response.status === 204) {
    return new NextResponse(null, { status: 204 });
  }
  return NextResponse.json(await response.json(), { status: response.status });
}
