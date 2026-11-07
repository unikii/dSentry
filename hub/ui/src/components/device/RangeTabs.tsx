import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useLanguage } from "@/context/use-lang";
import type { MessageKey } from "@/context/lang-context";
import type { ChartRange } from "@/lib/metrics";

const DEFAULT_RANGES: { value: ChartRange; labelKey: MessageKey }[] = [
  { value: "day", labelKey: "ranges.day" },
  { value: "week", labelKey: "ranges.week" },
  { value: "month", labelKey: "ranges.month" },
  { value: "year", labelKey: "ranges.year" },
];

export function RangeTabs<T extends string>({
  value,
  onChange,
  ranges,
}: {
  value: T;
  onChange: (r: T) => void;
  ranges?: { value: T; label: string }[];
}) {
  const { t } = useLanguage();
  const items = ranges ?? DEFAULT_RANGES.map((r) => ({ value: r.value as unknown as T, label: t(r.labelKey) }));

  return (
    <Tabs value={value} onValueChange={(v) => onChange(v as T)}>
      <TabsList className="h-8">
        {items.map((r) => (
          <TabsTrigger key={r.value} value={r.value} className="px-2.5 text-xs">
            {r.label}
          </TabsTrigger>
        ))}
      </TabsList>
    </Tabs>
  );
}
