import { NextRequest, NextResponse } from "next/server";

import { createScenario } from "@/lib/scenario-api";

export async function POST(request: NextRequest): Promise<NextResponse> {
  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json({ detail: "Invalid request body" }, { status: 400 });
  }
  const response = await createScenario(payload);
  return NextResponse.json(await response.json(), { status: response.status });
}
