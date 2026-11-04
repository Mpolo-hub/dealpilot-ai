// Prediction chart (spec 007 D14 amendment, 2026-11-04; hand-drawn SVG, D12): actual daily
// units up to the cutoff as a solid blue line, the forecast after it as a dashed purple
// line, and a vertical cutoff marker. No confidence band (the baseline gives no ranges) and
// no actual values after the cutoff. Arrow keys move a focus marker; the hidden table lists
// every value.
import { useState, type KeyboardEvent, type PointerEvent } from "react";

import type { IsoDate } from "../../api/types";
import { useSize } from "../../hooks/useWidth";
import { ChartFrame } from "./ChartFrame";
import { niceMax } from "./scale";
import styles from "./charts.module.css";

const MIN_HEIGHT = 260;
const M = { top: 30, right: 14, bottom: 28, left: 52 };

export interface ForecastChartPoint {
  date: IsoDate;
  label: string; // full date for the tooltip and the table
  tick: string; // short axis label
  actual: number | null;
  forecast: number | null;
}

export function ForecastChart({ title, points, cutoffIndex, cutoffLabel, actualLabel,
  forecastLabel, format }: {
  title: string; points: ForecastChartPoint[]; cutoffIndex: number; cutoffLabel: string;
  actualLabel: string; forecastLabel: string; format: (value: number) => string;
}) {
  const [ref, size] = useSize<HTMLDivElement>({ width: 640, height: MIN_HEIGHT });
  const width = size.width;
  const height = Math.max(size.height, MIN_HEIGHT);
  const [active, setActive] = useState<number | null>(null);
  const plotW = Math.max(width - M.left - M.right, 10);
  const plotH = height - M.top - M.bottom;
  const values = points.flatMap((p) => [p.actual ?? 0, p.forecast ?? 0]);
  const max = niceMax(Math.max(0, ...values));
  const x = (i: number) => M.left + (points.length <= 1 ? plotW / 2 : (i / (points.length - 1)) * plotW);
  const y = (v: number) => M.top + plotH - (v / max) * plotH;
  const line = (pick: (p: ForecastChartPoint) => number | null) => points
    .map((p, i) => ({ v: pick(p), i }))
    .filter((p): p is { v: number; i: number } => p.v !== null)
    .map((p, n) => `${n === 0 ? "M" : "L"}${x(p.i).toFixed(1)},${y(p.v).toFixed(1)}`).join("");
  const actualPath = line((p) => p.actual);
  const forecastPath = line((p) => p.forecast);
  const gridValues = [0, 0.25, 0.5, 0.75, 1].map((f) => f * max);
  const tickStep = Math.max(1, Math.ceil(points.length / Math.max(2, Math.floor(plotW / 64))));
  const cutoffX = x(cutoffIndex);

  const onKey = (event: KeyboardEvent) => {
    if (!points.length) return;
    const last = points.length - 1;
    const moves: Record<string, number> = {
      ArrowRight: Math.min((active ?? -1) + 1, last), ArrowLeft: Math.max((active ?? 1) - 1, 0),
      Home: 0, End: last,
    };
    if (event.key in moves) {
      event.preventDefault();
      setActive(moves[event.key] ?? null);
    }
  };
  const onPointer = (event: PointerEvent<SVGSVGElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    const fraction = (event.clientX - box.left - M.left) / plotW;
    setActive(Math.min(Math.max(Math.round(fraction * (points.length - 1)), 0), points.length - 1));
  };
  const point = active !== null ? points[active] : undefined;
  const describe = (p: ForecastChartPoint) => p.actual !== null
    ? `${actualLabel}: ${format(p.actual)}` : `${forecastLabel}: ${format(p.forecast ?? 0)}`;

  return (
    <ChartFrame title={title} valueHeader={`${actualLabel} / ${forecastLabel}`}
      data={points.map((p) => ({ label: p.label, value: p.actual ?? p.forecast ?? 0,
        display: describe(p) }))}>
      <div ref={ref} className={styles.lineBox}>
        <svg width={width} height={height} role="img" aria-label={title} tabIndex={0}
          className={styles.svg} onKeyDown={onKey} onPointerMove={onPointer}
          onPointerLeave={() => setActive(null)} onBlur={() => setActive(null)}>
          {gridValues.map((v) => (
            <g key={v}>
              <line x1={M.left} x2={M.left + plotW} y1={y(v)} y2={y(v)} className={styles.grid} />
              <text x={M.left - 8} y={y(v)} className={styles.axisY}>{format(v)}</text>
            </g>
          ))}
          {points.map((p, i) => (i % tickStep === 0 ? (
            <text key={p.date} x={x(i)} y={height - 8} className={styles.axisX}>{p.tick}</text>
          ) : null))}
          <line x1={cutoffX} x2={cutoffX} y1={M.top - 6} y2={M.top + plotH}
            className={styles.cutoff} data-testid="cutoff-marker" />
          <text x={Math.min(Math.max(cutoffX, M.left + 60), M.left + plotW - 60)} y={M.top - 12}
            className={styles.cutoffLabel}>{cutoffLabel}</text>
          <path d={actualPath} className={styles.actualLine} data-testid="actual-line" />
          <path d={forecastPath} className={styles.forecastLine} data-testid="forecast-line" />
          {point && active !== null && (
            <g className={styles.marker}>
              <line x1={x(active)} x2={x(active)} y1={M.top} y2={M.top + plotH} className={styles.guide} />
              <circle cx={x(active)} cy={y(point.actual ?? point.forecast ?? 0)} r={4.5}
                className={point.actual !== null ? styles.dot : styles.forecastDot} />
              <g transform={`translate(${Math.min(x(active) + 10, M.left + plotW - 170)},${M.top + 4})`}>
                <rect width={170} height={40} rx={6} className={styles.tooltip} />
                <text x={10} y={16} className={styles.tooltipLabel}>{point.label}</text>
                <text x={10} y={32} className={styles.tooltipValue}>{describe(point)}</text>
              </g>
            </g>
          )}
        </svg>
        <p className="visually-hidden" aria-live="polite">
          {point ? `${point.label}: ${describe(point)}` : ""}
        </p>
      </div>
    </ChartFrame>
  );
}
