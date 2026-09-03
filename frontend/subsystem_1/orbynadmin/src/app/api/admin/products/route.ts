import { NextRequest, NextResponse } from "next/server";

import { createMasterData, listMasterData } from "@/lib/admin-api";

const ENTITY = "products";

export async function GET(): Promise<NextResponse> {
  const response = await listMasterData(ENTITY);
  return NextResponse.json(await response.json(), { status: response.status });
}

export async function POST(request: NextRequest): Promise<NextResponse> {
  const payload = await request.json();
  const response = await createMasterData(ENTITY, payload);
  return NextResponse.json(await response.json(), { status: response.status });
}
