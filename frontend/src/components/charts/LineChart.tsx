// Daily line chart (Dashboard "Daily sales"). Arrow keys move a focus marker along the
// points; the hidden table lists every value (D12: accessible, responsive, tested).
import { useId, useState, type KeyboardEvent, type PointerEvent } from "react";

import { useSize } from "../../hooks/useWidth";
import { ChartFrame, type ChartDatum } from "./ChartFrame";
import { niceMax } from "./scale";
import styles from "./charts.module.css";

const MIN_HEIGHT = 260; // the CSS height of .lineBox never goes below this
const M = { top: 12, right: 12, bottom: 28, left: 56 };

export function LineChart({ title, data, valueHeader, axisLabel, ticks }: {
  title: string; data: ChartDatum[]; valueHeader: string;
  axisLabel: (value: number) => string; ticks: { index: number; label: string }[];
}) {
  // The box gets its height from CSS (bounded by the viewport); the chart draws to it.
  const [ref, size] = useSize<HTMLDivElement>({ width: 640, height: MIN_HEIGHT });
  const width = size.width;
  const HEIGHT = Math.max(size.height, MIN_HEIGHT);
  const [active, setActive] = useState<number | null>(null);
  const gradient = `line-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
  const plotW = Math.max(width - M.left - M.right, 10);
  const plotH = HEIGHT - M.top - M.bottom;
  const max = niceMax(Math.max(0, ...data.map((d) => d.value)));
  const x = (i: number) => M.left + (data.length <= 1 ? plotW / 2 : (i / (data.length - 1)) * plotW);
  const y = (v: number) => M.top + plotH - (v / max) * plotH;
  const path = data.map((d, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(d.value).toFixed(1)}`)
    .join("");
  const area = data.length ? `${path}L${x(data.length - 1).toFixed(1)},${y(0)}L${x(0).toFixed(1)},${y(0)}Z` : "";
  const gridValues = [0, 0.25, 0.5, 0.75, 1].map((f) => f * max);

  const onKey = (event: KeyboardEvent) => {
    if (!data.length) return;
    const last = data.length - 1;
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
    setActive(Math.min(Math.max(Math.round(fraction * (data.length - 1)), 0), data.length - 1));
  };
  const point = active !== null ? data[active] : undefined;

  return (
    <ChartFrame title={title} data={data} valueHeader={valueHeader}>
      <div ref={ref} className={styles.lineBox}>
        <svg width={width} height={HEIGHT} role="img" aria-label={title} tabIndex={0}
          className={styles.svg} onKeyDown={onKey} onPointerMove={onPointer}
          onPointerLeave={() => setActive(null)} onBlur={() => setActive(null)}>
          <defs>
            <linearGradient id={`${gradient}-stroke`} x1="0" x2="1" y1="0" y2="0">
              {/* Electric blue along the line, a short cyan highlight at the recent end. */}
              <stop offset="0%" stopColor="#0a6ae0" />
              <stop offset="55%" stopColor="#087cff" />
              <stop offset="88%" stopColor="#008bff" />
              <stop offset="100%" stopColor="#2bbcff" />
            </linearGradient>
            <linearGradient id={`${gradient}-area`} x1="0" x2="0" y1="0" y2="1">
              {/* Dark blue area fading out under the line. */}
              <stop offset="0%" stopColor="#087cff" stopOpacity="0.22" />
              <stop offset="45%" stopColor="#063b83" stopOpacity="0.18" />
              <stop offset="100%" stopColor="#063b83" stopOpacity="0" />
            </linearGradient>
          </defs>
          {gridValues.map((v) => (
            <g key={v}>
              <line x1={M.left} x2={M.left + plotW} y1={y(v)} y2={y(v)} className={styles.grid} />
              <text x={M.left - 8} y={y(v)} className={styles.axisY}>{axisLabel(v)}</text>
            </g>
          ))}
          {ticks.map((t) => (
            <text key={t.index} x={x(t.index)} y={HEIGHT - 8} className={styles.axisX}>{t.label}</text>
          ))}
          <path d={area} className={styles.area} fill={`url(#${gradient}-area)`} />
          <path d={path} className={styles.line} stroke={`url(#${gradient}-stroke)`} />
          {point && active !== null && (
            <g className={styles.marker}>
              <line x1={x(active)} x2={x(active)} y1={M.top} y2={M.top + plotH} className={styles.guide} />
              <circle cx={x(active)} cy={y(point.value)} r={4.5} className={styles.dot} />
              <g transform={`translate(${Math.min(x(active) + 10, M.left + plotW - 150)},${M.top + 4})`}>
                <rect width={150} height={40} rx={6} className={styles.tooltip} />
                <text x={10} y={16} className={styles.tooltipLabel}>{point.label}</text>
                <text x={10} y={32} className={styles.tooltipValue}>{point.display}</text>
              </g>
            </g>
          )}
        </svg>
        <p className="visually-hidden" aria-live="polite">
          {point ? `${point.label}: ${point.display}` : ""}
        </p>
      </div>
    </ChartFrame>
  );
}
