// Calendar helpers on ISO dates (YYYY-MM-DD), computed in UTC so the browser's time zone
// never shifts a day. Closed days are the fixed business calendar of spec 001 section 5.7.
import type { IsoDate } from "../api/types";
import { text } from "../text/en";

const ISO = /^\d{4}-\d{2}-\d{2}$/;
const DAY_MS = 86_400_000;
export const CLOSED_DAYS: readonly string[] = ["12-25", "01-01"]; // month-day, spec 001 5.7

export function isIsoDate(text: string): boolean {
  if (!ISO.test(text)) return false;
  const date = new Date(`${text}T00:00:00Z`);
  return !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === text;
}

function toTime(iso: IsoDate): number {
  if (!isIsoDate(iso)) throw new Error(`not an ISO date: ${iso}`);
  return Date.parse(`${iso}T00:00:00Z`);
}

function fromTime(time: number): IsoDate {
  return new Date(time).toISOString().slice(0, 10);
}

export function addDays(iso: IsoDate, days: number): IsoDate {
  return fromTime(toTime(iso) + days * DAY_MS);
}

/** Number of days from `start` to `end`, both included. */
export function daysInclusive(start: IsoDate, end: IsoDate): number {
  return Math.round((toTime(end) - toTime(start)) / DAY_MS) + 1;
}

export function eachDay(start: IsoDate, end: IsoDate): IsoDate[] {
  const out: IsoDate[] = [];
  for (let t = toTime(start), last = toTime(end); t <= last; t += DAY_MS) out.push(fromTime(t));
  return out;
}

export function isOpenDay(iso: IsoDate): boolean {
  return !CLOSED_DAYS.includes(iso.slice(5));
}

/** Open days in the range (spec 001 section 8.1: Dec 25 and Jan 1 left out). */
export function openDays(start: IsoDate, end: IsoDate): number {
  return eachDay(start, end).filter(isOpenDay).length;
}

/** First day of every month that overlaps the range (spec 002 month buckets). */
export function eachMonth(start: IsoDate, end: IsoDate): IsoDate[] {
  const out: IsoDate[] = [];
  let year = Number(start.slice(0, 4));
  let month = Number(start.slice(5, 7));
  const lastKey = end.slice(0, 7);
  for (;;) {
    const key = `${year}-${String(month).padStart(2, "0")}`;
    if (key > lastKey) return out;
    out.push(`${key}-01`);
    month += 1;
    if (month === 13) {
      month = 1;
      year += 1;
    }
  }
}

/** The same calendar date one year earlier; Feb 29 maps to Feb 28 (spec 007 D3). */
export function oneYearEarlier(iso: IsoDate): IsoDate {
  const year = Number(iso.slice(0, 4)) - 1;
  const monthDay = iso.slice(5) === "02-29" ? "02-28" : iso.slice(5);
  return `${year}-${monthDay}`;
}

export function yearsBetween(start: IsoDate, end: IsoDate): number[] {
  const out: number[] = [];
  for (let y = Number(start.slice(0, 4)); y <= Number(end.slice(0, 4)); y += 1) out.push(y);
  return out;
}

export const minDate = (a: IsoDate, b: IsoDate): IsoDate => (a < b ? a : b);
export const maxDate = (a: IsoDate, b: IsoDate): IsoDate => (a > b ? a : b);

/** Short month name from the text catalog: `Jan`. */
export function monthLabel(iso: IsoDate): string {
  return text.formats.months[Number(iso.slice(5, 7)) - 1] ?? iso;
}

/** English date: `Jan 1, 2024`. */
export function formatDate(iso: IsoDate): string {
  return `${monthLabel(iso)} ${Number(iso.slice(8, 10))}, ${iso.slice(0, 4)}`;
}

/** Complete a bucketed series: every bucket gets a value, missing ones 0 (spec 002 D5). */
export function fillBuckets<T extends { date?: IsoDate }>(buckets: IsoDate[], rows: T[],
  value: (row: T) => number): { date: IsoDate; value: number }[] {
  const byDate = new Map<IsoDate, number>();
  for (const row of rows) {
    if (row.date !== undefined) byDate.set(row.date, value(row));
  }
  return buckets.map((date) => ({ date, value: byDate.get(date) ?? 0 }));
}
