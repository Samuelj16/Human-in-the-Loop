/**
 * Next.js Server Route Handler: `/api/auth/login`
 *
 * Authenticates user credentials with FastAPI backend, storing the returned
 * JWT access token in an `httpOnly` cookie.
 *
 * Security Guarantee:
 *   - The raw access token stops here on the server; client-side JS receives `{ ok: true }`.
 */
import { NextResponse } from "next/server";

import { API_BASE, writeSessionToken } from "@/lib/session";

/**
 * Authenticate credentials and establish server session.
 *
 * @param request - Incoming request with email and password payload.
 * @returns NextResponse with status 200 on success or error details on failure.
 */
export async function POST(request: Request) {
  const body = await request.json();

  // Forward credentials to FastAPI login endpoint
  const upstream = await fetch(`${API_BASE}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });

  const payload = await upstream.json().catch(() => ({}));

  if (!upstream.ok) {
    return NextResponse.json(
      { detail: payload.detail ?? "Login failed" },
      { status: upstream.status },
    );
  }

  // Token is stored in httpOnly cookie and never exposed to browser scripts
  await writeSessionToken(payload.access_token);
  return NextResponse.json({ ok: true });
}

