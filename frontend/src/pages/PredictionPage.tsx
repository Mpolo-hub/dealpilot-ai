// Prediction (spec 007 D14 amendment, 2026-11-04; reference `DealDesign/prediction.png`,
// in the DealPilot dark theme). Forecasts come from GET /v1/forecasts (spec 003 section
// 10, seasonal naive "1.0"); actual units from /v1/sales/metrics. The Model Evaluation tab
// shows an exploratory backtest of the spec 003 harness, labelled as such, never a formal
// evaluation or a holdout result.
import { useState, type FormEvent } from "react";
import { useSearchParams } from "react-router";

import { DIMENSIONS, forecastsPath, metricsPath } from "../api/endpoints";
import type {
  Dimensions, ForecastLevel, ForecastQuery, ForecastResponse, IsoDate, MetricsQuery, SalesMetrics,
} from "../api/types";
import { ForecastChart, type ForecastChartPoint } from "../components/charts/ForecastChart";
import { type Column, DataTable } from "../components/DataTable";
import {
  Badge, Card, ChangeBadge, DataUnavailable, EmptyState, Grid, KpiCard, KpiRow, PageHeader,
  Select, Tabs,
} from "../components/ui";
import ui from "../components/ui.module.css";
import evaluation from "../evaluation/exploratory-backtest.json";
import { addDays, formatDate, isIsoDate, maxDate, minDate, monthLabel } from "../domain/dates";
import {
  type ForecastRow, forecastKpis, forecastRows, HISTORY_DAYS, HORIZONS, unitsByDate,
} from "../domain/forecast";
import { formatCount } from "../domain/format";
import { useApi } from "../hooks/useApi";
import { text } from "../text/en";
import { anyDataUnavailable } from "./pageState";
import styles from "./PredictionPage.module.css";
import { Loaded } from "./shared";

const t = text.prediction;
const LEVELS: ForecastLevel[] = ["total", "category", "product_region"];
const MIN_HISTORY_DAYS = 6; // spec 003 section 10: the cutoff is on or after start + 6
const ALL = "";

/** The submitted query from the URL, or null when nothing (valid) was submitted yet. */
function submittedQuery(params: URLSearchParams, dims: Dimensions): ForecastQuery | null {
  const level = params.get("level") as ForecastLevel | null;
  const cutoff = params.get("cutoff") ?? "";
  const horizon = Number(params.get("horizon"));
  const { start, end } = dims.date_range;
  if (!level || !LEVELS.includes(level) || !isIsoDate(cutoff)
    || cutoff < addDays(start, MIN_HISTORY_DAYS) || cutoff > end
    || !(HORIZONS as readonly number[]).includes(horizon)) return null;
  const query: ForecastQuery = { level, cutoff, horizon };
  if (level === "category") {
    const category = params.get("category");
    if (!category || !dims.categories.includes(category)) return null;
    query.category = category;
  }
  if (level === "product_region") {
    const productId = params.get("product_id");
    const regionId = params.get("region_id");
    if (!dims.products.some((p) => p.product_id === productId)
      || !dims.regions.some((r) => r.region_id === regionId)) return null;
    query.product_id = productId ?? undefined;
    query.region_id = regionId ?? undefined;
  }
  return query;
}

function seriesLabel(query: ForecastQuery, dims: Dimensions): string {
  if (query.level === "category") return query.category ?? "";
  if (query.level === "product_region") {
    const product = dims.products.find((p) => p.product_id === query.product_id);
    const region = dims.regions.find((r) => r.region_id === query.region_id);
    return `${product?.name ?? query.product_id} (${query.product_id}), ${region?.name ?? query.region_id}`;
  }
  return t.allSales;
}

function shortDate(iso: IsoDate): string {
  return `${monthLabel(iso)} ${Number(iso.slice(8, 10))}`;
}

function weekday(iso: IsoDate): string {
  return t.weekdays[new Date(`${iso}T00:00:00Z`).getUTCDay()] ?? "";
}

