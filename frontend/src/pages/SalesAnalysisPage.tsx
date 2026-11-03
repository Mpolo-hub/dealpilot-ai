// Sales analysis (spec 007 section 5.2, reference `seal.png`): Overview, By product and
// By region tabs. By customer and Promotion effects have no contract and are hidden (D2).
import { DIMENSIONS, metricsPath } from "../api/endpoints";
import type { Dimensions, MetricsQuery, MetricsRow, SalesMetrics } from "../api/types";
import { ColumnChart, HorizontalBarChart } from "../components/charts/BarCharts";
import { DataTable, type Column } from "../components/DataTable";
import { DateRangeControl } from "../components/DateRangeControl";
import {
  Badge, Card, ChangeBadge, DataUnavailable, EmptyState, FilterRow, Grid, KpiCard, KpiRow,
  PageHeader, Select, Tabs,
} from "../components/ui";
import { eachMonth, fillBuckets, maxDate, minDate, monthLabel, yearsBetween } from "../domain/dates";
import { formatCount } from "../domain/format";
import { compareMoney, formatMoney, formatMoneyCompact, moneyChange, toCents, toDollars } from "../domain/money";
import { averageRevenuePerOpenDay, comparisonRange } from "../domain/rules";
import { useApi, type ApiState } from "../hooks/useApi";
import { useUrlParam, useUrlRange, type Range } from "../hooks/useUrlState";
import { text } from "../text/en";
import { anyDataUnavailable } from "./pageState";
import { Loaded } from "./shared";

const t = text.analysis;
const TABS = [
  { id: "overview", label: t.tabOverview },
  { id: "products", label: t.tabProducts },
  { id: "regions", label: t.tabRegions },
];

/** Highest revenue first; ties broken by ID (spec 007 section 5.2). */
function byRevenue(id: (row: MetricsRow) => string) {
  return (a: MetricsRow, b: MetricsRow) => compareMoney(b.revenue, a.revenue)
    || id(a).localeCompare(id(b));
}

export function SalesAnalysisPage() {
  const [dims, retryDims] = useApi<Dimensions>(DIMENSIONS);
  const dataset = dims.status === "ready" ? dims.data.date_range : null;
  const [range, setRange] = useUrlRange(dataset);
  const [tabParam] = useUrlParam("tab");
  const tab = TABS.some((x) => x.id === tabParam) ? tabParam! : "overview";

  if (dims.status === "error" && anyDataUnavailable([dims])) return <DataUnavailable />;
  return (
    <>
      <PageHeader title={t.title} subtitle={t.subtitle}>
        {dataset && range && <DateRangeControl dataset={dataset} value={range} onChange={setRange} />}
      </PageHeader>
      <Tabs tabs={TABS} current={tab} label={t.title} />
      {dims.status !== "ready" || !range || !dataset
        ? <Loaded state={dims} retry={retryDims}>{() => null}</Loaded>
        : tab === "overview" ? <Overview dims={dims.data} range={range} dataset={dataset} />
          : tab === "products" ? <ByProduct dims={dims.data} range={range} />
            : <ByRegion dims={dims.data} range={range} />}
    </>
  );
}

