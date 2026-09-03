import { NextRequest, NextResponse } from "next/server";

import { executeQuery } from "@/lib/admin-api";

export async function POST(request: NextRequest): Promise<NextResponse> {
  const payload = await request.json();
  const response = await executeQuery(payload.sql, Boolean(payload.confirmed));
  return NextResponse.json(await response.json(), { status: response.status });
}
