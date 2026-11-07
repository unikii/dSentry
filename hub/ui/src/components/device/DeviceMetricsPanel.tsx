import { useEffect, useMemo, useState } from "react";
import { ChartColumn, X } from "lucide-react";
import { getDeviceMetrics } from "@/client";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { unwrap } from "@/lib/api";
import { getCurrentLocale, tStatic } from "@/i18n";
import { useLanguage } from "@/context/use-lang";
import type { MessageKey } from "@/context/lang-context";
import { formatBytes, formatDateTime, formatSpeed } from "@/lib/format";
import {
  METRIC_FIELDS,
  RANGE_DAYS,
  RANGE_PERIOD,
  USAGE_LOOKBACK_DAYS,
  USAGE_RANGES,
  formatAxisValue,
  formatMetricValue,
  formatSiMetricValue,
  isChartable,
  metricLabel,
  metricUnit,
  sampleTime,
  type ChartRange,
  type MetricSample,
  type MetricsQueryResult,
  type UsageRange,
} from "@/lib/metrics";
import { toastError } from "@/lib/toast";
import { cn } from "@/lib/utils";
import { MetricChart, type ChartPoint } from "./MetricChart";
import { RangeTabs } from "./RangeTabs";

interface DeviceMetricsPanelProps {
  deviceId: number;
  pushInterval?: number;
}

const MS_PER_DAY = 86_400_000;

