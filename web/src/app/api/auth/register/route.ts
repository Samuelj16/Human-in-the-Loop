/** Proxies registration and establishes the same protected session used by login. */
import { NextResponse } from "next/server";

import { API_BASE, writeSessionToken } from "@/lib/session";

export async function POST(request: Request) {
  const body = await request.json();

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

  // The token stops here - it is stored httpOnly and never returned to the page.
  await writeSessionToken(payload.access_token);
  return NextResponse.json({ ok: true });
}
