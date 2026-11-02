// Date range validation (spec 007 FR-07): valid dates, start <= end, inside the dataset.
import type { IsoDate } from "../api/types";
import { text } from "../text/en";
import { formatDate, isIsoDate } from "./dates";

export interface Range {
  start: IsoDate;
  end: IsoDate;
}

export function validateRange(start: string, end: string, dataset: Range): string | null {
  if (!isIsoDate(start) || !isIsoDate(end)) return text.validation.invalidDate;
  if (start > end) return text.validation.startAfterEnd;
  if (start < dataset.start || end > dataset.end) {
    return text.validation.outOfRange(formatDate(dataset.start), formatDate(dataset.end));
  }
  return null;
}
