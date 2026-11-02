// Sortable table (spec 007 section 6). Sorting is a view detail kept in component state;
// the table scrolls inside its card on small screens, never the page (section 10).
import { useState, type ReactNode } from "react";

import styles from "./DataTable.module.css";

export interface Column<T> {
  key: string;
  header: string;
  cell: (row: T) => ReactNode;
  /** Sort key; columns without one are not sortable. */
  sortValue?: (row: T) => string | number | bigint;
  align?: "start" | "end";
  /** Text weight: "strong" for the main label of a row, "muted" for codes. */
  tone?: "strong" | "muted";
}

export function DataTable<T>({ caption, columns, rows, rowKey, initialSort, empty }: {
  caption: string; columns: Column<T>[]; rows: T[]; rowKey: (row: T) => string;
  initialSort?: { key: string; direction: "asc" | "desc" }; empty?: ReactNode;
}) {
  const [sort, setSort] = useState(initialSort ?? null);
  const column = columns.find((c) => c.key === sort?.key);
  const sorted = column?.sortValue && sort ? [...rows].sort((a, b) => {
    const x = column.sortValue!(a);
    const y = column.sortValue!(b);
    const order = x < y ? -1 : x > y ? 1 : 0;
    return sort.direction === "asc" ? order : -order;
  }) : rows;

  const toggle = (key: string) => setSort((current) => ({
    key,
    direction: current?.key === key && current.direction === "desc" ? "asc" : "desc",
  }));

  return (
    <div className={styles.wrap}>
      <table className={styles.table}>
        <caption className="visually-hidden">{caption}</caption>
        <thead>
          <tr>
            {columns.map((c) => {
              const state = sort?.key === c.key
                ? (sort.direction === "asc" ? "ascending" : "descending") : undefined;
              return (
                <th key={c.key} scope="col" aria-sort={c.sortValue ? state ?? "none" : undefined}
                  className={c.align === "end" ? styles.end : undefined}>
                  {c.sortValue ? (
                    <button type="button" className={`${styles.sortButton} ${c.align === "end" ? styles.sortEnd : ""}`}
                      onClick={() => toggle(c.key)}>
                      {c.header}
                      <span aria-hidden="true" className={styles.arrow}>
                        {state === "ascending" ? "▲" : state === "descending" ? "▼" : "↕"}
                      </span>
                    </button>
                  ) : c.header}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => (
            <tr key={rowKey(row)}>
              {columns.map((c) => (
                <td key={c.key} className={[c.align === "end" ? styles.end : "",
                  c.tone ? styles[c.tone] : ""].join(" ").trim() || undefined}>{c.cell(row)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length === 0 && empty}
    </div>
  );
}
