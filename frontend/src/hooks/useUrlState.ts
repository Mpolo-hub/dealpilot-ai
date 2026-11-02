// URL-based state (spec 007 FR-07, D7): range, tab, filters and year live in the query
// string, so a view can be bookmarked and reloaded. Nothing is stored in the browser.
import { useCallback } from "react";
import { useSearchParams } from "react-router";

import type { Range } from "../domain/range";
import { isIsoDate } from "../domain/dates";

export function useUrlParam(name: string): [string | null, (value: string | null) => void] {
  const [params, setParams] = useSearchParams();
  const set = useCallback((value: string | null) => {
    setParams((current) => {
      const next = new URLSearchParams(current);
      if (value === null || value === "") next.delete(name);
      else next.set(name, value);
      return next;
    }, { replace: false });
  }, [name, setParams]);
  return [params.get(name), set];
}

export type { Range };

/** The page's date range: the URL values when valid and inside the dataset, else the default. */
export function useUrlRange(dataset: Range | null): [Range | null, (range: Range | null) => void] {
  const [params, setParams] = useSearchParams();
  const set = useCallback((range: Range | null) => {
    setParams((current) => {
      const next = new URLSearchParams(current);
      next.delete("start");
      next.delete("end");
      if (range !== null) {
        next.set("start", range.start);
        next.set("end", range.end);
      }
      return next;
    });
  }, [setParams]);
  if (dataset === null) return [null, set];
  const start = params.get("start");
  const end = params.get("end");
  const valid = start !== null && end !== null && isIsoDate(start) && isIsoDate(end)
    && start <= end && start >= dataset.start && end <= dataset.end;
  return [valid ? { start, end } : dataset, set];
}
