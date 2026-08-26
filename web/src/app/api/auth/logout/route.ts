/**
 * Next.js Server Route Handler: `/api/auth/logout`
 *
 * Invalidate user authentication by clearing the `hitl_session` httpOnly cookie.
 */
import { NextResponse } from "next/server";

import { clearSessionToken } from "@/lib/session";

/**
 * Handle user logout request.
 *
 * @returns NextResponse with status 200 acknowledging session termination.
 */
export async function POST() {
  await clearSessionToken();
  return NextResponse.json({ ok: true });
}

