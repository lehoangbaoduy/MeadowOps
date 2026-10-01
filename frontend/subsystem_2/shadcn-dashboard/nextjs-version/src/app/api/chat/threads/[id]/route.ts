import { NextRequest, NextResponse } from "next/server";

import { deleteThread } from "@/lib/chat-api";

export async function DELETE(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
): Promise<NextResponse> {
  const { id } = await params;
  const response = await deleteThread(id);
  if (response.status === 204) return new NextResponse(null, { status: 204 });
  return NextResponse.json(await response.json(), { status: response.status });
}
