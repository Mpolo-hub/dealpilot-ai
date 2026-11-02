// Page helpers that are not components (kept apart for fast refresh).
import { isDataUnavailable } from "../api/errors";
import type { ApiState } from "../hooks/useApi";

/** True when any request answered 503 data_unavailable: the page shows that view (FR-06). */
export function anyDataUnavailable(states: ApiState<unknown>[]): boolean {
  return states.some((s) => s.status === "error" && isDataUnavailable(s.error));
}

/** Month ticks for a daily axis: at most `max` labels, e.g. "Jan 2024". */
export function monthTicks(days: string[], max = 8): { index: number; label: string }[] {
  const starts = days.map((d, index) => ({ d, index })).filter(({ d }) => d.endsWith("-01"));
  const step = Math.max(1, Math.ceil(starts.length / max));
  const names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return starts.filter((_, i) => i % step === 0).map(({ d, index }) => ({
    index, label: `${names[Number(d.slice(5, 7)) - 1]} ${d.slice(0, 4)}`,
  }));
}
