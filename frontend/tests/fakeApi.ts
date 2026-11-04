// A small stand-in for the spec 002 API, used by the page tests. It follows the documented
// contract (spec 002 section 5): only groups with sales, exact money strings, distinct
// order counts, repeated-key filters, and the error body. Its data is hand-made and much
// smaller than the seed 42 dataset.
import { vi } from "vitest";

import type { Dimensions, Metadata, MetricsRow } from "../src/api/types";

export const DATASET = { start: "2023-01-01", end: "2024-12-31" };

export const DIMENSIONS: Dimensions = {
  date_range: DATASET,
  group_by: ["date", "product", "category", "region"],
  intervals: ["day", "week", "month"],
  metrics: ["units", "revenue", "orders", "order_lines"],
  regions: [{ region_id: "R01", name: "North" }, { region_id: "R02", name: "South" },
    { region_id: "R03", name: "East" }],
  categories: ["Home", "Toys"],
  products: [
    { product_id: "P001", name: "Nova Lamp", category: "Home", launch_date: "2023-01-01", discontinue_date: null },
    { product_id: "P002", name: "Halo Chair", category: "Home", launch_date: "2023-01-01", discontinue_date: "2024-03-01" },
    { product_id: "P003", name: "Kite Set", category: "Toys", launch_date: "2024-06-01", discontinue_date: null },
    { product_id: "P004", name: "Puzzle Box", category: "Toys", launch_date: "2023-01-01", discontinue_date: null },
  ],
};

export const METADATA: Metadata = {
  seed: 42, start: DATASET.start, end: DATASET.end, generator_version: "0.1.0",
  library_versions: { python: "3.13.17", numpy: "2.5.4", pyarrow: "26.0.0" },
  row_counts: { regions: 3, products: 4, customers: 2000, promotions: 40, orders: 6,
    order_lines: 8, expected_demand: 2920 },
};

// order_id, date, region, product, units, revenue in cents. P004 never sells; R03 never sells.
export const LINES: [string, string, string, string, number, number][] = [
  ["O1", "2023-03-10", "R01", "P001", 2, 2_000_00],
  ["O1", "2023-03-10", "R01", "P002", 1, 50_00],
  ["O2", "2023-07-04", "R02", "P001", 1, 1_000_00],
  ["O3", "2024-03-10", "R01", "P001", 3, 3_000_00],
  ["O4", "2024-03-11", "R02", "P002", 4, 200_00],
  ["O5", "2024-07-20", "R01", "P003", 5, 1_234_567_89],
  ["O5", "2024-07-20", "R01", "P001", 1, 1_000_01],
  ["O6", "2024-12-30", "R02", "P003", 1, 99],
];

const money = (cents: number) => `${Math.floor(cents / 100)}.${String(cents % 100).padStart(2, "0")}`;
const category = (id: string) => DIMENSIONS.products.find((p) => p.product_id === id)?.category ?? "";

function bucket(date: string, interval: string): string {
  if (interval === "month") return `${date.slice(0, 7)}-01`;
  if (interval === "week") {
    const d = new Date(`${date}T00:00:00Z`);
    d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7));
    return d.toISOString().slice(0, 10);
  }
  return date;
}

function error(status: number, code: string, message = "") {
  return new Response(JSON.stringify({ error: { code, message, details: [] } }), { status });
}