function Overview({ dims, range, dataset }: { dims: Dimensions; range: Range; dataset: Range }) {
  const previous = comparisonRange(range.start, range.end, dataset.start, dataset.end);
  const years = yearsBetween(dataset.start, dataset.end);
  const [yearParam, setYear] = useUrlParam("year");
  const year = years.includes(Number(yearParam)) ? Number(yearParam) : Number(range.end.slice(0, 4));
  const yearRange = { start: maxDate(`${year}-01-01`, dataset.start), end: minDate(`${year}-12-31`, dataset.end) };

  const [totals, retryTotals] = useApi<SalesMetrics>(metricsPath(range));
  const [prior] = useApi<SalesMetrics>(previous ? metricsPath(previous) : null);
  const [byProduct, retryProducts] = useApi<SalesMetrics>(metricsPath({ ...range, group_by: ["product"] }));
  const [byRegion, retryRegions] = useApi<SalesMetrics>(metricsPath({ ...range, group_by: ["region"] }));
  const [monthly, retryMonthly] = useApi<SalesMetrics>(
    metricsPath({ ...yearRange, group_by: ["date"], interval: "month" }));
  if (anyDataUnavailable([totals, prior, byProduct, byRegion, monthly])) return <DataUnavailable />;

  const productName = new Map(dims.products.map((p) => [p.product_id, p.name]));
  const regionName = new Map(dims.regions.map((r) => [r.region_id, r.name]));
  const growth = !previous ? text.common.notAvailable
    : prior.status === "ready" && totals.status === "ready"
      ? <ChangeBadge label={t.vsLastYear} change={moneyChange(totals.data.totals.revenue, prior.data.totals.revenue)} />
      : prior.status === "error" ? <Badge tone="neutral">{text.common.notAvailable}</Badge> : null;

  return (
    <>
      <KpiRow>
        <Loaded state={totals} retry={retryTotals} height={88}>
          {(m) => {
            const average = averageRevenuePerOpenDay(m.totals.revenue, range.start, range.end);
            return <KpiCard icon="money" label={t.averagePerDay} note={t.averageNote}
              value={average === null ? text.common.notAvailable : formatMoneyCompact(average)} />;
          }}
        </Loaded>
        <Loaded state={byProduct} retry={retryProducts} height={88}>
          {(m) => {
            const top = [...m.rows].sort(byRevenue((r) => r.product_id ?? ""))[0];
            return <KpiCard icon="trophy" label={t.topProduct}
              value={top?.product_id ?? text.common.notAvailable}
              note={top ? `${productName.get(top.product_id ?? "") ?? ""} · ${formatMoneyCompact(toDollars(top.revenue))}` : undefined} />;
          }}
        </Loaded>
        <Loaded state={byRegion} retry={retryRegions} height={88}>
          {(m) => {
            const top = [...m.rows].sort(byRevenue((r) => r.region_id ?? ""))[0];
            return <KpiCard icon="pin" label={t.topRegion}
              value={top ? regionName.get(top.region_id ?? "") ?? top.region_id : text.common.notAvailable}
              note={top ? formatMoneyCompact(toDollars(top.revenue)) : undefined} />;
          }}
        </Loaded>
        <KpiCard icon="trend" label={t.growth} value={growth ?? text.common.loading}
          note={previous ? t.vsLastYear : t.growthUnavailable} />
      </KpiRow>
      <Grid variant="halves">
        <Card title={t.topProducts} icon="trophy">
          <Loaded state={byProduct} retry={retryProducts} height={280}>
            {(m) => m.totals.units === 0 ? <EmptyState /> : (
              <HorizontalBarChart title={t.topProducts} valueHeader={t.revenue}
                data={[...m.rows].sort(byRevenue((r) => r.product_id ?? "")).slice(0, 10).map((r) => ({
                  label: r.product_id ?? "", value: toDollars(r.revenue),
                  display: formatMoneyCompact(toDollars(r.revenue)),
                }))} />
            )}
          </Loaded>
        </Card>
        <Card title={t.salesByMonth} icon="calendar" actions={
          <Select id="year" label={t.year} value={String(year)} inline
            options={years.map((y) => ({ value: String(y), label: String(y) }))}
            onChange={(value) => setYear(value)} />
        }>
          <MonthlyChart state={monthly} retry={retryMonthly} range={yearRange} />
        </Card>
      </Grid>
    </>
  );
}

function MonthlyChart({ state, retry, range }: { state: ApiState<SalesMetrics>; retry: () => void; range: Range }) {
  return (
    <Loaded state={state} retry={retry} height={240}>
      {(m) => {
        if (m.totals.units === 0) return <EmptyState />;
        const months = eachMonth(range.start, range.end);
        const series = fillBuckets(months, m.rows, (row: { revenue: string }) => toDollars(row.revenue));
        return (
          <ColumnChart title={t.salesByMonth} valueHeader={t.revenue} axisLabel={formatMoneyCompact}
            tickLabels={months.map(monthLabel)}
            data={series.map((p) => ({ label: `${monthLabel(p.date)} ${p.date.slice(0, 4)}`,
              value: p.value, display: formatMoneyCompact(p.value) }))} />
        );
      }}
    </Loaded>
  );
}

const metricColumns: Column<MetricsRow>[] = [
  { key: "units", header: t.units, align: "end", cell: (r) => formatCount(r.units), sortValue: (r) => r.units },
  { key: "revenue", header: t.revenue, align: "end", cell: (r) => formatMoney(r.revenue), sortValue: (r) => toCents(r.revenue) },
  { key: "orders", header: t.orders, align: "end", cell: (r) => formatCount(r.orders), sortValue: (r) => r.orders },
  { key: "order_lines", header: t.orderLines, align: "end", cell: (r) => formatCount(r.order_lines), sortValue: (r) => r.order_lines },
];

const zero = { units: 0, revenue: "0.00", orders: 0, order_lines: 0 };

function useFilterList(name: string): [string, (value: string) => void] {
  const [value, setValue] = useUrlParam(name);
  return [value ?? "", (next) => setValue(next || null)];
}

