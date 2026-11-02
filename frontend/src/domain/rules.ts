// Business rules approved in spec 007 section 6 (2026-11-01).
import type { IsoDate, Money, Product } from "../api/types";
import { oneYearEarlier, openDays } from "./dates";
import { toCents } from "./money";

/**
 * D3 (option C): compare with the same dates one year earlier. Returns null, so the
 * comparison is hidden, when that period is not fully inside the dataset.
 */
export function comparisonRange(start: IsoDate, end: IsoDate, datasetStart: IsoDate,
  datasetEnd: IsoDate): { start: IsoDate; end: IsoDate } | null {
  const previous = { start: oneYearEarlier(start), end: oneYearEarlier(end) };
  if (previous.start < datasetStart || previous.end > datasetEnd) return null;
  return previous;
}

export type ProductStatus = "active" | "discontinued" | "not_launched";

/**
 * D4 (option B): status on a reference date with the spec 001 section 4 rule: active on
 * day d when launch_date <= d and (no discontinue_date or d < discontinue_date).
 */
export function productStatus(product: Product, reference: IsoDate): ProductStatus {
  if (product.launch_date > reference) return "not_launched";
  if (product.discontinue_date !== null && product.discontinue_date <= reference) {
    return "discontinued";
  }
  return "active";
}

/**
 * D5 (option A): average daily revenue over the open days of the range (spec 001
 * section 8.1). Returns dollars, or null when the range has no open day.
 */
export function averageRevenuePerOpenDay(revenue: Money, start: IsoDate,
  end: IsoDate): number | null {
  const days = openDays(start, end);
  return days === 0 ? null : Number(toCents(revenue)) / 100 / days;
}
