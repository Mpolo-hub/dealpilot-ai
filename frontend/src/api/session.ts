// Tells the app that the demo session has ended (spec 007 A7-H1, S1-b): the client calls
// it when a `/v1` request answers 401, and the sign-out button calls it after logout.
type Listener = () => void;

const listeners = new Set<Listener>();

/** Subscribe; returns the function that unsubscribes. */
export function onSessionEnded(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function notifySessionEnded(): void {
  for (const listener of [...listeners]) listener();
}
