import { NextResponse } from "next/server";

import { requestClarification } from "@/lib/ledger-api";

export async function POST(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
): Promise<NextResponse> {
  const { id } = await params;
  const response = await requestClarification(id);
  return NextResponse.json(await response.json(), { status: response.status });
}
