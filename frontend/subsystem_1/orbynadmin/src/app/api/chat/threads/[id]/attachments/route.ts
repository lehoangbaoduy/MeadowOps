import { NextRequest, NextResponse } from "next/server";

import { uploadAttachment } from "@/lib/chat-api";

// Unit 30c (MEADOWOPS-UI-005, S1-FR-15/PRD 347/380, B12 follow-on to U30):
// forwards the browser's own multipart FormData straight through - never
// re-parsed and rebuilt here, so the file bytes pass through unmodified
// and the backend's own magic-byte sniffing (app.domain.
// attachment_validation) sees exactly what the browser sent.
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
): Promise<NextResponse> {
  const { id } = await params;
  const formData = await request.formData();
  const response = await uploadAttachment(id, formData);
  return NextResponse.json(await response.json(), { status: response.status });
}
