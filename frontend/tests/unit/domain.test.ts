// Business rules and formats (spec 007 sections 6 and 7). Expected values are computed by
// hand or independently here, never by the code under test.
import { describe, expect, it } from "vitest";

import type { Product } from "../../src/api/types";
import {
  addDays, daysInclusive, eachDay, eachMonth, fillBuckets, formatDate, isIsoDate, isOpenDay,
  monthLabel, oneYearEarlier, openDays,
} from "../../src/domain/dates";
import { formatCount } from "../../src/domain/format";
import {
  compareMoney, formatMoney, formatMoneyCompact, moneyChange, moneyShare, toCents, toDollars,
} from "../../src/domain/money";
import { averageRevenuePerOpenDay, comparisonRange, productStatus } from "../../src/domain/rules";
import { monthTicks } from "../../src/pages/pageState";
import { text } from "../../src/text/en";

describe("money (FR-02)", () => {
  it("keeps exact cents from the API string", () => {
    expect(toCents("2026466.37")).toBe(202646637n);
    expect(toCents("0.00")).toBe(0n);
    expect(() => toCents("12.5")).toThrow();
    expect(() => toCents("-1.00")).toThrow();
    expect(() => toCents("1e3")).toThrow();
  });

  it("formats exact and compact English amounts", () => {
    expect(formatMoney("2026466.37")).toBe("$2,026,466.37");
    expect(formatMoney("123456789012345.01")).toBe("$123,456,789,012,345.01");
    expect(formatMoneyCompact(12_500_000)).toBe("$12.5M");
    expect(formatMoneyCompact(482_000)).toBe("$482K");
    expect(formatMoneyCompact(3_000_000)).toBe("$3M");
    expect(formatMoneyCompact(950)).toBe("$950");
    expect(formatCount(152840)).toBe("152,840");
  });

  it("compares, shares and changes without float sums", () => {
    expect(compareMoney("10.01", "10.00")).toBe(1);
    expect(compareMoney("9.99", "10.00")).toBe(-1);
    expect(moneyShare("25.00", "100.00")).toBe(0.25);
    expect(moneyShare("1.00", "0.00")).toBeNull();
    expect(moneyChange("112.30", "100.00")).toBeCloseTo(0.123, 12);
    expect(moneyChange("5.00", "0.00")).toBeNull();
    expect(toDollars("0.10") + toDollars("0.20")).toBeCloseTo(0.3, 12);
  });
});

describe("dates", () => {
  it("validates strict ISO dates", () => {
    expect(isIsoDate("2024-02-29")).toBe(true);
    expect(isIsoDate("2023-02-29")).toBe(false);
    expect(isIsoDate("20240101")).toBe(false);
    expect(isIsoDate("2024-1-01")).toBe(false);
  });

  it("counts days, open days and buckets", () => {
    expect(daysInclusive("2023-01-01", "2025-12-31")).toBe(1096);
    expect(eachDay("2024-02-27", "2024-03-01")).toEqual(
      ["2024-02-27", "2024-02-28", "2024-02-29", "2024-03-01"]);
    expect(addDays("2024-12-31", 1)).toBe("2025-01-01");
    // Dec 20 2024 to Jan 5 2025: 17 days, of which Dec 25 and Jan 1 are closed.
    expect(openDays("2024-12-20", "2025-01-05")).toBe(15);
    expect(isOpenDay("2024-12-25")).toBe(false);
    expect(isOpenDay("2025-01-01")).toBe(false);
    expect(isOpenDay("2024-12-24")).toBe(true);
    expect(eachMonth("2024-11-15", "2025-02-02")).toEqual(
      ["2024-11-01", "2024-12-01", "2025-01-01", "2025-02-01"]);
    expect(formatDate("2024-01-01")).toBe("Jan 1, 2024");
  });

  it("fills missing buckets with zero (spec 002 D5)", () => {
    const filled = fillBuckets(["2024-12-24", "2024-12-25", "2024-12-26"],
      [{ date: "2024-12-24", v: 3 }, { date: "2024-12-26", v: 4 }], (r: { v: number }) => r.v);
    expect(filled).toEqual([{ date: "2024-12-24", value: 3 }, { date: "2024-12-25", value: 0 },
      { date: "2024-12-26", value: 4 }]);
  });
});

