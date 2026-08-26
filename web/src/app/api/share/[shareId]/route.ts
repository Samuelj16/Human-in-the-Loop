/**
 * Public report fetch - deliberately separate from the authenticated proxy,
 * since a shared report must be readable by someone with no account.
 */
import { NextResponse } from "next/server";

import { API_BASE } from "@/lib/session";

export async function GET(
  _request: Request,
  context: { params: Promise<{ shareId: string }> },
) {
  const { shareId } = await context.params;

  const upstream = await fetch(
    `${API_BASE}/api/public/reports/${encodeURIComponent(shareId)}`,
    { cache: "no-store" },
  );

  const payload = await upstream.json().catch(() => ({}));
  return NextResponse.json(payload, { status: upstream.status });
}
