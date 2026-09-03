import { NextRequest, NextResponse } from "next/server";

import { cancelQueryConfirmation } from "@/lib/admin-api";

export async function POST(request: NextRequest): Promise<NextResponse> {
  const payload = await request.json();
  const response = await cancelQueryConfirmation(payload.sql);
  // Backend returns 204 No Content on success - no body to parse there,
  // unlike its own 401/500 error paths which do return a JSON `detail`.
  if (response.status === 204) {
    return new NextResponse(null, { status: 204 });
  }
  return NextResponse.json(await response.json(), { status: response.status });
}
