import { NextRequest, NextResponse } from "next/server";

import { updateGroundTruth } from "@/lib/scenario-api";

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
): Promise<NextResponse> {
  const { id } = await params;
  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json({ detail: "Invalid request body" }, { status: 400 });
  }
  const response = await updateGroundTruth(id, payload);
  return NextResponse.json(await response.json(), { status: response.status });
}
