/** Exchanges credentials with the API and stores the returned token server-side. */
import { NextResponse } from "next/server";

import { API_BASE, writeSessionToken } from "@/lib/session";

export async function POST(request: Request) {
  const body = await request.json();

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

  // The token stops here - it is stored httpOnly and never returned to the page.
  await writeSessionToken(payload.access_token);
  return NextResponse.json({ ok: true });
}
