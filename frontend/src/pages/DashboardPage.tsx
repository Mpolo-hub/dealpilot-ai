// Dashboard (spec 007 section 5.1, reference `dashboard.png`).
import { DIMENSIONS, METADATA, metricsPath } from "../api/endpoints";
import type { Dimensions, Metadata, SalesMetrics } from "../api/types";
import { DonutChart } from "../components/charts/DonutChart";
import { LineChart } from "../components/charts/LineChart";
import { DateRangeControl } from "../components/DateRangeControl";
import {
  Badge, Card, ChangeBadge, DataUnavailable, EmptyState, Grid, KpiCard, KpiRow, LegendKey,
  PageHeader,
} from "../components/ui";
import { eachDay, fillBuckets, formatDate } from "../domain/dates";
import { formatCount } from "../domain/format";
import { formatMoney, formatMoneyCompact, moneyChange, moneyShare, toDollars } from "../domain/money";
import { comparisonRange, productStatus } from "../domain/rules";
import { useApi } from "../hooks/useApi";
import { useUrlRange } from "../hooks/useUrlState";
import { text } from "../text/en";
import { anyDataUnavailable, monthTicks } from "./pageState";
import { Loaded } from "./shared";

const t = text.dashboard;

export function DashboardPage() {
  const [dims, retryDims] = useApi<Dimensions>(DIMENSIONS);
  const [meta, retryMeta] = useApi<Metadata>(METADATA);
  const dataset = dims.status === "ready" ? dims.data.date_range : null;
  const [range, setRange] = useUrlRange(dataset);
  const previous = range && dataset
    ? comparisonRange(range.start, range.end, dataset.start, dataset.end) : null;

  const [totals, retryTotals] = useApi<SalesMetrics>(range ? metricsPath(range) : null);
  const [prior] = useApi<SalesMetrics>(previous ? metricsPath(previous) : null);
  const [daily, retryDaily] = useApi<SalesMetrics>(
    range ? metricsPath({ ...range, group_by: ["date"], interval: "day" }) : null);
  const [regions, retryRegions] = useApi<SalesMetrics>(
    range ? metricsPath({ ...range, group_by: ["region"] }) : null);

  if (anyDataUnavailable([dims, meta, totals, prior, daily, regions])) return <DataUnavailable />;

  const header = (
    <PageHeader title={t.title} subtitle={t.subtitle}>
      {dataset && range && <DateRangeControl dataset={dataset} value={range} onChange={setRange} />}
    </PageHeader>
  );
  if (dims.status !== "ready" || !range) {
    return <>{header}<Loaded state={dims} retry={retryDims}>{() => null}</Loaded></>;
  }
  const products = dims.data.products;
  const activeCount = products.filter((p) => productStatus(p, range.end) === "active").length;
  // D3: a badge only when the same period last year lies inside the dataset.
  const badge = (change: (before: SalesMetrics) => number | null) => {
    if (!previous || prior.status === "loading") return undefined;
    if (prior.status === "error") return <Badge tone="neutral">{text.common.notAvailable}</Badge>;
    return <ChangeBadge label={t.vsLastYear} change={change(prior.data)} />;
  };

  return (
    <>
      {header}
      <KpiRow>
        <Loaded state={totals} retry={retryTotals} height={88}>
          {(m) => (
            <KpiCard icon="money" label={t.totalSales} value={formatMoneyCompact(toDollars(m.totals.revenue))}
              exact={formatMoney(m.totals.revenue)}
              badge={badge((before) => moneyChange(m.totals.revenue, before.totals.revenue))} />
          )}
        </Loaded>
        <Loaded state={totals} retry={retryTotals} height={88}>
          {(m) => (
            <KpiCard icon="orders" label={t.orders} value={formatCount(m.totals.orders)}
              badge={badge((before) => before.totals.orders === 0 ? null
                : (m.totals.orders - before.totals.orders) / before.totals.orders)} />
          )}
        </Loaded>
        <KpiCard icon="box" label={t.products} value={formatCount(activeCount)}
          note={t.activeNote(formatCount(products.length), formatDate(range.end))}
          badge={<Badge tone="positive">{t.active}</Badge>} />
        <Loaded state={meta} retry={retryMeta} height={88}>
          {(m) => (
            <KpiCard icon="users" label={t.customers} note={t.customersNote}
              value={m.row_counts.customers === undefined ? text.common.notAvailable
                : formatCount(m.row_counts.customers)} />
          )}
        </Loaded>
      </KpiRow>
      <Grid variant="wide-narrow">
        <Card title={t.dailySales} icon="bars"
          actions={<LegendKey label={t.actualSales} />}>
          <Loaded state={daily} retry={retryDaily} height={260}>
            {(m) => {
              if (m.totals.units === 0) return <EmptyState />;
              const days = eachDay(range.start, range.end);
              const series = fillBuckets(days, m.rows, (row: { revenue: string }) => toDollars(row.revenue));
              return (
                <LineChart title={t.dailySales} valueHeader={t.sales}
                  data={series.map((p) => ({ label: formatDate(p.date), value: p.value,
                    display: formatMoneyCompact(p.value) }))}
                  axisLabel={formatMoneyCompact} ticks={monthTicks(days)} />
              );
            }}
          </Loaded>
        </Card>
        <Card title={t.salesByRegion} icon="pie">
          <Loaded state={regions} retry={retryRegions} height={220}>
            {(m) => {
              if (m.totals.units === 0) return <EmptyState />;
              const byId = new Map(m.rows.map((r) => [r.region_id, r.revenue]));
              const rows = dims.data.regions.map((r) => ({ name: r.name, revenue: byId.get(r.region_id) ?? "0.00" }));
              return (
                <DonutChart title={t.salesByRegion} valueHeader={t.sales}
                  data={rows.map((r) => ({ label: r.name, value: toDollars(r.revenue), display: formatMoney(r.revenue) }))}
                  shares={rows.map((r) => moneyShare(r.revenue, m.totals.revenue))}
                  centerValue={formatMoneyCompact(toDollars(m.totals.revenue))} centerLabel={t.sales} />
              );
            }}
          </Loaded>
        </Card>
      </Grid>
    </>
  );
}
