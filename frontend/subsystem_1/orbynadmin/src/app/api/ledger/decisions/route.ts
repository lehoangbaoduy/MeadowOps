import { NextRequest, NextResponse } from "next/server";

import { proposeDecision } from "@/lib/ledger-api";

export async function POST(request: NextRequest): Promise<NextResponse> {
  const payload = await request.json();
  const response = await proposeDecision(payload);
  return NextResponse.json(await response.json(), { status: response.status });
}
