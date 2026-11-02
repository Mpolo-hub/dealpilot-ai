// Products (spec 007 section 5.3, reference `product_custom.png`): read-only list with
// sales over the whole dataset, and a Categories tab. No Price column (spec 002 D8), no
// Performance tab (D2), no "New product" button (read-only API).
import { DIMENSIONS, metricsPath } from "../api/endpoints";
import type { Dimensions, MetricsRow, SalesMetrics } from "../api/types";
import { DataTable } from "../components/DataTable";
import {
  Card, DataUnavailable, EmptyState, FilterRow, PageHeader, ResultCount, SearchBox, Select,
  StatusBadge, Tabs,
} from "../components/ui";
import { formatDate } from "../domain/dates";
import { formatCount } from "../domain/format";
import { formatMoney, toCents } from "../domain/money";
import { productStatus, type ProductStatus } from "../domain/rules";
import { useApi } from "../hooks/useApi";
import { useUrlParam } from "../hooks/useUrlState";
import { text } from "../text/en";
import { anyDataUnavailable } from "./pageState";
import { Loaded } from "./shared";

const t = text.products;
const TABS = [{ id: "all", label: t.tabAll }, { id: "categories", label: t.tabCategories }];
const STATUSES: ProductStatus[] = ["active", "discontinued", "not_launched"];

export function ProductsPage() {
  const [dims, retryDims] = useApi<Dimensions>(DIMENSIONS);
  const [tabParam] = useUrlParam("tab");
  const tab = tabParam === "categories" ? "categories" : "all";
  const range = dims.status === "ready" ? dims.data.date_range : null;
  const [sales, retrySales] = useApi<SalesMetrics>(
    range && tab === "all" ? metricsPath({ ...range, group_by: ["product"] }) : null);
  const [categories, retryCategories] = useApi<SalesMetrics>(
    range && tab === "categories" ? metricsPath({ ...range, group_by: ["category"] }) : null);
  const [query, setQuery] = useUrlParam("q");
  const [category, setCategory] = useUrlParam("category");
  const [status, setStatus] = useUrlParam("status");

  if (anyDataUnavailable([dims, sales, categories])) return <DataUnavailable />;
  return (
    <>
      <PageHeader title={t.title} subtitle={t.subtitle} />
      <Tabs tabs={TABS} current={tab} label={t.title} />
      <Loaded state={dims} retry={retryDims}>
        {(d) => tab === "all" ? (
          <Card>
            <FilterRow>
              <SearchBox id="product-search" label={t.searchLabel} placeholder={t.search}
                value={query ?? ""} onChange={(v) => setQuery(v || null)} />
              <Select id="product-category" label={t.category}
                value={d.categories.includes(category ?? "") ? category ?? "" : ""}
                onChange={(v) => setCategory(v || null)}
                options={[{ value: "", label: text.common.all }, ...d.categories.map((c) => ({ value: c, label: c }))]} />
              <Select id="product-status" label={t.status}
                value={STATUSES.includes(status as ProductStatus) ? status ?? "" : ""}
                onChange={(v) => setStatus(v || null)}
                options={[{ value: "", label: text.common.all },
                  ...STATUSES.map((s) => ({ value: s, label: t.statuses[s] }))]} />
            </FilterRow>
            <Loaded state={sales} retry={retrySales} height={360}>
              {(m) => <ProductTable dims={d} rows={m.rows} query={query ?? ""} category={category ?? ""}
                status={status ?? ""} />}
            </Loaded>
            <p className="table-note">
              {t.salesPeriod(formatDate(d.date_range.start), formatDate(d.date_range.end))}{" "}
              {t.statusNote(formatDate(d.date_range.end))}
            </p>
          </Card>
        ) : (
          <Card>
            <Loaded state={categories} retry={retryCategories} height={240}>
              {(m) => <CategoryTable dims={d} rows={m.rows} />}
            </Loaded>
            <p className="table-note">
              {t.salesPeriod(formatDate(d.date_range.start), formatDate(d.date_range.end))}
            </p>
          </Card>
        )}
      </Loaded>
    </>
  );
}

function ProductTable({ dims, rows, query, category, status }: {
  dims: Dimensions; rows: MetricsRow[]; query: string; category: string; status: string;
}) {
  const reference = dims.date_range.end; // D4: Products uses the dataset end
  const revenue = new Map(rows.map((r) => [r.product_id, r.revenue]));
  const needle = query.trim().toLowerCase();
  const list = dims.products
    .map((p) => ({ ...p, revenue: revenue.get(p.product_id) ?? "0.00", status: productStatus(p, reference) }))
    .filter((p) => !needle || p.product_id.toLowerCase().includes(needle) || p.name.toLowerCase().includes(needle))
    .filter((p) => !dims.categories.includes(category) || p.category === category)
    .filter((p) => !STATUSES.includes(status as ProductStatus) || p.status === status);
  return (
    <>
      <ResultCount>{t.count(formatCount(list.length), formatCount(dims.products.length))}</ResultCount>
      <DataTable caption={t.title} rows={list} rowKey={(p) => p.product_id}
      initialSort={{ key: "id", direction: "asc" }} empty={<EmptyState message={t.noMatch} />}
      columns={[
        { key: "id", header: t.id, tone: "muted", cell: (p) => p.product_id, sortValue: (p) => p.product_id },
        { key: "name", header: t.name, tone: "strong", cell: (p) => p.name, sortValue: (p) => p.name },
        { key: "category", header: t.category, cell: (p) => p.category, sortValue: (p) => p.category },
        { key: "sales", header: t.sales, align: "end", cell: (p) => formatMoney(p.revenue),
          sortValue: (p) => toCents(p.revenue) },
        { key: "status", header: t.status, cell: (p) => <StatusBadge status={p.status} label={t.statuses[p.status]} />,
          sortValue: (p) => p.status },
      ]} />
    </>
  );
}

function CategoryTable({ dims, rows }: { dims: Dimensions; rows: MetricsRow[] }) {
  const byName = new Map(rows.map((r) => [r.category, r]));
  const list = dims.categories.map((c) => ({
    category: c, count: dims.products.filter((p) => p.category === c).length,
    units: 0, revenue: "0.00", orders: 0, order_lines: 0, ...byName.get(c),
  }));
  return (
    <DataTable caption={t.tabCategories} rows={list} rowKey={(r) => r.category ?? ""}
      initialSort={{ key: "revenue", direction: "desc" }}
      columns={[
        { key: "category", header: t.category, tone: "strong", cell: (r) => r.category, sortValue: (r) => r.category ?? "" },
        { key: "count", header: t.productCount, align: "end", cell: (r) => formatCount(r.count), sortValue: (r) => r.count },
        { key: "units", header: text.analysis.units, align: "end", cell: (r) => formatCount(r.units), sortValue: (r) => r.units },
        { key: "revenue", header: text.analysis.revenue, align: "end", cell: (r) => formatMoney(r.revenue), sortValue: (r) => toCents(r.revenue) },
        { key: "orders", header: text.analysis.orders, align: "end", cell: (r) => formatCount(r.orders), sortValue: (r) => r.orders },
        { key: "lines", header: text.analysis.orderLines, align: "end", cell: (r) => formatCount(r.order_lines), sortValue: (r) => r.order_lines },
      ]} />
  );
}
