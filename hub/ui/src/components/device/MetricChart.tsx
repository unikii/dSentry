import { useMemo } from "react";
import { Download } from "lucide-react";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useLanguage } from "@/context/use-lang";
import { Skeleton } from "@/components/ui/skeleton";

export interface ChartPoint {
  /** x label */
  label: string;
  /** full description used in tooltip */
  fullLabel: string;
  value: number;
}

interface MetricChartProps {
  title: string;
  data: ChartPoint[];
  loading?: boolean;
  color?: string;
  formatValue: (v: number) => string;
  formatAxis?: (v: number) => string;
  emptyText?: string;
}

function ChartTooltip({ active, payload, formatValue }: { active?: boolean; payload?: { payload: ChartPoint }[]; formatValue: (v: number) => string }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="border-border/70 bg-popover/95 text-popover-foreground rounded-xl border px-3 py-2 text-xs shadow-xl backdrop-blur-md">
      <p className="text-muted-foreground">{p.fullLabel}</p>
      <p className="mt-0.5 text-sm font-semibold">{formatValue(p.value)}</p>
    </div>
  );
}

export function MetricChart({
  title,
  data,
  loading,
  color = "var(--chart-1)",
  formatValue,
  formatAxis,
  emptyText,
}: MetricChartProps) {
  const gradientId = useMemo(
    () => `area-fill-${title.replace(/[^a-zA-Z0-9]/g, "-").toLowerCase()}`,
    [title],
  );

  const { t } = useLanguage();

  const exportCsv = () => {
    const rows = ["label,full_label,value", ...data.map((p) => `${JSON.stringify(p.label)},${JSON.stringify(p.fullLabel)},${p.value}`)];
    const blob = new Blob([rows.join("\n")], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${title.replace(/[^a-zA-Z0-9]+/g, "-").toLowerCase()}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="border-border/55 bg-card/40 tnum rounded-2xl border p-4 backdrop-blur-sm">
      <div className="mb-3 flex items-center justify-between gap-2">
        <p className="mono-label text-muted-foreground">
          <span className="bg-primary mr-2 inline-block size-1.5 rounded-full align-middle" />
          {title}
        </p>
        {data.length > 0 && !loading && (
          <button
            type="button"
            onClick={exportCsv}
            className="text-muted-foreground hover:text-foreground flex cursor-pointer items-center gap-1 text-xs"
            aria-label={t("metrics.exportCsv", { title })}
            title={t("metrics.exportCsv", { title })}
          >
            <Download className="size-3.5" />
            {t("metrics.csv")}
          </button>
        )}
      </div>
      {loading ? (
        <Skeleton className="h-44 w-full" />
      ) : data.length === 0 ? (
        <div className="text-muted-foreground/80 flex h-44 items-center justify-center text-[12px]">{emptyText ?? t("metrics.noData")}</div>
      ) : (
        <ResponsiveContainer width="100%" height={176}>
          <AreaChart data={data} margin={{ top: 4, right: 4, left: -8, bottom: 0 }}>
            <defs>
              <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={color} stopOpacity={0.35} />
                <stop offset="100%" stopColor={color} stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 5" vertical={false} stroke="var(--border)" strokeOpacity={0.55} />
            <XAxis
              dataKey="label"
              tickLine={false}
              axisLine={false}
              minTickGap={28}
              tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
            />
            <YAxis
              width={52}
              domain={["auto", "auto"]}
              tickLine={false}
              axisLine={false}
              tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
              tickFormatter={(v: number) => (formatAxis ? formatAxis(v) : formatValue(v))}
            />
            <Tooltip cursor={{ stroke: "var(--border)", strokeDasharray: "3 3" }} content={<ChartTooltip formatValue={formatValue} />} />
            <Area
              type="monotone"
              dataKey="value"
              stroke={color}
              strokeWidth={2}
              fill={`url(#${gradientId})`}
              fillOpacity={1}
              dot={false}
              activeDot={{ r: 4, fill: "var(--background)", stroke: color, strokeWidth: 2 }}
              animationDuration={400}
            />
          </AreaChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