export function metrics(url: URL): Response {
  const p = url.searchParams;
  const allowed = ["start", "end", "group_by", "interval", "product_id", "category", "region_id"];
  if ([...p.keys()].some((k) => !allowed.includes(k))) return error(422, "unknown_parameter");
  const start = p.get("start") ?? DATASET.start;
  const end = p.get("end") ?? DATASET.end;
  if (start < DATASET.start || end > DATASET.end) return error(422, "date_out_of_range");
  const groupBy = p.getAll("group_by");
  const interval = p.get("interval") ?? "day";
  const lines = LINES.filter(([, date, region, product]) => date >= start && date <= end
    && (!p.getAll("product_id").length || p.getAll("product_id").includes(product))
    && (!p.getAll("category").length || p.getAll("category").includes(category(product)))
    && (!p.getAll("region_id").length || p.getAll("region_id").includes(region)));
  const sum = (group: typeof lines) => ({
    units: group.reduce((s, l) => s + l[4], 0), revenue: money(group.reduce((s, l) => s + l[5], 0)),
    orders: new Set(group.map((l) => l[0])).size, order_lines: group.length,
  });
  const groups = new Map<string, { key: Record<string, string>; lines: typeof lines }>();
  for (const line of groupBy.length ? lines : []) {
    const key: Record<string, string> = {};
    for (const g of groupBy) {
      if (g === "date") key.date = bucket(line[1], interval);
      if (g === "product") key.product_id = line[3];
      if (g === "category") key.category = category(line[3]);
      if (g === "region") key.region_id = line[2];
    }
    const id = JSON.stringify(key);
    if (!groups.has(id)) groups.set(id, { key, lines: [] });
    groups.get(id)!.lines.push(line);
  }
  const rows: MetricsRow[] = [...groups.values()].map((g) => ({ ...g.key, ...sum(g.lines) }))
    .sort((a, b) => JSON.stringify(Object.values(a)).localeCompare(JSON.stringify(Object.values(b))));
  return Response.json({
    start, end, group_by: groupBy, interval: groupBy.includes("date") ? interval : null,
    filters: { product_id: p.getAll("product_id"), category: p.getAll("category"), region_id: p.getAll("region_id") },
    metrics: ["units", "revenue", "orders", "order_lines"], rows, totals: sum(lines), row_count: rows.length,
  });
}

/** GET /v1/forecasts (spec 003 section 10): seasonal naive over the hand-made lines, with
 * the weekly fallback for closed source days. Key parameters are not validated here. */
export function forecasts(url: URL): Response {
  const p = url.searchParams;
  const level = p.get("level");
  const cutoff = p.get("cutoff") ?? DATASET.end;
  const horizon = Number(p.get("horizon") ?? "28");
  if (!level) return error(422, "invalid_parameter");
  const keep = (line: (typeof LINES)[number]) => (level === "total"
    || (level === "category" && category(line[3]) === p.get("category"))
    || (level === "product_region" && line[3] === p.get("product_id") && line[2] === p.get("region_id")))
    && line[1] <= cutoff;
  const units = new Map<string, number>();
  for (const line of LINES.filter(keep)) units.set(line[1], (units.get(line[1]) ?? 0) + line[4]);
  const shift = (iso: string, days: number) =>
    new Date(Date.parse(`${iso}T00:00:00Z`) + days * 86_400_000).toISOString().slice(0, 10);
  const closed = (iso: string) => ["12-25", "01-01"].includes(iso.slice(5));
  const points = [];
  for (let h = 1; h <= horizon; h += 1) {
    let source = shift(cutoff, -6 + ((h - 1) % 7));
    while (source >= DATASET.start && closed(source)) source = shift(source, -7);
    points.push({ date: shift(cutoff, h), forecast: source >= DATASET.start ? units.get(source) ?? 0 : 0,
      lower_80: null, upper_80: null });
  }
  const key = level === "category" ? { category: p.get("category") }
    : level === "product_region" ? { product_id: p.get("product_id"), region_id: p.get("region_id") } : {};
  return Response.json({
    level, key, cutoff, horizon,
    model: { name: "seasonal_naive", version: "1.0", settings: { lag_days: 7, closed_day_fallback: "weekly" } },
    uses_planned_promotions: false, points,
  });
}

export type Override = (url: URL) => Response | Promise<Response> | undefined;

/** Replace `fetch` with the fake API; returns the list of requested paths (with query). */
export function installFakeApi(override?: Override): string[] {
  const requested: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: string) => {
    requested.push(input);
    const url = new URL(input, "http://127.0.0.1:5173");
    const custom = override?.(url);
    if (custom) return custom;
    if (url.pathname === "/health") return Response.json({ status: "ok", version: "0.1.0" });
    if (url.pathname === "/v1/metadata") return Response.json(METADATA);
    if (url.pathname === "/v1/dimensions") return Response.json(DIMENSIONS);
    if (url.pathname === "/v1/sales/metrics") return metrics(url);
    if (url.pathname === "/v1/forecasts") return forecasts(url);
    return error(404, "not_found");
  }));
  return requested;
}

export const errorResponse = error;
