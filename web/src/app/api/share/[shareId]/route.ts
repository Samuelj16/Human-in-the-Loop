/**
 * Next.js Server Route Handler: `/api/share/[shareId]`
 *
 * Public unauthenticated report fetch - deliberately separated from the authenticated
 * proxy (`/api/proxy/*`), allowing public shared research reports to be retrieved
 * by visitors without an account or login cookie.
 */
import { NextResponse } from "next/server";

import { API_BASE } from "@/lib/session";

/**
 * Handle public report retrieval by share identifier.
 *
 * @param _request - Incoming HTTP request.
 * @param context - Dynamic route parameters containing `shareId`.
 * @returns NextResponse with public report JSON or 404.
 */
export async function GET(
  _request: Request,
  context: { params: Promise<{ shareId: string }> },
) {
  const { shareId } = await context.params;

  // Forward to unauthenticated backend public report endpoint
  const upstream = await fetch(
    `${API_BASE}/api/public/reports/${encodeURIComponent(shareId)}`,
    { cache: "no-store" },
  );

  const payload = await upstream.json().catch(() => ({}));
  return NextResponse.json(payload, { status: upstream.status });
}

