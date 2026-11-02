// Row order of the Data overview table (spec 007 section 5.4).
const ORDER = ["regions", "products", "customers", "promotions", "orders", "order_lines",
  "expected_demand"];

export function tableRows(counts: Record<string, number>): { table: string; rows: number }[] {
  const known = ORDER.filter((name) => name in counts);
  const others = Object.keys(counts).filter((name) => !ORDER.includes(name)).sort();
  return [...known, ...others].map((table) => ({ table, rows: counts[table] ?? 0 }));
}
