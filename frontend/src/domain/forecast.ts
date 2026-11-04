// Prediction page rules (spec 007 D14 amendment, 2026-11-04): the table rows, the KPI sums
// and the percent changes. Pure functions over the API answers; nothing is invented.
import type { ForecastPoint, IsoDate } from "../api/types";
import { addDays, maxDate } from "./dates";

export const HORIZONS = [7, 14, 21, 28] as const;
export const HISTORY_DAYS = 28;

export interface ForecastRow {
  date: IsoDate;
  actual: number | null; // null: no observed value (after the dataset end)
  forecast: number;
  difference: number | null; // forecast minus actual
  absError: number | null;
  ape: number | null; // |F - A| / A; null when there is no actual or A = 0
}

/** Daily units by date, from `/v1/sales/metrics?group_by=date` rows (missing days are 0). */
export function unitsByDate(rows: { date?: IsoDate; units: number }[]): Map<IsoDate, number> {
  const out = new Map<IsoDate, number>();
  for (const row of rows) if (row.date !== undefined) out.set(row.date, row.units);
  return out;
}

/** The actual for a day: 0 when the day is inside the dataset without sales (spec 002
 * D5), null when the day is after the dataset end. */
export function actualOn(units: Map<IsoDate, number>, date: IsoDate, datasetEnd: IsoDate): number | null {
  if (date > datasetEnd) return null;
  return units.get(date) ?? 0;
}

export function forecastRows(points: ForecastPoint[], units: Map<IsoDate, number>,
  datasetEnd: IsoDate): ForecastRow[] {
  return points.map((point) => {
    const actual = actualOn(units, point.date, datasetEnd);
    const difference = actual === null ? null : point.forecast - actual;
    const absError = difference === null ? null : Math.abs(difference);
    const ape = actual === null || actual === 0 || absError === null ? null : absError / actual;
    return { date: point.date, actual, forecast: point.forecast, difference, absError, ape };
  });
}

/** Sum of daily units from `first` to `last`, or null if part of it lies before `start`. */
export function windowSum(units: Map<IsoDate, number>, first: IsoDate, last: IsoDate,
  datasetStart: IsoDate): number | null {
  if (first < datasetStart) return null;
  let sum = 0;
  for (let day = first; day <= last; day = addDays(day, 1)) sum += units.get(day) ?? 0;
  return sum;
}

/** (now - before) / before, or null when `before` is missing or 0. */
export function change(now: number | null, before: number | null): number | null {
  if (now === null || before === null || before === 0) return null;
  return (now - before) / before;
}

export interface ForecastKpis {
  historyFirst: IsoDate;
  historyDays: number;
  historical: number;
  historicalChange: number | null; // vs the 28 days before, when fully inside the dataset
  forecasted: number;
  forecastChange: number | null; // vs the last N days before the cutoff (same length)
}

export function forecastKpis(points: ForecastPoint[], units: Map<IsoDate, number>,
  cutoff: IsoDate, datasetStart: IsoDate): ForecastKpis {
  const historyFirst = maxDate(addDays(cutoff, -(HISTORY_DAYS - 1)), datasetStart);
  const historical = windowSum(units, historyFirst, cutoff, datasetStart) ?? 0;
  const full = historyFirst === addDays(cutoff, -(HISTORY_DAYS - 1));
  const previous = full
    ? windowSum(units, addDays(cutoff, -(2 * HISTORY_DAYS - 1)), addDays(cutoff, -HISTORY_DAYS),
      datasetStart)
    : null;
  const forecasted = points.reduce((sum, p) => sum + p.forecast, 0);
  const sameLength = windowSum(units, addDays(cutoff, -(points.length - 1)), cutoff, datasetStart);
  return {
    historyFirst,
    historyDays: Math.round((Date.parse(cutoff) - Date.parse(historyFirst)) / 86_400_000) + 1,
    historical,
    historicalChange: full ? change(historical, previous) : null,
    forecasted,
    forecastChange: change(forecasted, sameLength),
  };
}