function modelName(name: string, version: string): string {
  return `${t.modelNames[name]?.replace(" (sanity check)", "") ?? name} v${version}`;
}

const percent = (value: number | null, digits = 1) =>
  value === null ? text.common.notAvailable : `${(value * 100).toFixed(digits)}%`;
const signed = (value: number) => `${value > 0 ? "+" : ""}${formatCount(value)}`;

export function PredictionPage() {
  const [dims, retryDims] = useApi<Dimensions>(DIMENSIONS);
  const [params, setParams] = useSearchParams();
  const header = <PageHeader title={t.title} subtitle={t.subtitle} />;
  if (anyDataUnavailable([dims])) return <DataUnavailable />;
  if (dims.status !== "ready") {
    return <>{header}<Loaded state={dims} retry={retryDims}>{() => null}</Loaded></>;
  }
  const submitted = submittedQuery(params, dims.data);
  const submit = (query: ForecastQuery) => {
    setParams((current) => {
      const next = new URLSearchParams();
      const tab = current.get("tab");
      if (tab) next.set("tab", tab);
      next.set("level", query.level);
      if (query.category) next.set("category", query.category);
      if (query.product_id) next.set("product_id", query.product_id);
      if (query.region_id) next.set("region_id", query.region_id);
      next.set("cutoff", query.cutoff);
      next.set("horizon", String(query.horizon));
      return next;
    });
  };
  return (
    <>
      {header}
      <ForecastResults dims={dims.data} query={submitted} tab={params.get("tab")}
        onSubmit={submit} />
    </>
  );
}

