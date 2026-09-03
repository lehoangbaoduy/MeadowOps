import { NextRequest, NextResponse } from "next/server";

import { updateMasterData } from "@/lib/admin-api";

const ENTITY = "products";

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
): Promise<NextResponse> {
  const { id } = await params;
  const payload = await request.json();
  const response = await updateMasterData(ENTITY, id, payload);
  return NextResponse.json(await response.json(), { status: response.status });
}
