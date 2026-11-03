// Invitation redemption shared by the invitation link page (/access) and the Login page
// (/login): spec 014 JA-FR-05, POST /access/redeem with {token}. The token is held only in
// memory for the request; it is never stored in localStorage, sessionStorage or the URL.
import { ApiError, NetworkError, postJson } from "./client";
import { ACCESS_REDEEM } from "./endpoints";
import { isRateLimited } from "./errors";
import { notifySignedIn } from "./session";

export type AccessFailure = "invalid" | "rateLimited" | "unavailable";

/** Redeem the token; on success the app is told the user is signed in. */
export async function redeemInvitation(token: string): Promise<void> {
  await postJson(ACCESS_REDEEM, { token });
  notifySignedIn();
}

/**
 * Map a redemption error to what the user may be told. Invalid, expired and revoked
 * invitations get ONE generic answer (the backend never tells them apart).
 */
export function accessFailure(error: unknown): AccessFailure {
  if (isRateLimited(error)) return "rateLimited";
  if (error instanceof NetworkError) return "unavailable";
  if (error instanceof ApiError && error.status >= 500) return "unavailable";
  return "invalid";
}

/** The code from what was typed: a bare code, or a full link whose code follows `#`. */
export function extractCode(input: string): string {
  const value = input.trim();
  const hash = value.lastIndexOf("#");
  return (hash >= 0 ? value.slice(hash + 1) : value).trim();
}