describe("D3: same period last year", () => {
  const ds = { start: "2023-01-01", end: "2025-12-31" };

  it("maps dates one year back, Feb 29 to Feb 28", () => {
    expect(oneYearEarlier("2024-03-15")).toBe("2023-03-15");
    expect(oneYearEarlier("2024-02-29")).toBe("2023-02-28");
  });

  it("is available only when fully inside the dataset", () => {
    expect(comparisonRange(ds.start, ds.end, ds.start, ds.end)).toBeNull(); // default range
    expect(comparisonRange("2024-01-01", "2024-12-31", ds.start, ds.end))
      .toEqual({ start: "2023-01-01", end: "2023-12-31" });
    expect(comparisonRange("2023-06-01", "2023-07-01", ds.start, ds.end)).toBeNull();
    expect(comparisonRange("2023-12-31", "2024-01-31", ds.start, ds.end)).toBeNull();
    expect(comparisonRange("2024-01-01", "2024-02-29", ds.start, ds.end))
      .toEqual({ start: "2023-01-01", end: "2023-02-28" });
  });
});

describe("D4: product status (spec 001 section 4)", () => {
  const product = (launch: string, stop: string | null): Product => ({
    product_id: "P1", name: "x", category: "c", launch_date: launch, discontinue_date: stop });

  it("uses launch <= d and (no stop or d < stop)", () => {
    expect(productStatus(product("2024-01-10", null), "2024-01-09")).toBe("not_launched");
    expect(productStatus(product("2024-01-10", null), "2024-01-10")).toBe("active");
    expect(productStatus(product("2023-01-01", "2024-07-06"), "2024-07-05")).toBe("active");
    expect(productStatus(product("2023-01-01", "2024-07-06"), "2024-07-06")).toBe("discontinued");
  });
});

describe("D5: average revenue per open day", () => {
  it("divides by open days counted independently (AC-UI-17)", () => {
    // 2024-12-20 to 2025-01-05: 15 open days.
    expect(averageRevenuePerOpenDay("1500.00", "2024-12-20", "2025-01-05")).toBe(100);
    expect(averageRevenuePerOpenDay("10.00", "2024-12-25", "2024-12-25")).toBeNull();
  });
});

// R-02 (AC-UI-11): month names and number formats have one source, `text/en.ts`. The
// visible output stays the same English text as before. The currency is data (spec 002
// section 3.3) and is named once, in domain/money.ts.
const SOURCES = import.meta.glob(["../../src/**/*.{ts,tsx}", "!../../src/text/en.ts"],
  { query: "?raw", import: "default", eager: true }) as Record<string, string>;
// SVG path commands ("M", "L") in components/charts are not compact suffixes, so the
// suffix rule applies only to the modules that format amounts.
const FORMATTING = /\/src\/(domain|pages)\//;

describe("formats come from text/en.ts (AC-UI-11)", () => {
  it("no month name, locale tag, currency or compact suffix is written outside the catalog", () => {
    expect(Object.keys(SOURCES).some((path) => path.includes("/src/components/"))).toBe(true);
    for (const [path, source] of Object.entries(SOURCES)) {
      expect(source, path).not.toMatch(/["'](Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)["']/);
      expect(source, path).not.toMatch(/["']en-US["']/);
      expect(source, path).not.toMatch(/toLocaleString\(\)/);
      expect(source, path).not.toMatch(/`\$\$\{/);
      if (!path.endsWith("/src/domain/money.ts")) expect(source, path).not.toMatch(/["']USD["']/);
      if (FORMATTING.test(path)) expect(source, path).not.toMatch(/["'][KMB]["']/);
    }
  });

  it("the catalog holds the same English formats as before", () => {
    const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    expect([...text.formats.months]).toEqual(months);
    expect(months.map((_, i) => monthLabel(`2024-${String(i + 1).padStart(2, "0")}-01`))).toEqual(months);
    expect(text.formats.locale).toBe("en-US");
    expect(text.formats).not.toHaveProperty("currency");
    expect(text.formats.compactSuffixes).toEqual({ thousand: "K", million: "M", billion: "B" });
    // The symbol comes from the USD currency code, on both the compact and the exact paths.
    expect(formatMoneyCompact(2_500_000_000)).toBe("$2.5B");
    expect(formatMoneyCompact(482_000)).toBe("$482K");
    expect(formatMoneyCompact(950)).toBe("$950");
    expect(formatMoney("2026466.37")).toBe("$2,026,466.37");
    // Negative compact amounts never occur in RC1 (revenue, averages and axes are >= 0), and
    // spec 007 defines no negative money format, so no negative form is asserted here.
    expect(formatMoneyCompact(12.4)).toBe("$12");
    expect(monthTicks(["2023-12-31", "2024-01-01", "2024-01-02", "2024-02-01"]))
      .toEqual([{ index: 1, label: "Jan 2024" }, { index: 3, label: "Feb 2024" }]);
  });
});
