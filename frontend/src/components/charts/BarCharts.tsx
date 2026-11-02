// Horizontal bars ("Sales by product (top 10)", regions) and vertical columns ("Sales by
// month"). Bars are focusable with a title; values are drawn as text (D12).
import { useWidth } from "../../hooks/useWidth";
import { ChartFrame, type ChartDatum } from "./ChartFrame";
import { niceMax } from "./scale";
import styles from "./charts.module.css";

const ROW = 28;

export function HorizontalBarChart({ title, data, valueHeader, labelWidth = 64 }: {
  title: string; data: ChartDatum[]; valueHeader: string; labelWidth?: number;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const labelW = labelWidth;
  const valueW = 72;
  const plotW = Math.max(width - labelW - valueW, 10);
  const max = Math.max(0, ...data.map((d) => d.value)) || 1;
  const height = data.length * ROW + 4;
  return (
    <ChartFrame title={title} data={data} valueHeader={valueHeader}>
      <div ref={ref} className={styles.box}>
        <svg width={width} height={height} role="group" aria-label={title} className={styles.svg}>
          {data.map((d, i) => {
            const w = Math.max((d.value / max) * plotW, d.value > 0 ? 2 : 0);
            const y = i * ROW + 4;
            return (
              <g key={d.label}>
                <text x={labelW - 8} y={y + 10} className={styles.barLabel}>{d.label}</text>
                <rect x={labelW} y={y} width={w} height={ROW - 10} rx={3} tabIndex={0}
                  className={styles.bar} aria-label={`${d.label}: ${d.display}`}>
                  <title>{`${d.label}: ${d.display}`}</title>
                </rect>
                <text x={labelW + w + 6} y={y + 10} className={styles.barValue}>{d.display}</text>
              </g>
            );
          })}
        </svg>
      </div>
    </ChartFrame>
  );
}

const COL_HEIGHT = 240;
const CM = { top: 12, right: 8, bottom: 26, left: 52 };

export function ColumnChart({ title, data, valueHeader, axisLabel, tickLabels }: {
  title: string; data: ChartDatum[]; valueHeader: string;
  axisLabel: (value: number) => string; tickLabels: string[];
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const plotW = Math.max(width - CM.left - CM.right, 10);
  const plotH = COL_HEIGHT - CM.top - CM.bottom;
  const max = niceMax(Math.max(0, ...data.map((d) => d.value)));
  const slot = plotW / Math.max(data.length, 1);
  const barW = Math.max(slot * 0.62, 2);
  const y = (v: number) => CM.top + plotH - (v / max) * plotH;
  return (
    <ChartFrame title={title} data={data} valueHeader={valueHeader}>
      <div ref={ref} className={styles.box}>
        <svg width={width} height={COL_HEIGHT} role="group" aria-label={title} className={styles.svg}>
          {[0, 0.25, 0.5, 0.75, 1].map((f) => (
            <g key={f}>
              <line x1={CM.left} x2={CM.left + plotW} y1={y(f * max)} y2={y(f * max)}
                className={styles.grid} />
              <text x={CM.left - 8} y={y(f * max)} className={styles.axisY}>{axisLabel(f * max)}</text>
            </g>
          ))}
          {data.map((d, i) => {
            const x = CM.left + i * slot + (slot - barW) / 2;
            return (
              <g key={d.label}>
                <rect x={x} y={y(d.value)} width={barW} height={Math.max(y(0) - y(d.value), 0)} rx={3}
                  tabIndex={0} className={styles.column} aria-label={`${d.label}: ${d.display}`}>
                  <title>{`${d.label}: ${d.display}`}</title>
                </rect>
                <text x={x + barW / 2} y={COL_HEIGHT - 8} className={styles.axisX}>
                  {tickLabels[i] ?? d.label}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
    </ChartFrame>
  );
}
