/**
 * Server-side session management and secure cookie handlers.
 *
 * Security Architecture:
 *   - The backend FastAPI JWT bearer token never reaches client-side JavaScript.
 *   - It is encapsulated in an `httpOnly`, `sameSite: "lax"` cookie named `hitl_session`
 *     on the Next.js origin.
 *   - Server route handlers (`/api/auth/*` and `/api/proxy/*`) read the cookie and
 *     forward it as an `Authorization: Bearer <token>` header to FastAPI.
 *   - Prevents XSS-based token exfiltration and eliminates cross-origin cookie blocking issues.
 */
import { cookies } from "next/headers";

/** Name of the secure httpOnly session cookie */
export const SESSION_COOKIE = "hitl_session";

/** Session lifetime duration (7 days in seconds) */
const SEVEN_DAYS_IN_SECONDS = 60 * 60 * 24 * 7;

/**
 * Resolved backend API base URL.
 * Prefers server-side `API_URL` environment variable, falling back to public URL or localhost.
 */
export const API_BASE = (
  process.env.API_URL ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8000"
).replace(/\/$/, "");

/**
 * Read the current session JWT token from incoming request cookies on the server.
 *
 * @returns The JWT string if present, or undefined if unauthenticated.
 */
export async function readSessionToken(): Promise<string | undefined> {
  const store = await cookies();
  return store.get(SESSION_COOKIE)?.value;
}

/**
 * Persist an access token into the httpOnly session cookie.
 *
 * @param token - The raw JWT bearer string received from FastAPI.
 */
export async function writeSessionToken(token: string): Promise<void> {
  const store = await cookies();
  store.set(SESSION_COOKIE, token, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: SEVEN_DAYS_IN_SECONDS,
  });
}

/**
 * Invalidate and remove the session cookie upon user sign-out.
 */
export async function clearSessionToken(): Promise<void> {
  const store = await cookies();
  store.delete(SESSION_COOKIE);
}

