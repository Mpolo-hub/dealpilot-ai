// The four spec 002 endpoints the first release uses (spec 007 section 8), as same-origin
// paths. Nothing else is ever requested.
import { buildQuery } from "./client";
import type { MetricsQuery } from "./types";

export const HEALTH = "/health";
export const METADATA = "/v1/metadata";
export const DIMENSIONS = "/v1/dimensions";

export function metricsPath(query: MetricsQuery): string {
  if (query.group_by?.includes("date") && query.group_by.length > 1) {
    // FR-04: date buckets are never combined with other groups, so no request can
    // approach the 20,000-group limit (spec 002 D6).
    throw new Error("date buckets are never combined with other groups");
  }
  return "/v1/sales/metrics" + buildQuery({
    start: query.start,
    end: query.end,
    group_by: query.group_by,
    interval: query.interval,
    product_id: query.product_id,
    category: query.category,
    region_id: query.region_id,
  });
}
