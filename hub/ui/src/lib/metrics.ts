/**
 * Metric metadata — vendored copy of schemas/metrics_schema.json (the canonical
 * source shared by dsnode / Hub API / Web UI / VictoriaMetrics). Re-copy the file
 * from schemas/metrics_schema.json when it changes.
 */
import schema from "./metrics-schema.json";
import { formatBytes, formatNumber, formatSiBytes, parseUTC } from "./format";

export interface MetricField {
  name: string;
  go_field: string;
  label: string;
  type: string;
  unit: string;
  aggregate: string;
  description: string;
}

export const METRIC_FIELDS: MetricField[] = schema.measurements.device_metric.fields;

const FIELD_MAP = new Map(METRIC_FIELDS.map((f) => [f.name, f]));

export function metricMeta(name: string): MetricField | undefined {
  return FIELD_MAP.get(name);
}

export function metricLabel(name: string): string {
  return FIELD_MAP.get(name)?.label ?? name.replace(/_/g, " ");
}

export function metricUnit(name: string): string {
  return FIELD_MAP.get(name)?.unit ?? "";
}

/** Metrics that are more useful as raw numbers (no chart button) — bitmask etc. */
const NO_CHART = new Set(["nvme_critical_warning"]);

export function isChartable(name: string): boolean {
  return !NO_CHART.has(name);
}

export function formatMetricValue(name: string, value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const unit = metricUnit(name);
  switch (unit) {
    case "bytes":
      return formatBytes(value);
    case "°C":
      return `${Math.round(value * 10) / 10} °C`;
    case "%":
      return `${Math.round(value * 10) / 10}%`;
    case "hours":
      return `${formatNumber(Math.round(value))} h`;
    case "minutes":
      return `${formatNumber(Math.round(value))} min`;
    case "bitmask":
      return `0x${value.toString(16).toUpperCase().padStart(2, "0")}`;
    default:
      return formatNumber(Math.round(value * 100) / 100);
  }
}

/** SI (1000‑based) bytes display — used as secondary value for bytes metrics. */
export function formatSiMetricValue(name: string, value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (metricUnit(name) !== "bytes") return formatMetricValue(name, value);
  return formatSiBytes(value);
}

/** Compact value used in chart Y axes. */
export function formatAxisValue(name: string, value: number): string {
  const unit = metricUnit(name);
  if (unit === "bytes") return formatBytes(value, 0);
  if (unit === "hours") return `${Math.round(value)}h`;
  if (unit === "minutes") return `${Math.round(value)}m`;
  if (unit === "°C") return `${Math.round(value * 10) / 10}°C`;
  if (unit === "%") return `${Math.round(value)}%`;
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 10_000) return `${(value / 1_000).toFixed(1)}k`;
  return `${Math.round(value * 10) / 10}`;
}

/** A single metrics sample returned by the API (time + arbitrary metric fields). */
export interface MetricSample {
  time: string;
  device_id?: string;
  [key: string]: unknown;
}

export interface MetricsQueryResult {
  items: MetricSample[];
  speed: {
    avg_write_speed_bytes?: number;
    avg_read_speed_bytes?: number;
  } | null;
}

/** Chart range tabs -> API period mapping. */
export type ChartRange = "day" | "week" | "month" | "year";

export const RANGE_PERIOD: Record<ChartRange, string> = {
  day: "hour", // hourly bins over the last 24h
  week: "day", // daily bins over 30 days, trimmed client-side to 7
  month: "day", // daily bins over 30 days
  year: "week", // weekly bins over 52 weeks
};

export const RANGE_DAYS: Record<ChartRange, number> = {
  day: 1,
  week: 7,
  month: 30,
  year: 365,
};

/** Periods used by the per-bucket read/write usage chart.
 *  Keep these windows in sync with app/services/metrics_store.py
 *  (_AGG_WINDOWS / _USAGE_WINDOWS). */
export type UsageRange = "hour" | "day" | "week" | "month" | "year";

export const USAGE_LOOKBACK_DAYS: Record<UsageRange, number> = {
  hour: 1,
  day: 30,
  week: 364,
  month: 365,
  year: 3650,
};

export const USAGE_RANGES: UsageRange[] = ["hour", "day", "week", "month", "year"];

/** Parse API timestamps; a missing tz suffix is treated as UTC. */
export function sampleTime(s: MetricSample): number {
  return parseUTC(s.time)?.getTime() ?? 0;
}
