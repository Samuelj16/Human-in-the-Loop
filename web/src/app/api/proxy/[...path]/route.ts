/**
 * Next.js Server Route Handler: `/api/proxy/[...path]`
 *
 * Same-Origin Authenticated Proxy to the FastAPI Backend.
 *
 * Architecture & Security:
 *   - The browser sends requests directly to the Next.js origin (`/api/proxy/api/tasks/...`).
 *   - This server-side route handler extracts the JWT from the httpOnly session cookie
 *     and injects it into the upstream request as `Authorization: Bearer <token>`.
 *   - Completely eliminates cross-origin credential issues (CORS cookies) and keeps the raw
 *     JWT invisible to client-side JavaScript.
 *   - Streams upstream binary response bodies verbatim, allowing direct PDF downloads
 *     and dynamic event payloads without buffering.
 */
import { NextRequest, NextResponse } from "next/server";

import { API_BASE, readSessionToken } from "@/lib/session";

type Context = { params: Promise<{ path: string[] }> };

/**
 * Forwards incoming HTTP request to upstream FastAPI server with bearer token authorization.
 *
 * @param request - Next.js Request object.
 * @param context - Dynamic route parameters containing target API path segments.
 * @returns Proxied upstream NextResponse.
 */
async function forward(request: NextRequest, context: Context) {
  const { path } = await context.params;
  const token = await readSessionToken();

  // Reject unauthenticated requests before calling upstream
  if (!token) {
    return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  }

  // Construct target URL including query parameters
  const search = request.nextUrl.search;
  const target = `${API_BASE}/${path.join("/")}${search}`;

  const headers = new Headers();
  headers.set("Authorization", `Bearer ${token}`);
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("Content-Type", contentType);

  const hasBody = request.method !== "GET" && request.method !== "HEAD";

  // Dispatch upstream fetch
  const upstream = await fetch(target, {
    method: request.method,
    headers,
    body: hasBody ? await request.text() : undefined,
    cache: "no-store",
  });

  // Stream the body through untouched so PDF downloads work seamlessly
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

// Export forward handler for all standard HTTP methods
export const GET = forward;
export const POST = forward;
export const PATCH = forward;
export const PUT = forward;
export const DELETE = forward;

