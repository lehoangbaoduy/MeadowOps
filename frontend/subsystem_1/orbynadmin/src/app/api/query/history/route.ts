import { NextResponse } from "next/server";

import { getQueryHistory } from "@/lib/admin-api";

export async function GET(): Promise<NextResponse> {
  const response = await getQueryHistory();
  return NextResponse.json(await response.json(), { status: response.status });
}
