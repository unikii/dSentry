import { useEffect, useMemo, useState } from "react";
import { Activity, AlertTriangle, ArrowLeft, Cpu, FileJson, Gauge, HardDrive, ListTree, Server, TerminalSquare } from "lucide-react";
import { updateDevice, type DeviceResponse } from "@/client";
import { SmartBadge } from "@/components/SmartBadge";
import { TagEditor } from "@/components/TagEditor";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { unwrap } from "@/lib/api";
import { useLanguage } from "@/context/use-lang";
import { saveDeviceTags } from "@/lib/device-tags";
import { deviceTypeMeta } from "@/lib/constants";
import { formatBytes, formatDateTime } from "@/lib/format";
import { toastError } from "@/lib/toast";
import { cn } from "@/lib/utils";
import { DeviceEventsPanel } from "./DeviceEventsPanel";
import { DeviceMetricsPanel } from "./DeviceMetricsPanel";
import { DeviceRawsPanel } from "./DeviceRawsPanel";
import { DriveGlyph } from "./DriveGlyph";

interface DeviceDetailViewProps {
  device: DeviceResponse;
  nodeName?: string;
  pushInterval?: number;
  onBack: () => void;
  onChanged: (device: DeviceResponse) => void;
}

function KV({ k, v, mono, title }: { k: string; v: React.ReactNode; mono?: boolean; title?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-border/40 py-2.5 last:border-b-0">
      <span className="mono-label text-muted-foreground/65 shrink-0">{k}</span>
      <span
        className={cn("min-w-0 truncate text-right text-[12px]", mono && "font-mono text-[11px]")}
        title={title ?? (typeof v === "string" ? v : undefined)}
      >
        {v ?? "—"}
      </span>
    </div>
  );
}

function InfoPill({ icon: Icon, label, value, title }: { icon: typeof HardDrive; label: string; value: string; title?: string }) {
  return (
    <span className="border-border/55 bg-card/40 inline-flex max-w-full items-center gap-2 rounded-full border py-1.5 pr-3 pl-2.5 backdrop-blur-sm">
      <Icon className="text-muted-foreground/70 size-3.5 shrink-0" strokeWidth={1.7} />
      <span className="mono-label text-muted-foreground/60 shrink-0">{label}</span>
      <span className="truncate font-mono text-[10px] font-medium" title={title}>
        {value}
      </span>
    </span>
  );
}

