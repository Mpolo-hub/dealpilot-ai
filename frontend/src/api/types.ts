// Response types of the spec 002 API (v1), exactly as documented. Money is a decimal
// string (`^[0-9]+\.[0-9]{2}$`, spec 002 section 3.3) and stays a string here.

export type IsoDate = string; // YYYY-MM-DD
export type Money = string;

export interface Health {
  status: string;
  version: string;
}

export interface Metadata {
  seed: number;
  start: IsoDate;
  end: IsoDate;
  generator_version: string;
  library_versions: Record<string, string | null> | null;
  row_counts: Record<string, number>;
}

export interface Region {
  region_id: string;
  name: string;
}

export interface Product {
  product_id: string;
  name: string;
  category: string;
  launch_date: IsoDate;
  discontinue_date: IsoDate | null;
}

export interface Dimensions {
  date_range: { start: IsoDate; end: IsoDate };
  group_by: string[];
  intervals: string[];
  metrics: string[];
  regions: Region[];
  categories: string[];
  products: Product[];
}

export type GroupBy = "date" | "product" | "category" | "region";
export type Interval = "day" | "week" | "month";

export interface MetricValues {
  units: number;
  revenue: Money;
  orders: number;
  order_lines: number;
}

export interface MetricsRow extends MetricValues {
  date?: IsoDate;
  product_id?: string;
  category?: string;
  region_id?: string;
}

export interface SalesMetrics {
  start: IsoDate;
  end: IsoDate;
  group_by: GroupBy[];
  interval: Interval | null;
  filters: { product_id: string[]; category: string[]; region_id: string[] };
  metrics: string[];
  rows: MetricsRow[];
  totals: MetricValues;
  row_count: number;
}

export interface MetricsQuery {
  start?: IsoDate;
  end?: IsoDate;
  group_by?: GroupBy[];
  interval?: Interval;
  product_id?: string[];
  category?: string[];
  region_id?: string[];
}
