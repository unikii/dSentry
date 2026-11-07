import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { FileJson, FileText, Loader2 } from "lucide-react";
import { getDeviceRaw, getDeviceRaws, type RawDetail, type RawListItem } from "@/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { unwrap } from "@/lib/api";
import { useLanguage } from "@/context/use-lang";
import { tStatic } from "@/i18n";
import { formatDateTime } from "@/lib/format";
import { toastError } from "@/lib/toast";
import { JsonViewer } from "@/components/JsonViewer";
import { cn } from "@/lib/utils";



interface ParsedRaw {
  json: unknown;
  plain?: string | null;
}

function parseRawOutput(raw: string): ParsedRaw | null {
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return null;
  }

  if (!value || typeof value !== "object") return null;
  const object = value as Record<string, unknown>;
  if (!("json" in object)) return { json: object, plain: null };

  let json = object.json;
  if (typeof json === "string") {
    try {
      json = JSON.parse(json);
    } catch {
      /* keep the raw string */
    }
  }
  return {
    json,
    plain: typeof object.plain === "string" ? object.plain : null,
  };
}

export function DeviceRawsPanel({ deviceId }: { deviceId: number }) {
  const { t } = useLanguage();
  const [items, setItems] = useState<RawListItem[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);
  const [detail, setDetail] = useState<RawDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const listRequest = useRef(0);

  const loadList = useCallback((s?: string, e?: string) => {
    const requestId = ++listRequest.current;
    setItems(null);
    setFailed(false);
    setSelected(null);
    setDetail(null);
    unwrap(
      getDeviceRaws({
        path: { device_id: deviceId },
        query: s && e ? { start: s, end: e } : {},
      }),
    )
      .then((result) => {
        if (listRequest.current === requestId) setItems(result);
      })
      .catch((err) => {
        if (listRequest.current === requestId) {
          setFailed(true);
          toastError(err, tStatic("raws.failedList"));
        }
      });
  }, [deviceId]);

  useEffect(() => {
    // loadList bumps the request id, so an in-flight request from a previous
    // device becomes stale as soon as the effect reruns.
    void loadList();
  }, [loadList]);

  useEffect(() => {
    if (selected === null) return;
    // Tagged like every other fetch here: clicking two raw items quickly
    // must show whichever the user selected last, not whichever responded last.
    let cancelled = false;
    setLoadingDetail(true);
    setDetail(null);
    unwrap(getDeviceRaw({ path: { device_id: deviceId, raw_id: selected } }))
      .then((res) => {
        if (!cancelled) setDetail(res);
      })
      .catch((e) => {
        if (!cancelled) toastError(e, tStatic("raws.failedDetail"));
      })
      .finally(() => {
        if (!cancelled) setLoadingDetail(false);
      });
    return () => {
      cancelled = true;
    };
  }, [deviceId, selected]);

  const rawOutput = detail?.raw_output;
  const rawAsJson = useMemo(() => (rawOutput ? parseRawOutput(rawOutput) : null), [rawOutput]);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end gap-2">
        <div className="grid gap-1">
          <span className="text-muted-foreground text-xs">{t("common.from")}</span>
          <Input type="date" value={start} onChange={(e) => setStart(e.target.value)} className="w-36" />
        </div>
        <div className="grid gap-1">
          <span className="text-muted-foreground text-xs">{t("common.to")}</span>
          <Input type="date" value={end} onChange={(e) => setEnd(e.target.value)} className="w-36" />
        </div>
        <Button variant="outline" size="sm" disabled={!start || !end} onClick={() => loadList(start, end)}>
          {t("common.apply")}
        </Button>
        {(start || end) && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setStart("");
              setEnd("");
              loadList();
            }}
          >
            {t("common.reset")}
          </Button>
        )}
      </div>

      {items === null ? (
        failed ? (
          <p className="border-border/55 bg-card/25 text-muted-foreground rounded-2xl border border-dashed py-10 text-center text-[13px]">
            {t("raws.failedList")}
          </p>
        ) : (
          <div className="flex flex-col gap-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-10" />
            ))}
          </div>
        )
      ) : items.length === 0 ? (
        <p className="border-border/55 bg-card/25 text-muted-foreground rounded-2xl border border-dashed py-10 text-center text-[13px]">
          {t("raws.noRaws")}
        </p>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[220px_1fr]">
          {/* timestamp list */}
          <div className="scrollbar-thin flex max-h-112 flex-col gap-1 overflow-y-auto pr-1">
            {items.map((r) => (
              <button
                key={r.id}
                type="button"
                onClick={() => setSelected(r.id)}
                className={cn(
                  "text-muted-foreground hover:bg-accent hover:text-accent-foreground cursor-pointer rounded-lg px-3 py-2 text-left text-xs transition-colors",
                  selected === r.id && "bg-accent text-accent-foreground font-medium",
                )}
              >
                {formatDateTime(r.add_at)}
              </button>
            ))}
          </div>

          {/* content */}
          <div className="min-w-0">
            {selected === null ? (
              <div className="border-border/55 bg-card/25 text-muted-foreground flex h-full min-h-40 items-center justify-center rounded-2xl border border-dashed text-[13px]">
                {t("raws.selectTs")}
              </div>
            ) : loadingDetail ? (
              <div className="flex h-40 items-center justify-center">
                <Loader2 className="text-muted-foreground size-6 animate-spin" />
              </div>
            ) : detail ? (
              rawAsJson ? (
                <Tabs defaultValue="json">
                  <TabsList>
                    <TabsTrigger value="json">
                      <FileJson className="size-4" /> JSON
                    </TabsTrigger>
                    {rawAsJson.plain ? (
                      <TabsTrigger value="plain">
                        <FileText className="size-4" /> {t("raws.plainText")}
                      </TabsTrigger>
                    ) : null}
                  </TabsList>
                  <TabsContent value="json">
                    <JsonViewer data={rawAsJson.json} />
                  </TabsContent>
                  {rawAsJson.plain ? (
                    <TabsContent value="plain">
                      <pre className="scrollbar-thin bg-secondary/35 mt-2 max-h-96 overflow-auto rounded-xl border border-border/55 p-4 text-xs leading-relaxed whitespace-pre-wrap">
                        {rawAsJson.plain}
                      </pre>
                    </TabsContent>
                  ) : null}
                </Tabs>
              ) : (
                <pre className="scrollbar-thin bg-secondary/35 max-h-96 overflow-auto rounded-xl border border-border/55 p-4 text-xs leading-relaxed whitespace-pre-wrap">
                  {detail.raw_output}
                </pre>
              )
            ) : null}
          </div>
        </div>
      )}
    </div>
  );
}