function ForecastResults({ dims, query, tab, onSubmit }: {
  dims: Dimensions; query: ForecastQuery | null; tab: string | null;
  onSubmit: (query: ForecastQuery) => void;
}) {
  const dataset = dims.date_range;
  const [forecast, retryForecast] = useApi<ForecastResponse>(query ? forecastsPath(query) : null);
  const actualsQuery: MetricsQuery | null = query ? {
    start: maxDate(dataset.start, addDays(query.cutoff, -(2 * HISTORY_DAYS - 1))),
    end: minDate(dataset.end, addDays(query.cutoff, query.horizon)),
    group_by: ["date"], interval: "day",
    category: query.level === "category" && query.category ? [query.category] : undefined,
    product_id: query.level === "product_region" && query.product_id ? [query.product_id] : undefined,
    region_id: query.level === "product_region" && query.region_id ? [query.region_id] : undefined,
  } : null;
  const [actuals, retryActuals] = useApi<SalesMetrics>(actualsQuery ? metricsPath(actualsQuery) : null);
  const busy = query !== null && (forecast.status === "loading" || actuals.status === "loading");

  if (anyDataUnavailable([forecast, actuals])) return <DataUnavailable />;

  const form = <ForecastForm dims={dims} initial={query} busy={busy} onSubmit={onSubmit} />;
  if (!query) {
    return <>{form}<Card><EmptyState message={t.start} /></Card></>;
  }
  if (forecast.status !== "ready" || actuals.status !== "ready") {
    const failed = forecast.status === "error" ? forecast : actuals;
    const retry = forecast.status === "error" ? retryForecast : retryActuals;
    return <>{form}<Card><Loaded state={failed} retry={retry} height={260}>{() => null}</Loaded></Card></>;
  }

  const answer = forecast.data;
  const units = unitsByDate(actuals.data.rows);
  const kpis = forecastKpis(answer.points, units, answer.cutoff, dataset.start);
  const rows = forecastRows(answer.points, units, dataset.end);
  const first = answer.points[0]?.date ?? answer.cutoff;
  const last = answer.points[answer.points.length - 1]?.date ?? answer.cutoff;
  const product = query.level === "product_region"
    ? dims.products.find((p) => p.product_id === query.product_id) : undefined;
  const label = seriesLabel(query, dims);
  const history: ForecastChartPoint[] = [];
  for (let day = kpis.historyFirst; day <= answer.cutoff; day = addDays(day, 1)) {
    history.push({ date: day, label: formatDate(day), tick: shortDate(day),
      actual: units.get(day) ?? 0, forecast: null });
  }
  // No actual value is drawn after the cutoff, even when the dataset has one.
  const chartPoints = [...history, ...answer.points.map((p) => ({
    date: p.date, label: formatDate(p.date), tick: shortDate(p.date), actual: null,
    forecast: p.forecast }))];

  return (
    <>
      {form}
      <KpiRow>
        <KpiCard icon="orders" label={t.historical} value={formatCount(kpis.historical)}
          note={t.historicalNote(kpis.historyDays)}
          badge={kpis.historicalChange !== null
            ? <ChangeBadge change={kpis.historicalChange} label={t.vsPrevious} /> : undefined} />
        <KpiCard icon="trend" label={t.forecasted} value={formatCount(kpis.forecasted)}
          note={t.forecastedNote(answer.horizon)}
          badge={kpis.forecastChange !== null
            ? <ChangeBadge change={kpis.forecastChange} label={t.vsLast(answer.horizon)} /> : undefined} />
        <KpiCard icon="calendar" label={t.horizonCard} value={t.horizonDays(answer.horizon)}
          note={t.range(formatDate(first), formatDate(last))} />
        <KpiCard icon="bars" label={t.model} value={modelName(answer.model.name, answer.model.version)}
          badge={<Badge tone="info">{t.baseline}</Badge>} />
      </KpiRow>
      <Grid variant="wide-narrow">
        <Card title={t.chartTitle} icon="analysis">
          <p className={styles.chartSubtitle}>{t.chartSubtitle(label)}</p>
          {product && product.launch_date > answer.cutoff && (
            <p className={styles.notice} role="note">{t.notLaunched(formatDate(product.launch_date))}</p>
          )}
          <ForecastChart title={`${t.chartTitle}, ${label}`} points={chartPoints}
            cutoffIndex={history.length - 1} cutoffLabel={t.cutoffMarker(formatDate(answer.cutoff))}
            actualLabel={t.actualUnits} forecastLabel={t.forecastUnits} format={formatCount} />
          <div className={styles.legend}>
            <span className={styles.legendItem}>
              <svg width="22" height="6" aria-hidden="true"><line x1="0" x2="22" y1="3" y2="3" className={styles.legendActual} /></svg>
              {t.actualUnits}
            </span>
            <span className={styles.legendItem}>
              <svg width="22" height="6" aria-hidden="true"><line x1="0" x2="22" y1="3" y2="3" className={styles.legendForecast} /></svg>
              {t.forecastUnits}
            </span>
          </div>
        </Card>
        <Card title={t.details} icon="info">
          <dl className={styles.details}>
            <dt>{t.detailModel}</dt><dd>{t.modelNames[answer.model.name]?.replace(" (sanity check)", "") ?? answer.model.name}</dd>
            <dt>{t.detailVersion}</dt><dd>{answer.model.version}</dd>
            <dt>{t.detailTarget}</dt><dd>{t.dailyUnits}</dd>
            <dt>{t.detailHorizon}</dt><dd>{t.horizonDays(answer.horizon)}</dd>
            <dt>{t.detailTraining}</dt><dd>{t.range(formatDate(dataset.start), formatDate(answer.cutoff))}</dd>
            <dt>{t.detailMethod}</dt><dd>{t.method}</dd>
            <dt>{t.detailPromotions}</dt><dd>{answer.uses_planned_promotions ? t.used : t.notUsed}</dd>
          </dl>
          <p className={styles.note} role="note">{t.note}</p>
        </Card>
      </Grid>
      <section className={styles.tabsSection}>
        <Tabs label={t.tabs} current={tab === "evaluation" ? "evaluation" : "table"}
          tabs={[{ id: "table", label: t.tabTable }, { id: "evaluation", label: t.tabEvaluation }]} />
        {tab === "evaluation"
          ? <EvaluationView level={query.level} />
          : <ForecastTable rows={rows} label={label} />}
      </section>
    </>
  );
}

