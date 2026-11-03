// Demo session events (spec 007 A7-H1; spec 014 Annex D, S1-D13 amended 2026-11-04):
// - "ended": a `/v1` request answered 401 (the session expired or was revoked);
// - "signedOut": the user signed out;
// - "signedIn": an invitation was redeemed (Login page or invitation link).
// The browser never sees the session itself: it is an HttpOnly cookie.
type Listener = () => void;
type SessionEvent = "ended" | "signedOut" | "signedIn";

const listeners: Record<SessionEvent, Set<Listener>> = {
  ended: new Set(), signedOut: new Set(), signedIn: new Set(),
};

function subscribe(event: SessionEvent, listener: Listener): () => void {
  listeners[event].add(listener);
  return () => {
    listeners[event].delete(listener);
  };
}

function emit(event: SessionEvent): void {
  for (const listener of [...listeners[event]]) listener();
}

/** Subscribe to "the session ended" (401); returns the function that unsubscribes. */
export const onSessionEnded = (listener: Listener) => subscribe("ended", listener);
export const notifySessionEnded = () => emit("ended");
export const onSignedOut = (listener: Listener) => subscribe("signedOut", listener);
export const notifySignedOut = () => emit("signedOut");
export const onSignedIn = (listener: Listener) => subscribe("signedIn", listener);
export const notifySignedIn = () => emit("signedIn");
