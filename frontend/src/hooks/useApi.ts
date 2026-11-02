// Loads one API path (spec 007 section 12.4). A new path cancels the older request
// (FR-08), so a late answer never overwrites a newer one. Answers are cached in memory
// for the page load only (D7: nothing persisted). `null` means "nothing to load yet".
import { useEffect, useState } from "react";

import { getJson } from "../api/client";

export type ApiState<T> =
  | { status: "loading" }
  | { status: "ready"; data: T }
  | { status: "error"; error: unknown };

const cache = new Map<string, unknown>();

export function clearApiCache(): void {
  cache.clear();
}

export function useApi<T>(path: string | null): [ApiState<T>, () => void] {
  const [failures, setFailures] = useState<Map<string, unknown>>(() => new Map());
  const [, setLoaded] = useState(0);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (path === null || cache.has(path)) return undefined;
    const controller = new AbortController();
    getJson<T>(path, controller.signal).then(
      (data) => {
        if (controller.signal.aborted) return;
        cache.set(path, data);
        setLoaded((n) => n + 1);
      },
      (error: unknown) => {
        if (controller.signal.aborted) return;
        setFailures((current) => new Map(current).set(path, error));
      },
    );
    return () => controller.abort();
  }, [path, attempt]);

  const retry = () => {
    if (path === null) return;
    setFailures((current) => {
      const next = new Map(current);
      next.delete(path);
      return next;
    });
    setAttempt((n) => n + 1);
  };

  if (path === null) return [{ status: "loading" }, retry];
  if (cache.has(path)) return [{ status: "ready", data: cache.get(path) as T }, retry];
  if (failures.has(path)) return [{ status: "error", error: failures.get(path) }, retry];
  return [{ status: "loading" }, retry];
}
