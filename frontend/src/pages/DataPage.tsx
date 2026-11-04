// Data (spec 007 section 5.4, reference `data_manage.png`): read-only dataset overview and
// metadata. No file sizes or dates (not in the API), no Tables tab (D2), no "Generate data"
// button (read-only API). `parameters` is never requested or shown.
import { HEALTH, METADATA } from "../api/endpoints";
import type { Health, Metadata } from "../api/types";
import { DataTable } from "../components/DataTable";
import { Icon } from "../components/Icons";
import { Card, DataUnavailable, KpiCard, KpiRow, PageHeader, Tabs } from "../components/ui";
import { daysInclusive, formatDate } from "../domain/dates";
import { formatCount } from "../domain/format";
import { useApi, type ApiState } from "../hooks/useApi";
import { useUrlParam } from "../hooks/useUrlState";
import { text } from "../text/en";
import { tableRows } from "./dataTables";
import { anyDataUnavailable } from "./pageState";
import { Loaded } from "./shared";

const t = text.data;
const TABS = [{ id: "overview", label: t.tabOverview }, { id: "metadata", label: t.tabMetadata }];

export function DataPage() {
  const [meta, retryMeta] = useApi<Metadata>(METADATA);
  const [tabParam] = useUrlParam("tab");
  const tab = tabParam === "metadata" ? "metadata" : "overview";
  const [health, retryHealth] = useApi<Health>(HEALTH);

  if (anyDataUnavailable([meta])) return <DataUnavailable />;
  return (
    <>
      <PageHeader title={t.title} subtitle={t.subtitle} />
      <Card title={t.syntheticTitle} icon="info">
        <p className="table-note">{t.syntheticNotice}</p>
      </Card>
      <Tabs tabs={TABS} current={tab} label={t.title} />
      <Loaded state={meta} retry={retryMeta} height={280}>
        {(m) => (
          <>
            <KpiRow>
              <KpiCard icon="data" label={t.seed} value={String(m.seed)}
                note={t.seedNote(m.generator_version)} />
              <KpiCard icon="calendar" label={t.periodCard} textValue
                value={t.periodDays(formatCount(daysInclusive(m.start, m.end)))}
                note={t.periodNote(formatDate(m.start), formatDate(m.end))} />
              <KpiCard icon="table" label={t.tablesCard}
                value={formatCount(Object.keys(m.row_counts).length)} note={t.tablesNote} />
              <Loaded state={health} retry={retryHealth} height={88}>
                {(h) => <KpiCard icon="info" label={t.apiVersion} value={h.version}
                  note={t.apiNote(h.status)} />}
              </Loaded>
            </KpiRow>
            <Card title={tab === "overview" ? t.tabOverview : t.tabMetadata}
              icon={tab === "overview" ? "table" : "info"}>
              {tab === "overview" ? (
                <DataTable caption={t.tabOverview} rows={tableRows(m.row_counts)} rowKey={(r) => r.table}
                  columns={[
                    { key: "table", header: t.table, tone: "strong", cell: (r) => (
                      <span className="table-name"><Icon name="file" size={16} />
                        {t.tableNames[r.table] ?? r.table}</span>
                    ), sortValue: (r) => t.tableNames[r.table] ?? r.table },
                    { key: "rows", header: t.rows, align: "end", cell: (r) => formatCount(r.rows),
                      sortValue: (r) => r.rows },
                  ]} />
              ) : (
                <DataTable caption={t.tabMetadata} rows={metadataRows(m, health)} rowKey={(r) => r.field}
                  columns={[
                    { key: "field", header: t.field, tone: "muted", cell: (r) => r.field },
                    { key: "value", header: t.value, tone: "strong", cell: (r) => r.value },
                  ]} />
              )}
            </Card>
          </>
        )}
      </Loaded>
    </>
  );
}

function metadataRows(m: Metadata, health: ApiState<Health>): { field: string; value: string }[] {
  const versions = m.library_versions === null ? t.notRecorded : Object.entries(m.library_versions)
    .map(([name, version]) => `${name} ${version ?? t.notRecorded}`).join(", ");
  return [
    { field: t.seed, value: String(m.seed) },
    { field: t.start, value: formatDate(m.start) },
    { field: t.end, value: formatDate(m.end) },
    { field: t.generatorVersion, value: m.generator_version },
    { field: t.libraryVersions, value: versions },
    { field: t.apiVersion, value: health.status === "ready" ? health.data.version
      : health.status === "error" ? text.common.notAvailable : text.common.loading },
  ];
}
