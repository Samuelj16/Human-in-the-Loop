/**
 * Same-origin proxy to the FastAPI backend.
 *
 * The browser talks only to this app; this handler attaches the session token
 * server-side. That keeps the JWT out of client JavaScript, removes the need
 * for cross-site cookies, and means the API's address is never a public value.
 */
import { NextRequest, NextResponse } from "next/server";

import { API_BASE, readSessionToken } from "@/lib/session";

type Context = { params: Promise<{ path: string[] }> };

async function forward(request: NextRequest, context: Context) {
  const { path } = await context.params;
  const token = await readSessionToken();

  if (!token) {
    return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  }

  const search = request.nextUrl.search;
  const target = `${API_BASE}/${path.join("/")}${search}`;

  const headers = new Headers();
  headers.set("Authorization", `Bearer ${token}`);
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("Content-Type", contentType);

  const hasBody = request.method !== "GET" && request.method !== "HEAD";

  const upstream = await fetch(target, {
    method: request.method,
    headers,
    body: hasBody ? await request.text() : undefined,
    cache: "no-store",
  });

  // Stream the body through untouched so PDF downloads work like any other route.
  const responseHeaders = new Headers();
  for (const header of ["content-type", "content-disposition", "retry-after"]) {
    const value = upstream.headers.get(header);
    if (value) responseHeaders.set(header, value);
  }

  return new NextResponse(upstream.body, {
    status: upstream.status,
    headers: responseHeaders,
  });
}

export const GET = forward;
export const POST = forward;
export const PATCH = forward;
export const PUT = forward;
export const DELETE = forward;
