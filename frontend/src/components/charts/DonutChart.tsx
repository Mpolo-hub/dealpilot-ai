// Donut with a center total and a legend (Dashboard "Sales by region"). Each segment is
// focusable and has a title (D12).
import { ChartFrame, type ChartDatum } from "./ChartFrame";
import styles from "./charts.module.css";

const SIZE = 196;
const R = 86;
const INNER = 60;
const SERIES_COLORS = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)",
  "var(--chart-4)", "var(--chart-5)", "var(--chart-6)", "var(--chart-7)"];

function arc(start: number, end: number): string {
  const point = (angle: number, radius: number) =>
    `${(SIZE / 2 + radius * Math.sin(angle)).toFixed(2)},${(SIZE / 2 - radius * Math.cos(angle)).toFixed(2)}`;
  const large = end - start > Math.PI ? 1 : 0;
  return `M${point(start, R)}A${R},${R} 0 ${large} 1 ${point(end, R)}`
    + `L${point(end, INNER)}A${INNER},${INNER} 0 ${large} 0 ${point(start, INNER)}Z`;
}

export function DonutChart({ title, data, valueHeader, centerValue, centerLabel, shares }: {
  title: string; data: ChartDatum[]; valueHeader: string; centerValue: string;
  centerLabel: string; shares: (number | null)[];
}) {
  const total = data.reduce((sum, d) => sum + d.value, 0);
  const sweeps = data.map((d) => (total > 0 ? (d.value / total) * 2 * Math.PI : 0));
  const segments = data.map((d, i) => {
    const start = sweeps.slice(0, i).reduce((sum, s) => sum + s, 0);
    return { d, i, start, end: start + (sweeps[i] ?? 0), sweep: sweeps[i] ?? 0 };
  });
  const pct = (share: number | null) => (share === null ? "0%" : `${(share * 100).toFixed(0)}%`);

  return (
    <ChartFrame title={title} data={data} valueHeader={valueHeader}>
      <div className={styles.donutLayout}>
        <svg width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`} role="group" aria-label={title}
          className={styles.donut}>
          <circle cx={SIZE / 2} cy={SIZE / 2} r={R + 5} className={styles.donutRing} />
          <circle cx={SIZE / 2} cy={SIZE / 2} r={INNER - 2} className={styles.donutCore} />
          {total === 0 && <circle cx={SIZE / 2} cy={SIZE / 2} r={(R + INNER) / 2}
            className={styles.donutEmpty} />}
          {segments.map(({ d, i, start, end, sweep }) => sweep > 0 && (
            <path key={d.label} tabIndex={0} className={styles.segment}
              d={sweep >= 2 * Math.PI - 1e-9 ? arc(0, 2 * Math.PI - 1e-4) : arc(start, end)}
              fill={SERIES_COLORS[i % SERIES_COLORS.length]}
              aria-label={`${d.label}: ${d.display} (${pct(shares[i] ?? null)})`}>
              <title>{`${d.label}: ${d.display} (${pct(shares[i] ?? null)})`}</title>
            </path>
          ))}
          <text x={SIZE / 2} y={SIZE / 2 - 2} className={styles.centerValue}>{centerValue}</text>
          <text x={SIZE / 2} y={SIZE / 2 + 18} className={styles.centerLabel}>{centerLabel}</text>
        </svg>
        <ul className={styles.legend}>
          {data.map((d, i) => (
            <li key={d.label}>
              <svg width="10" height="10" aria-hidden="true">
                <circle cx="5" cy="5" r="5" fill={SERIES_COLORS[i % SERIES_COLORS.length]} />
              </svg>
              <span className={styles.legendLabel}>{d.label}</span>
              <span className={styles.legendValue}>{pct(shares[i] ?? null)}</span>
            </li>
          ))}
        </ul>
      </div>
    </ChartFrame>
  );
}
