/**
 * Server-side session handling.
 *
 * The API's JWT never reaches client JavaScript: it lives in an httpOnly
 * cookie on this app's own origin, and only route handlers on the server read
 * it back out to call the API. A cross-site scripting bug can therefore not
 * exfiltrate a login, and there are no third-party cookies to be blocked.
 */
import { cookies } from "next/headers";

export const SESSION_COOKIE = "hitl_session";
const SEVEN_DAYS_IN_SECONDS = 60 * 60 * 24 * 7;

export const API_BASE = (
  process.env.API_URL ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8000"
).replace(/\/$/, "");

export async function readSessionToken(): Promise<string | undefined> {
  const store = await cookies();
  return store.get(SESSION_COOKIE)?.value;
}

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

export async function clearSessionToken(): Promise<void> {
  const store = await cookies();
  store.delete(SESSION_COOKIE);
}