function ForecastForm({ dims, initial, busy, onSubmit }: {
  dims: Dimensions; initial: ForecastQuery | null; busy: boolean;
  onSubmit: (query: ForecastQuery) => void;
}) {
  const { start, end } = dims.date_range;
  const earliest = addDays(start, MIN_HISTORY_DAYS);
  const firstCategory = dims.categories[0] ?? "";
  const [level, setLevel] = useState<ForecastLevel>(initial?.level ?? "total");
  const initialProduct = dims.products.find((p) => p.product_id === initial?.product_id);
  const [category, setCategory] = useState<string>(
    initial?.category ?? (initialProduct ? initialProduct.category : ALL));
  const [productId, setProductId] = useState<string>(initial?.product_id ?? dims.products[0]?.product_id ?? "");
  const [regionId, setRegionId] = useState<string>(initial?.region_id ?? dims.regions[0]?.region_id ?? "");
  const [cutoff, setCutoff] = useState<string>(initial?.cutoff ?? end);
  const [horizon, setHorizon] = useState<number>(initial?.horizon ?? 28);
  const [error, setError] = useState<string | null>(null);

  const products = dims.products.filter((p) => level !== "product_region" || category === ALL
    || p.category === category);
  const product = products.some((p) => p.product_id === productId) ? productId : products[0]?.product_id ?? "";
  const categoryValue = level === "total" ? ALL
    : level === "category" && category === ALL ? firstCategory : category;
  const categoryOptions = [
    ...(level !== "category" ? [{ value: ALL, label: t.all }] : []),
    ...dims.categories.map((c) => ({ value: c, label: c })),
  ];

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (busy) return; // no double submit
    if (!isIsoDate(cutoff) || cutoff < earliest || cutoff > end) {
      setError(t.cutoffInvalid(formatDate(earliest), formatDate(end)));
      return;
    }
    setError(null);
    onSubmit({
      level, cutoff, horizon,
      category: level === "category" ? categoryValue : undefined,
      product_id: level === "product_region" ? product : undefined,
      region_id: level === "product_region" ? regionId : undefined,
    });
  };

  return (
    <form className={styles.form} onSubmit={submit} aria-label={t.filters} noValidate>
      <Select id="prediction-level" label={t.level} value={level}
        options={LEVELS.map((l) => ({ value: l, label: t.levels[l] }))}
        onChange={(value) => setLevel(value as ForecastLevel)} />
      <Select id="prediction-category" label={t.category} value={categoryValue}
        disabled={level === "total"} options={level === "total" ? [{ value: ALL, label: t.all }] : categoryOptions}
        onChange={setCategory} />
      <Select id="prediction-product" label={t.product}
        value={level === "product_region" ? product : ALL} disabled={level !== "product_region"}
        options={level === "product_region"
          ? products.map((p) => ({ value: p.product_id, label: `${p.name} (${p.product_id})` }))
          : [{ value: ALL, label: t.all }]}
        onChange={setProductId} />
      <Select id="prediction-region" label={t.region}
        value={level === "product_region" ? regionId : ALL} disabled={level !== "product_region"}
        options={level === "product_region"
          ? dims.regions.map((r) => ({ value: r.region_id, label: r.name }))
          : [{ value: ALL, label: t.all }]}
        onChange={setRegionId} />
      <div className={ui.field}>
        <label htmlFor="prediction-cutoff" className={ui.fieldLabel}>{t.cutoff}</label>
        <input id="prediction-cutoff" type="date" className={ui.control} value={cutoff}
          min={earliest} max={end} aria-invalid={error !== null}
          aria-describedby={error ? "prediction-cutoff-error" : undefined}
          onChange={(event) => setCutoff(event.target.value)} />
      </div>
      <Select id="prediction-horizon" label={t.horizon} value={String(horizon)}
        options={HORIZONS.map((h) => ({ value: String(h), label: t.horizonDays(h) }))}
        onChange={(value) => setHorizon(Number(value))} />
      <button type="submit" className={`${ui.button} ${styles.generate}`} disabled={busy}
        aria-busy={busy}>
        {busy ? t.generating : t.generate}
      </button>
      {error && <p id="prediction-cutoff-error" className={styles.formError} role="alert">{error}</p>}
    </form>
  );
}

