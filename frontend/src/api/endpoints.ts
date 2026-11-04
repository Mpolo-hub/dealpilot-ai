// The four spec 002 endpoints the first release uses (spec 007 sections 3.1 and 4), plus
// `/v1/forecasts` for the Prediction page (spec 003 section 10, D11 approved 2026-11-04;
// spec 007 D14 amendment), as same-origin paths. Nothing else is ever requested, except
// the two Stage 1 access paths in public demo mode (spec 014 JA-FR-05 and JA-FR-08).
import { buildQuery } from "./client";
import type { ForecastQuery, MetricsQuery } from "./types";

export const ACCESS_REDEEM = "/access/redeem";
export const ACCESS_LOGOUT = "/access/logout";
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

/** Only the key parameters of the level are sent (spec 003 section 10 refuses the others). */
export function forecastsPath(query: ForecastQuery): string {
  return "/v1/forecasts" + buildQuery({
    level: query.level,
    category: query.level === "category" ? query.category : undefined,
    product_id: query.level === "product_region" ? query.product_id : undefined,
    region_id: query.level === "product_region" ? query.region_id : undefined,
    cutoff: query.cutoff,
    horizon: String(query.horizon),
  });
}
