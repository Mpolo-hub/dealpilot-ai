// Money (spec 002 section 3.3, spec 007 FR-02). Values stay decimal strings from the API;
// they become integer cents (BigInt, exact) for comparisons and are turned into floating
// numbers only to divide for display (shares, averages, percent changes).
import type { Money } from "../api/types";

const MONEY = /^[0-9]+\.[0-9]{2}$/;

export function toCents(value: Money): bigint {
  if (!MONEY.test(value)) throw new Error(`not a money string: ${value}`);
  return BigInt(value.replace(".", ""));
}

export function compareMoney(a: Money, b: Money): number {
  const diff = toCents(a) - toCents(b);
  return diff > 0n ? 1 : diff < 0n ? -1 : 0;
}

/** Dollars as a float, for chart geometry and display arithmetic only. */
export function toDollars(value: Money): number {
  return Number(toCents(value)) / 100;
}

const exact = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });

/** Exact amount with cents, for tooltips and tables: `$2,026,466.37`. */
export function formatMoney(value: Money): string {
  const cents = toCents(value);
  const dollars = cents / 100n;
  const rest = (cents % 100n).toString().padStart(2, "0");
  return `$${dollars.toLocaleString("en-US")}.${rest}`;
}

/** Short amount for cards and axes: `$12.5M`, `$482K`, `$950`. */
export function formatMoneyCompact(dollars: number): string {
  const abs = Math.abs(dollars);
  const units: [number, string][] = [[1e9, "B"], [1e6, "M"], [1e3, "K"]];
  for (const [size, suffix] of units) {
    if (abs >= size) {
      const scaled = dollars / size;
      const digits = Math.abs(scaled) >= 100 ? 0 : 1;
      return `$${scaled.toFixed(digits).replace(/\.0$/, "")}${suffix}`;
    }
  }
  return exact.format(Math.round(dollars)).replace(/\.00$/, "");
}

/** part / total as a fraction; null when the total is zero. */
export function moneyShare(part: Money, total: Money): number | null {
  const whole = toCents(total);
  return whole === 0n ? null : Number(toCents(part)) / Number(whole);
}

/** (current - previous) / previous; null when the previous amount is zero. */
export function moneyChange(current: Money, previous: Money): number | null {
  const before = toCents(previous);
  if (before === 0n) return null;
  return Number(toCents(current) - before) / Number(before);
}
