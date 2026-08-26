/**
 * Next.js Server Route Handler: `/api/auth/register`
 *
 * Handles account creation by proxying credentials to the FastAPI backend
 * and securely intercepting the returned JWT to store in an `httpOnly` cookie.
 *
 * Security Guarantee:
 *   - The raw access token stops here on the server; the browser only receives `{ ok: true }`.
 */
import { NextResponse } from "next/server";

import { API_BASE, writeSessionToken } from "@/lib/session";

/**
 * Handle user registration request.
 *
 * @param request - Incoming Next.js Request with email and password in JSON body.
 * @returns NextResponse with status 200 or upstream error detail.
 */
export async function POST(request: Request) {
  const body = await request.json();

  // Forward credentials to backend registration endpoint
  const upstream = await fetch(`${API_BASE}/api/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });

  const payload = await upstream.json().catch(() => ({}));

  if (!upstream.ok) {
    return NextResponse.json(
      { detail: payload.detail ?? "Registration failed" },
      { status: upstream.status },
    );
  }

  // Token interception: Encapsulate in httpOnly cookie so client JS never touches it
  await writeSessionToken(payload.access_token);
  return NextResponse.json({ ok: true });
}

