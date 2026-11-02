// Date range picker (spec 007 section 5, FR-07): native date inputs, validated before any
// request (valid dates, start <= end, inside the dataset). The range lives in the URL.
import { useState, type FormEvent } from "react";

import type { IsoDate } from "../api/types";
import { validateRange, type Range } from "../domain/range";
import { text } from "../text/en";
import { Icon } from "./Icons";
import styles from "./DateRangeControl.module.css";

export function DateRangeControl({ dataset, value, onChange }: {
  dataset: Range; value: Range; onChange: (range: Range | null) => void;
}) {
  const [draft, setDraft] = useState<{ start: IsoDate; end: IsoDate }>(value);
  const [shown, setShown] = useState(value);
  if (shown.start !== value.start || shown.end !== value.end) {
    // The URL changed (back button, link): show the new range.
    setShown(value);
    setDraft(value);
  }
  const problem = validateRange(draft.start, draft.end, dataset);
  const isDefault = value.start === dataset.start && value.end === dataset.end;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (problem !== null) return;
    const isFull = draft.start === dataset.start && draft.end === dataset.end;
    onChange(isFull ? null : draft);
  };

  return (
    <form className={styles.range} onSubmit={submit} aria-label={text.common.dateRange}
      noValidate>
      <span className={styles.icon}><Icon name="calendar" /></span>
      <label className={styles.field}>
        <span className="visually-hidden">{text.common.from}</span>
        <input type="date" className={styles.input} value={draft.start} min={dataset.start}
          max={dataset.end} required aria-invalid={problem !== null}
          aria-describedby={problem ? "range-problem" : undefined}
          onChange={(event) => setDraft({ ...draft, start: event.target.value })} />
      </label>
      <span aria-hidden="true" className={styles.dash}>–</span>
      <label className={styles.field}>
        <span className="visually-hidden">{text.common.to}</span>
        <input type="date" className={styles.input} value={draft.end} min={dataset.start}
          max={dataset.end} required aria-invalid={problem !== null}
          aria-describedby={problem ? "range-problem" : undefined}
          onChange={(event) => setDraft({ ...draft, end: event.target.value })} />
      </label>
      <button type="submit" className={styles.apply} disabled={problem !== null}>
        {text.common.apply}
      </button>
      {!isDefault && (
        <button type="button" className={styles.reset} onClick={() => onChange(null)}>
          {text.common.reset}
        </button>
      )}
      {problem && <p id="range-problem" className={styles.problem} role="alert">{problem}</p>}
    </form>
  );
}