function ForecastTable({ rows, label }: { rows: ForecastRow[]; label: string }) {
  const dash = t.noActual;
  const columns: Column<ForecastRow>[] = [
    { key: "date", header: t.date, cell: (r) => formatDate(r.date), tone: "strong" },
    { key: "day", header: t.day, cell: (r) => weekday(r.date) },
    { key: "actual", header: t.actual, align: "end",
      cell: (r) => (r.actual === null ? dash : formatCount(r.actual)) },
    { key: "forecast", header: t.forecast, align: "end", cell: (r) => formatCount(r.forecast) },
    { key: "difference", header: t.difference, align: "end",
      cell: (r) => (r.difference === null ? dash : signed(r.difference)) },
    { key: "absError", header: t.absError, align: "end",
      cell: (r) => (r.absError === null ? dash : formatCount(r.absError)) },
    { key: "ape", header: t.ape, align: "end",
      cell: (r) => (r.actual === null ? dash : percent(r.ape)) },
  ];
  return (
    <Card>
      <DataTable caption={`${t.tabTable}, ${label}`} columns={columns} rows={rows}
        rowKey={(r) => r.date} />
      <p className={styles.tableNote}>{t.tableNote}</p>
    </Card>
  );
}

interface EvaluationRow {
  model: string; level: string; wape: number | null; mae: number | null;
  bias: number | null; mase_mean: number | null; relmae: number | null;
}

function EvaluationView({ level }: { level: ForecastLevel }) {
  const rows = evaluation.metrics as EvaluationRow[];
  const decimal = (value: number | null, digits: number) =>
    value === null ? text.common.notAvailable : value.toFixed(digits);
  const columns: Column<EvaluationRow>[] = [
    { key: "level", header: t.evalLevel, tone: "strong",
      cell: (r) => (
        <>
          {t.levels[r.level as ForecastLevel] ?? r.level}
          {r.level === level && <span className={styles.selected}> ({t.selectedLevel})</span>}
        </>
      ) },
    { key: "model", header: t.evalModel, cell: (r) => t.modelNames[r.model] ?? r.model },
    { key: "wape", header: t.wape, align: "end", cell: (r) => percent(r.wape) },
    { key: "mae", header: t.mae, align: "end", cell: (r) => decimal(r.mae, 2) },
    { key: "bias", header: t.bias, align: "end", cell: (r) => percent(r.bias, 2) },
    { key: "mase", header: t.mase, align: "end", cell: (r) => decimal(r.mase_mean, 2) },
    { key: "relmae", header: t.relmae, align: "end",
      cell: (r) => (r.model === "seasonal_naive" ? t.reference : decimal(r.relmae, 2)) },
  ];
  const ordered = LEVELS.flatMap((l) => rows.filter((r) => r.level === l));
  return (
    <Card>
      <p className={styles.evaluationLabel} role="note">
        <Badge tone="upcoming">{evaluation.label}</Badge>
      </p>
      <p className={styles.tableNote}>
        {t.evaluationIntro(evaluation.folds, evaluation.fold_horizon_days,
          formatDate(evaluation.first_cutoff), formatDate(evaluation.last_cutoff))}
      </p>
      <DataTable caption={evaluation.label} columns={columns} rows={ordered}
        rowKey={(r) => `${r.level}-${r.model}`} />
      <p className={styles.tableNote}>
        {t.evaluationRun(evaluation.run_id, evaluation.data.seed,
          formatDate(evaluation.data.start), formatDate(evaluation.data.end))}{" "}
        {t.evaluationLimits}
      </p>
    </Card>
  );
}
