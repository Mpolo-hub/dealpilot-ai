// Shared building blocks: page header, tabs, cards, KPI cards, badges, filters and the
// loading, empty and error states (spec 007 sections 5 and 6).
import type { ReactNode } from "react";
import { Link, useLocation, useSearchParams } from "react-router";

import { errorMessage } from "../api/errors";
import { isPublicDemo } from "../demo";
import { text } from "../text/en";
import { Icon, type IconName } from "./Icons";
import styles from "./ui.module.css";

export function PageHeader({ title, subtitle, children }: {
  title: string; subtitle: string; children?: ReactNode;
}) {
  return (
    <div className={styles.header}>
      <div>
        <h1 className={styles.title}>{title}</h1>
        <p className={styles.subtitle}>{subtitle}</p>
      </div>
      {children && <div className={styles.headerActions}>{children}</div>}
    </div>
  );
}

/** Tabs as links: the tab is part of the URL (FR-07). The first tab is the default. */
export function Tabs({ tabs, current, label }: {
  tabs: { id: string; label: string }[]; current: string; label: string;
}) {
  const [params] = useSearchParams();
  const location = useLocation();
  return (
    <nav aria-label={label} className={styles.tabs}>
      {tabs.map((tab, index) => {
        const next = new URLSearchParams(params);
        if (index === 0) next.delete("tab");
        else next.set("tab", tab.id);
        const search = next.toString();
        const active = tab.id === current;
        return (
          <Link key={tab.id} to={{ pathname: location.pathname, search: search ? `?${search}` : "" }}
            className={`${styles.tab} ${active ? styles.tabActive : ""}`}
            aria-current={active ? "page" : undefined}>
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}

export function Card({ title, icon, actions, children, className }: {
  title?: string; icon?: IconName; actions?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <section className={`${styles.card} ${className ?? ""}`} aria-label={title}>
      {(title || actions) && (
        <div className={styles.cardHeader}>
          {title && (
            <h2 className={styles.cardTitle}>
              {icon && <span className={styles.cardTitleIcon}><Icon name={icon} size={20} /></span>}
              {title}
            </h2>
          )}
          {actions && <div className={styles.cardActions}>{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

export function KpiCard({ icon, label, value, exact, note, badge }: {
  icon: IconName; label: string; value: ReactNode; exact?: string; note?: ReactNode;
  badge?: ReactNode;
}) {
  return (
    <section className={styles.kpi} aria-label={label}>
      <span className={styles.kpiIcon}><Icon name={icon} size={20} /></span>
      <h2 className={styles.kpiLabel}>{label}</h2>
      {badge && <div className={styles.kpiBadge}>{badge}</div>}
      <p className={styles.kpiValue} title={exact ? `${text.common.exactValue}: ${exact}` : undefined}>
        {value}
        {exact && <span className="visually-hidden"> ({text.common.exactValue}: {exact})</span>}
      </p>
      {note && <p className={styles.kpiNote}>{note}</p>}
    </section>
  );
}

export function KpiRow({ children }: { children: ReactNode }) {
  return <div className={styles.kpiRow}>{children}</div>;
}

export function Badge({ tone, children }: {
  tone: "positive" | "negative" | "neutral" | "info" | "upcoming"; children: ReactNode;
}) {
  return <span className={`${styles.badge} ${styles[tone]}`}>{children}</span>;
}

/** Product status (D4): a dot and a soft tint per state. */
export function StatusBadge({ status, label }: {
  status: "active" | "discontinued" | "not_launched"; label: string;
}) {
  const tone = { active: "positive", discontinued: "neutral", not_launched: "upcoming" }[status];
  return <span className={`${styles.badge} ${styles.status} ${styles[tone]}`}>{label}</span>;
}

/** Signed percent change with one decimal, e.g. `+12.3%`. */
export function ChangeBadge({ change, label }: { change: number | null; label: string }) {
  if (change === null) return <Badge tone="neutral">{text.common.notAvailable}</Badge>;
  const pct = change * 100;
  const shown = `${pct > 0 ? "+" : ""}${pct.toFixed(1)}%`;
  return (
    <Badge tone={pct > 0 ? "positive" : pct < 0 ? "negative" : "neutral"}>
      {shown}<span className="visually-hidden"> {label}</span>
    </Badge>
  );
}

export function Select({ id, label, value, options, onChange, inline = false, disabled = false }: {
  id: string; label: string; value: string;
  options: { value: string; label: string }[]; onChange: (value: string) => void;
  /** Label beside the control (for card headers) instead of above it. */
  inline?: boolean;
  disabled?: boolean;
}) {
  return (
    <div className={`${styles.field} ${inline ? styles.fieldInline : ""}`}>
      <label htmlFor={id} className={styles.fieldLabel}>{label}</label>
      <select id={id} className={styles.control} value={value} disabled={disabled}
        onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => (
          <option key={option.value} value={option.value}>{option.label}</option>
        ))}
      </select>
    </div>
  );
}

export function SearchBox({ id, label, placeholder, value, onChange }: {
  id: string; label: string; placeholder: string; value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className={`${styles.field} ${styles.searchField}`}>
      <label htmlFor={id} className={styles.fieldLabel}>{label}</label>
      <span className={styles.searchIcon}><Icon name="search" size={16} /></span>
      <input id={id} type="search" className={`${styles.control} ${styles.search}`}
        placeholder={placeholder} value={value} onChange={(event) => onChange(event.target.value)} />
    </div>
  );
}

/** "Showing 12 of 50 products": the size of a filtered list, for orientation. */
export function ResultCount({ children }: { children: ReactNode }) {
  // aria-live without role="status": that role marks loading placeholders in this app.
  return <p className={styles.resultCount} aria-live="polite">{children}</p>;
}

export function FilterRow({ children }: { children: ReactNode }) {
  return <div className={styles.filterRow}>{children}</div>;
}

export function Grid({ children, variant, className }: {
  children: ReactNode; variant: "wide-narrow" | "halves" | "chart-table"; className?: string;
}) {
  return <div className={`${styles.grid} ${styles[variant]} ${className ?? ""}`}>{children}</div>;
}

export function Skeleton({ height = 120, label = text.common.loading }: {
  height?: number; label?: string;
}) {
  return (
    <div className={styles.skeleton} data-height={height} role="status" aria-live="polite">
      <span className="visually-hidden">{label}</span>
      <svg width="100%" height={height} aria-hidden="true" />
    </div>
  );
}

export function EmptyState({ message = text.common.noSales }: { message?: string }) {
  return <p className={styles.empty}>{message}</p>;
}

export function ErrorPanel({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { message, detail } = errorMessage(error);
  return (
    <div className={styles.error} role="alert">
      <p className={styles.errorTitle}>{text.errors.title}</p>
      <p>{message}</p>
      {detail && <p className={styles.errorDetail}>{detail}</p>}
      {onRetry && (
        <button type="button" className={styles.button} onClick={onRetry}>
          {text.common.tryAgain}
        </button>
      )}
    </div>
  );
}

export function DataUnavailable() {
  // Public demo (S1-D15): a neutral message, no local command.
  const publicDemo = isPublicDemo();
  return (
    <div className={styles.unavailable} role="alert">
      <h1 className={styles.title}>{text.errors.dataUnavailableTitle}</h1>
      <p>{publicDemo ? text.errors.demoDataUnavailable : text.errors.dataUnavailable}</p>
      {!publicDemo && <p className={styles.subtitle}>{text.errors.dataUnavailableHelp}</p>}
    </div>
  );
}

/** Stage 1 demo notice (A7-H1, S1-d): one permanent line, public demo mode only. */
export function DemoNotice() {
  return <p className={styles.demoNotice} role="note">{text.access.demoNotice}</p>;
}

/** A legend entry: a colored line and its label (reference: "Actual sales"). */
export function LegendKey({ label }: { label: string }) {
  return (
    <span className={styles.legendKey}>
      <svg width="16" height="4" aria-hidden="true"><rect width="16" height="4" rx="2" className={styles.legendSwatch} /></svg>
      {label}
    </span>
  );
}