function toNum(v: unknown): number | null {
  // The API can return null for a field that was absent from a sample. Number(null)
  // is 0, which would draw a false zero on the chart instead of a gap.
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function labelFor(t: number, range: ChartRange): string {
  const d = new Date(t);
  const locale = getCurrentLocale();
  if (range === "day") return d.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" });
  if (range === "year") return d.toLocaleDateString(locale, { month: "short", year: "2-digit" });
  return d.toLocaleDateString(locale, { month: "short", day: "numeric" });
}

function fullLabelFor(t: number): string {
  return new Date(t).toLocaleString(getCurrentLocale(), { dateStyle: "medium", timeStyle: "short" });
}

function usageLabelFor(t: number, range: UsageRange): string {
  const d = new Date(t);
  const locale = getCurrentLocale();
  if (range === "hour") return d.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" });
  if (range === "year") return d.toLocaleDateString(locale, { year: "numeric" });
  if (range === "month") return d.toLocaleDateString(locale, { month: "short", year: "2-digit" });
  return d.toLocaleDateString(locale, { month: "short", day: "numeric" });
}

/** Turn cumulative counter samples into per-bucket average speeds. */
function toSpeedPoints(samples: MetricSample[], field: string, range: ChartRange): ChartPoint[] {
  const cutoff = Date.now() - RANGE_DAYS[range] * MS_PER_DAY;
  const pts = samples
    .map((s) => ({ t: sampleTime(s), v: toNum(s[field]) }))
    .filter((p): p is { t: number; v: number } => p.v !== null && p.t >= cutoff)
    .sort((a, b) => a.t - b.t);

  const out: ChartPoint[] = [];
  for (let i = 1; i < pts.length; i++) {
    const dt = (pts[i].t - pts[i - 1].t) / 1000;
    const dv = pts[i].v - pts[i - 1].v;
    if (dt <= 0 || dv < 0) continue; // skip counter resets
    out.push({ label: labelFor(pts[i].t, range), fullLabel: fullLabelFor(pts[i].t), value: dv / dt });
  }
  return out;
}

function toValuePoints(samples: MetricSample[], field: string, range: ChartRange): ChartPoint[] {
  return samplesToPoints(samples, field, Date.now() - RANGE_DAYS[range] * MS_PER_DAY, (t) => ({
    label: labelFor(t, range),
    fullLabel: fullLabelFor(t),
  }));
}

function toUsagePoints(samples: MetricSample[], field: string, range: UsageRange): ChartPoint[] {
  return samplesToPoints(samples, field, Date.now() - USAGE_LOOKBACK_DAYS[range] * MS_PER_DAY, (t) => ({
    label: usageLabelFor(t, range),
    fullLabel: fullLabelFor(t),
  }));
}

function samplesToPoints(
  samples: MetricSample[],
  field: string,
  cutoff: number,
  label: (t: number) => { label: string; fullLabel: string },
): ChartPoint[] {
  return samples
    .map((s) => ({ t: sampleTime(s), v: toNum(s[field]) }))
    .filter((p): p is { t: number; v: number } => p.v !== null && p.t >= cutoff)
    .sort((a, b) => a.t - b.t)
    .map((p) => ({ ...label(p.t), value: p.v }));
}

const USAGE_UNIT_KEYS: Record<UsageRange, MessageKey> = {
  hour: "metrics.unitHour",
  day: "metrics.unitDay",
  week: "metrics.unitWeek",
  month: "metrics.unitMonth",
  year: "metrics.unitYear",
};

const USAGE_TAB_KEYS: Record<UsageRange, MessageKey> = {
  hour: "ranges.hour",
  day: "ranges.day",
  week: "ranges.week",
  month: "ranges.month",
  year: "ranges.year",
};

export function DeviceMetricsPanel({ deviceId, pushInterval }: DeviceMetricsPanelProps) {
  const { t } = useLanguage();
  const [latest, setLatest] = useState<MetricSample | null>(null);
  const [loadingLatest, setLoadingLatest] = useState(true);

  const [speedRange, setSpeedRange] = useState<ChartRange>("day");
  const [speeds, setSpeeds] = useState<{ write: ChartPoint[]; read: ChartPoint[] } | null>(null);
  const [loadingSpeeds, setLoadingSpeeds] = useState(false);

  const [usageRange, setUsageRange] = useState<UsageRange>("day");
  const [usage, setUsage] = useState<{ write: ChartPoint[]; read: ChartPoint[] } | null>(null);
  const [loadingUsage, setLoadingUsage] = useState(false);
  const [throughputOpen, setThroughputOpen] = useState(false);

  const [historyMetric, setHistoryMetric] = useState<string | null>(null);
  const [historyRange, setHistoryRange] = useState<ChartRange>("month");
  const [history, setHistory] = useState<ChartPoint[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(false);

  const hasWrite = useMemo(() => !!latest && latest.total_bytes_written != null, [latest]);
  const hasRead = useMemo(() => !!latest && latest.total_bytes_read != null, [latest]);
  const hasTotals = hasWrite || hasRead;
  const hourlyUsageEnabled = pushInterval != null && pushInterval <= 10;

  useEffect(() => {
    if (!hourlyUsageEnabled && usageRange === "hour") setUsageRange("day");
  }, [hourlyUsageEnabled, usageRange]);

  /* ---- latest sample ---- */
  useEffect(() => {
    let cancelled = false;
    setLoadingLatest(true);
    unwrap<MetricsQueryResult>(getDeviceMetrics({ path: { device_id: deviceId }, query: { period: "latest" } }))
      .then((res) => {
        if (!cancelled) setLatest(res.items?.[0] ?? null);
      })
      .catch((e) => toastError(e, tStatic("metrics.failedLatest")))
      .finally(() => !cancelled && setLoadingLatest(false));
    return () => {
      cancelled = true;
    };
  }, [deviceId]);

  /* ---- speed series (computed from cumulative totals) ---- */
  useEffect(() => {
    if (!throughputOpen || !hasTotals) return;
    let cancelled = false;
    setLoadingSpeeds(true);
    const period = RANGE_PERIOD[speedRange];
    const q = (metric: string) =>
      unwrap<MetricsQueryResult>(getDeviceMetrics({ path: { device_id: deviceId }, query: { period, metric } }));
    const writeRequest = hasWrite ? q("total_bytes_written") : Promise.resolve(null);
    const readRequest = hasRead ? q("total_bytes_read") : Promise.resolve(null);
    Promise.all([writeRequest, readRequest])
      .then(([write, read]) => {
        if (cancelled) return;
        setSpeeds({
          write: write ? toSpeedPoints(write.items ?? [], "total_bytes_written", speedRange) : [],
          read: read ? toSpeedPoints(read.items ?? [], "total_bytes_read", speedRange) : [],
        });
      })
      .catch((e) => toastError(e, tStatic("metrics.failedSpeed")))
      .finally(() => !cancelled && setLoadingSpeeds(false));
    return () => {
      cancelled = true;
    };
  }, [deviceId, speedRange, throughputOpen, hasTotals, hasWrite, hasRead]);

  /* ---- per-period I/O usage (computed from cumulative counters in the API) ---- */
  useEffect(() => {
    if (!hasTotals || (usageRange === "hour" && !hourlyUsageEnabled)) return;
    let cancelled = false;
    setLoadingUsage(true);
    unwrap<MetricsQueryResult>(
      getDeviceMetrics({
        path: { device_id: deviceId },
        query: { period: usageRange, metric: "io_usage" },
      }),
    )
      .then((res) => {
        if (cancelled) return;
        const items = res.items ?? [];
        setUsage({
          write: hasWrite ? toUsagePoints(items, "data_written", usageRange) : [],
          read: hasRead ? toUsagePoints(items, "data_read", usageRange) : [],
        });
      })
      .catch((e) => toastError(e, tStatic("metrics.failedUsage")))
      .finally(() => !cancelled && setLoadingUsage(false));
    return () => {
      cancelled = true;
    };
  }, [deviceId, usageRange, hourlyUsageEnabled, hasTotals, hasWrite, hasRead]);

  /* ---- single-metric history ---- */
  useEffect(() => {
    if (!historyMetric) return;
    let cancelled = false;
    setLoadingHistory(true);
    unwrap<MetricsQueryResult>(
      getDeviceMetrics({
        path: { device_id: deviceId },
        query: { period: RANGE_PERIOD[historyRange], metric: historyMetric },
      }),
    )
      .then((res) => {
        if (!cancelled) setHistory(toValuePoints(res.items ?? [], historyMetric, historyRange));
      })
      .catch((e) => toastError(e, tStatic("metrics.failedHistory")))
      .finally(() => !cancelled && setLoadingHistory(false));
    return () => {
      cancelled = true;
    };
  }, [deviceId, historyMetric, historyRange]);

  const visibleMetrics = useMemo(() => {
    if (!latest) return [];
    return METRIC_FIELDS.filter((f) => latest[f.name] !== null && latest[f.name] !== undefined);
  }, [latest]);

  const usageTabs = USAGE_RANGES.filter((range) => range !== "hour" || hourlyUsageEnabled).map((value) => ({
    value,
    label: t(USAGE_TAB_KEYS[value]),
  }));

  return (
    <div className="flex flex-col gap-5">
      {/* -------- per-period I/O usage -------- */}
      {!loadingLatest && hasTotals && (
        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-between gap-3">
            <p className="mono-label text-foreground/80 flex items-center gap-2">
              <span className="bg-primary size-1.5 rounded-full" /> {t("metrics.dataTitle")}
            </p>
            <RangeTabs
              value={usageRange}
              onChange={setUsageRange}
              ranges={usageTabs}
            />
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            {hasWrite && (
              <MetricChart
                title={t("metrics.dataWrittenPer", { unit: t(USAGE_UNIT_KEYS[usageRange]) })}
                data={usage?.write ?? []}
                loading={loadingUsage}
                color="var(--chart-1)"
                formatValue={formatBytes}
                formatAxis={(v) => formatBytes(v, 0)}
              />
            )}
            {hasRead && (
              <MetricChart
                title={t("metrics.dataReadPer", { unit: t(USAGE_UNIT_KEYS[usageRange]) })}
                data={usage?.read ?? []}
                loading={loadingUsage}
                color="var(--chart-2)"
                formatValue={formatBytes}
                formatAxis={(v) => formatBytes(v, 0)}
              />
            )}
          </div>
        </div>
      )}

      {/* -------- optional throughput -------- */}
      {!loadingLatest && hasTotals && (
        <div className="flex flex-col gap-3">
          <Button variant="outline" size="sm" className="self-start" onClick={() => setThroughputOpen((open) => !open)}>
            <ChartColumn className="size-3.5" />
            {throughputOpen ? t("metrics.hideThroughput") : t("metrics.showThroughput")}
          </Button>
          {throughputOpen && (
            <div className="flex flex-col gap-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="mono-label text-foreground/80 flex items-center gap-2">
                  <span className="bg-chart-2 size-1.5 rounded-full" /> {t("metrics.throughput")}
                </p>
                <RangeTabs value={speedRange} onChange={setSpeedRange} />
              </div>
              <div className="grid gap-4 lg:grid-cols-2">
                {hasWrite && (
                  <MetricChart
                    title={t("metrics.writeSpeed")}
                    data={speeds?.write ?? []}
                    loading={loadingSpeeds}
                    color="var(--chart-1)"
                    formatValue={formatSpeed}
                    formatAxis={(v) => `${formatBytes(v, 0)}/s`}
                  />
                )}
                {hasRead && (
                  <MetricChart
                    title={t("metrics.readSpeed")}
                    data={speeds?.read ?? []}
                    loading={loadingSpeeds}
                    color="var(--chart-2)"
                    formatValue={formatSpeed}
                    formatAxis={(v) => `${formatBytes(v, 0)}/s`}
                  />
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* -------- latest values -------- */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-baseline gap-2.5">
          <p className="mono-label text-foreground/80 flex items-center gap-2">
            <span className="status-dot text-success" /> {t("metrics.latest")}
          </p>
          {latest?.time && (
            <span className="text-muted-foreground/70 font-mono text-[10px]" title={fullLabelFor(sampleTime(latest))}>
              {formatDateTime(latest.time)}
            </span>
          )}
        </div>
      </div>

      {loadingLatest ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-[86px]" />
          ))}
        </div>
      ) : visibleMetrics.length === 0 ? (
        <div className="border-border/55 bg-card/25 text-muted-foreground rounded-2xl border border-dashed py-12 text-center text-[13px]">
          {t("metrics.noMetrics")}
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {visibleMetrics.map((f) => {
            const raw = toNum(latest?.[f.name]);
            const active = historyMetric === f.name;
            return (
              <div
                key={f.name}
                className={cn(
                  "group border-border/55 bg-card/40 relative overflow-hidden rounded-2xl border p-3.5 backdrop-blur-sm transition-[border-color,background-color,box-shadow] duration-300 hover:border-border hover:bg-card/65",
                  active && "border-primary/45 bg-primary/[0.04] ring-1 ring-primary/15",
                )}
                title={f.description}
              >
                <span className={cn("bg-border/80 absolute inset-y-3 left-0 w-[2px] rounded-full transition-colors", active && "bg-primary")} aria-hidden />
                <p className="text-muted-foreground truncate pl-1.5 text-[11px]">{f.label}</p>
                <p className="tnum mt-1.5 truncate pl-1.5 font-display text-[19px] leading-none font-semibold tracking-[-0.02em]">
                  {formatMetricValue(f.name, raw)}
                </p>
                {metricUnit(f.name) === "bytes" && raw != null && (
                  <p className="text-muted-foreground/60 mt-1 truncate pl-1.5 font-mono text-[9px]" title={t("metrics.siNote")}>
                    {formatSiMetricValue(f.name, raw)}
                  </p>
                )}
                {isChartable(f.name) && (
                  <button
                    type="button"
                    aria-label={t("metrics.showHistory", { name: f.label })}
                    className={cn(
                      "bg-secondary/80 text-muted-foreground hover:bg-primary hover:text-primary-foreground absolute top-2 right-2 cursor-pointer rounded-lg p-1.5 shadow-sm transition-[background-color,color,opacity] sm:opacity-0 sm:group-hover:opacity-100",
                      active && "bg-primary text-primary-foreground opacity-100 shadow-md",
                    )}
                    onClick={() => setHistoryMetric(active ? null : f.name)}
                  >
                    <ChartColumn className="size-3.5" />
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* -------- history chart -------- */}
      {historyMetric && (
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="mono-label text-foreground/80 flex items-center gap-2">
              <span className="bg-chart-3 size-1.5 rounded-full" />
              {t("metrics.history", { name: metricLabel(historyMetric) })}
              <Button variant="ghost" size="icon-sm" aria-label={t("metrics.closeHistory")} onClick={() => setHistoryMetric(null)}>
                <X className="size-3.5" />
              </Button>
            </p>
            <RangeTabs value={historyRange} onChange={setHistoryRange} />
          </div>
          <MetricChart
            title={metricLabel(historyMetric)}
            data={history}
            loading={loadingHistory}
            color="var(--chart-3)"
            formatValue={(v) => formatMetricValue(historyMetric, v)}
            formatAxis={(v) => formatAxisValue(historyMetric, v)}
          />
        </div>
      )}
    </div>
  );
}