function ByProduct({ dims, range }: { dims: Dimensions; range: Range }) {
  const [category, setCategory] = useFilterList("category");
  const [region, setRegion] = useFilterList("region");
  const validCategory = dims.categories.includes(category) ? category : "";
  const validRegion = dims.regions.some((r) => r.region_id === region) ? region : "";
  const query: MetricsQuery = { ...range, group_by: ["product"] };
  if (validCategory) query.category = [validCategory];
  if (validRegion) query.region_id = [validRegion];
  const [state, retry] = useApi<SalesMetrics>(metricsPath(query));
  if (anyDataUnavailable([state])) return <DataUnavailable />;

  type Row = MetricsRow & { name: string; categoryName: string };
  return (
    <Card title={t.tabProducts} icon="products">
      <FilterRow>
        <Select id="category" label={t.category} value={validCategory} onChange={setCategory}
          options={[{ value: "", label: text.common.all }, ...dims.categories.map((c) => ({ value: c, label: c }))]} />
        <Select id="region" label={t.region} value={validRegion} onChange={setRegion}
          options={[{ value: "", label: text.common.all }, ...dims.regions.map((r) => ({ value: r.region_id, label: r.name }))]} />
      </FilterRow>
      <Loaded state={state} retry={retry} height={320}>
        {(m) => {
          const byId = new Map(m.rows.map((r) => [r.product_id, r]));
          const rows: Row[] = dims.products
            .filter((p) => !validCategory || p.category === validCategory)
            .map((p) => ({ ...zero, ...byId.get(p.product_id), product_id: p.product_id, name: p.name,
              categoryName: p.category }));
          return (
            <>
              <DataTable caption={t.tabProducts} rows={rows} rowKey={(r) => r.product_id ?? ""}
                initialSort={{ key: "revenue", direction: "desc" }}
                columns={[
                  { key: "id", header: t.product, tone: "muted", cell: (r) => r.product_id, sortValue: (r) => r.product_id ?? "" },
                  { key: "name", header: text.products.name, tone: "strong", cell: (r) => r.name, sortValue: (r) => r.name },
                  { key: "category", header: t.category, cell: (r) => r.categoryName, sortValue: (r) => r.categoryName },
                  ...(metricColumns as Column<Row>[]),
                ]} />
              <p className="table-note">{t.ordersNote}</p>
            </>
          );
        }}
      </Loaded>
    </Card>
  );
}

function ByRegion({ dims, range }: { dims: Dimensions; range: Range }) {
  const [category, setCategory] = useFilterList("category");
  const [product, setProduct] = useFilterList("product");
  const validCategory = dims.categories.includes(category) ? category : "";
  const validProduct = dims.products.some((p) => p.product_id === product) ? product : "";
  const query: MetricsQuery = { ...range, group_by: ["region"] };
  if (validCategory) query.category = [validCategory];
  if (validProduct) query.product_id = [validProduct];
  const [state, retry] = useApi<SalesMetrics>(metricsPath(query));
  if (anyDataUnavailable([state])) return <DataUnavailable />;

  type Row = MetricsRow & { name: string };
  return (
    <Card title={t.tabRegions} icon="pin">
      <FilterRow>
        <Select id="category" label={t.category} value={validCategory} onChange={setCategory}
          options={[{ value: "", label: text.common.all }, ...dims.categories.map((c) => ({ value: c, label: c }))]} />
        <Select id="product" label={t.product} value={validProduct} onChange={setProduct}
          options={[{ value: "", label: text.common.all },
            ...dims.products.map((p) => ({ value: p.product_id, label: `${p.product_id} · ${p.name}` }))]} />
      </FilterRow>
      <Loaded state={state} retry={retry} height={320}>
        {(m) => {
          const byId = new Map(m.rows.map((r) => [r.region_id, r]));
          const rows: Row[] = dims.regions.map((r) => ({ ...zero, ...byId.get(r.region_id),
            region_id: r.region_id, name: r.name }));
          return (
            <Grid variant="chart-table">
              <div>
                {m.totals.units === 0 ? <EmptyState /> : (
                  <HorizontalBarChart title={t.salesByRegion} valueHeader={t.revenue} labelWidth={110}
                    data={rows.map((r) => ({ label: r.name, value: toDollars(r.revenue),
                      display: formatMoneyCompact(toDollars(r.revenue)) }))} />
                )}
              </div>
              <DataTable caption={t.tabRegions} rows={rows} rowKey={(r) => r.region_id ?? ""}
                initialSort={{ key: "revenue", direction: "desc" }}
                columns={[
                  { key: "name", header: t.region, tone: "strong", cell: (r) => r.name, sortValue: (r) => r.name },
                  ...(metricColumns as Column<Row>[]),
                ]} />
            </Grid>
          );
        }}
      </Loaded>
    </Card>
  );
}