function extLabel(key: string): string {
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function extValue(key: string, value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number" && (key.includes("size") || key.includes("tbw"))) return formatBytes(value);
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function DeviceDetailView({ device, nodeName, pushInterval, onBack, onChanged }: DeviceDetailViewProps) {
  const { t } = useLanguage();
  const [tab, setTab] = useState("metrics");

  // Acknowledge the critical-event highlight when the user opens the device.
  useEffect(() => {
    if (!device.last_event_at) return;
    const id = device.id;
    unwrap(updateDevice({ path: { device_id: id }, body: { clear_last_event: true } }))
      .then(onChanged)
      .catch((e) => toastError(e, t("detail.failedAck")));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [device.id]);

  const meta = deviceTypeMeta(device.device_type);
  const extEntries = useMemo(
    () => Object.entries(device.device_ext ?? {}).filter(([, v]) => v !== null && v !== undefined),
    [device.device_ext],
  );

  const saveTags = async (tags: string[]) => {
    await saveDeviceTags(device.id, tags, onChanged, t("device.tagsFailed"));
  };

  return (
    <div className="flex flex-col gap-5 py-5 sm:py-6">
      <div>
        <Button variant="ghost" size="sm" className="text-muted-foreground -ml-2 mb-3" onClick={onBack}>
          <ArrowLeft className="size-4" />
          {t("nav.devices")}
        </Button>

        <section className="panel relative overflow-hidden p-5 sm:p-6">
          <div className="bg-grid-dense pointer-events-none absolute inset-0 opacity-25 [mask-image:radial-gradient(ellipse_75%_100%_at_0%_0%,black,transparent_70%)]" aria-hidden />
          <div className="pointer-events-none absolute -top-24 -left-16 size-64 rounded-full bg-primary/[0.08] blur-3xl" aria-hidden />
          <span className={cn("absolute inset-x-0 top-0 h-px bg-gradient-to-r", meta.bar)} aria-hidden />

          <div className="relative flex flex-wrap items-start gap-4">
            <span className={cn("flex size-14 shrink-0 items-center justify-center rounded-2xl border", meta.icon)}>
              <DriveGlyph className="size-7" />
            </span>

            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="font-display min-w-0 max-w-full text-[24px] leading-tight font-semibold tracking-[-0.035em] break-words sm:text-[28px]">
                  {device.model_name}
                </h1>
                <Badge variant="outline" className={meta.badge}>
                  {meta.label}
                </Badge>
                <SmartBadge device={device} showEvent={false} />
              </div>
              <p className="text-muted-foreground mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-[10px] tracking-[0.03em]">
                <span>SN {device.serial_number}</span>
                <span className="bg-border size-0.5 rounded-full" />
                <span>{device.vendor || device.vendor_guess || t("device.unknownVendor")}</span>
                {device.device_hash && (
                  <>
                    <span className="bg-border size-0.5 rounded-full" />
                    <span title={device.device_hash}>#{device.device_hash.slice(0, 8)}</span>
                  </>
                )}
              </p>

              <div className="mt-4 flex flex-wrap gap-2">
                <InfoPill icon={HardDrive} label={t("device.capacity")} value={formatBytes(device.total_capacity_bytes)} />
                {nodeName && <InfoPill icon={Server} label={t("device.node")} value={nodeName} />}
                <InfoPill icon={Cpu} label={t("device.firmware")} value={device.firmware_version || "—"} />
                <InfoPill icon={TerminalSquare} label={t("device.device")} value={device.device_name || "—"} title={device.device_name ?? undefined} />
              </div>
            </div>

          </div>
        </section>
      </div>

      {device.last_event_at && (
        <div className="border-destructive/25 bg-destructive/[0.06] text-destructive relative flex items-center gap-3 overflow-hidden rounded-xl border px-3.5 py-2.5 text-[12px]">
          <span className="bg-destructive/10 text-destructive flex size-7 shrink-0 items-center justify-center rounded-lg">
            <AlertTriangle className="size-4" />
          </span>
          <span className="relative">{t("detail.criticalBanner", { when: formatDateTime(device.last_event_at) })}</span>
        </div>
      )}

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="no-scrollbar w-full justify-start overflow-x-auto sm:w-fit">
          <TabsTrigger value="metrics">
            <Gauge className="size-3.5" /> {t("detail.tabMetrics")}
          </TabsTrigger>
          <TabsTrigger value="overview">
            <ListTree className="size-3.5" /> {t("detail.tabOverview")}
          </TabsTrigger>
          <TabsTrigger value="raws">
            <FileJson className="size-3.5" /> {t("detail.tabRaws")}
          </TabsTrigger>
          <TabsTrigger value="events">
            <Activity className="size-3.5" /> {t("detail.tabEvents")}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="metrics" className="mt-2">
          <DeviceMetricsPanel deviceId={device.id} pushInterval={pushInterval} />
        </TabsContent>

        <TabsContent value="overview" className="mt-2">
          <div className="panel p-5 sm:p-6">
            <p className="mono-label text-primary/80 mb-2">{t("detail.tabOverview")}</p>
            <div className="grid gap-x-10 sm:grid-cols-2">
              <KV k={t("detail.model")} v={device.model_name} />
              <KV k={t("detail.serial")} v={device.serial_number} mono />
              <KV k={t("detail.path")} v={device.device_name} mono />
              <KV k={t("detail.vendor")} v={device.vendor || device.vendor_guess} />
              <KV k={t("detail.vendorGuess")} v={device.vendor_guess} />
              <KV k={t("detail.firmware")} v={device.firmware_version} mono />
              <KV k={t("detail.capacity")} v={formatBytes(device.total_capacity_bytes)} />
              <KV k={t("detail.deviceType")} v={meta.label} />
              <KV k={t("detail.protocol")} v={device.using_protocol} />
              <KV k={t("detail.smartAvailable")} v={device.smart_available === null ? "—" : device.smart_available ? t("common.yes") : t("common.no")} />
              <KV k={t("detail.smartEnabled")} v={device.smart_enabled === null ? "—" : device.smart_enabled ? t("common.yes") : t("common.no")} />
              <KV k={t("detail.registered")} v={formatDateTime(device.reg_at)} />
              <KV k={t("detail.deviceHash")} v={`${device.device_hash.slice(0, 16)}…`} mono title={device.device_hash} />
            </div>

            {extEntries.length > 0 && (
              <div className="mt-6 border-t border-border/50 pt-5">
                <p className="mono-label text-muted-foreground/70 mb-2">{t("detail.extDetails", { label: meta.label })}</p>
                <div className="grid gap-x-10 sm:grid-cols-2">
                  {extEntries.map(([k, v]) => (
                    <KV key={k} k={extLabel(k)} v={extValue(k, v)} mono={typeof v === "string" && v.length > 20} />
                  ))}
                </div>
              </div>
            )}

            <div className="mt-6 border-t border-border/50 pt-5">
              <p className="mono-label text-muted-foreground/70 mb-3">{t("detail.tags")}</p>
              <TagEditor tags={device.tags ?? []} onSave={saveTags} />
            </div>
          </div>
        </TabsContent>

        <TabsContent value="raws" className="mt-2">
          <div className="panel p-4 sm:p-5">
            <DeviceRawsPanel deviceId={device.id} />
          </div>
        </TabsContent>

        <TabsContent value="events" className="mt-2">
          <DeviceEventsPanel deviceId={device.id} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
