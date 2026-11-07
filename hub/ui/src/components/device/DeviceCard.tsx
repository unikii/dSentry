import { Archive, ArchiveRestore, CalendarDays, Server } from "lucide-react";
import { archiveDevice, unarchiveDevice, type DeviceResponse } from "@/client";
import { SmartBadge } from "@/components/SmartBadge";
import { TagEditor } from "@/components/TagEditor";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useLanguage } from "@/context/use-lang";
import { unwrap } from "@/lib/api";
import { saveDeviceTags } from "@/lib/device-tags";
import { deviceTypeMeta } from "@/lib/constants";
import { formatBytes, formatDate } from "@/lib/format";
import { toastError } from "@/lib/toast";
import { cn } from "@/lib/utils";
import { DriveGlyph } from "./DriveGlyph";

interface DeviceCardProps {
  device: DeviceResponse;
  nodeName?: string;
  onOpen: (device: DeviceResponse) => void;
  onChanged: (device: DeviceResponse) => void;
  onArchived: (id: number) => void;
}

function DataField({
  label,
  value,
  mono,
  title,
  icon,
}: {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
  title?: string;
  icon?: React.ReactNode;
}) {
  return (
    <div className="min-w-0">
      <p className="mono-label text-muted-foreground/65 mb-1 flex items-center gap-1">
        {icon}
        {label}
      </p>
      <p className={cn("truncate text-[12px] leading-snug", mono && "font-mono text-[11px]")} title={title}>
        {value}
      </p>
    </div>
  );
}

export function DeviceCard({ device, nodeName, onOpen, onChanged, onArchived }: DeviceCardProps) {
  const { t } = useLanguage();
  const meta = deviceTypeMeta(device.device_type);
  const hasEvent = !!device.last_event_at;

  const saveTags = async (tags: string[]) => {
    await saveDeviceTags(device.id, tags, onChanged, t("device.tagsFailed"));
  };

  const toggleArchive = async () => {
    try {
      if (device.archived) {
        await unwrap(unarchiveDevice({ path: { device_id: device.id } }));
      } else {
        await unwrap(archiveDevice({ path: { device_id: device.id } }));
      }
      onArchived(device.id);
    } catch (e) {
      toastError(e, t("device.archiveFailed"));
    }
  };

  return (
    <article
      role="button"
      tabIndex={0}
      onClick={() => onOpen(device)}
      onKeyDown={(e) => {
        if (e.key !== "Enter") return;
        const el = e.target as HTMLElement | null;
        if (el && el !== e.currentTarget && el.closest?.("input, textarea, select, button, a")) return;
        onOpen(device);
      }}
      className={cn(
        "panel panel-hover group relative flex cursor-pointer flex-col overflow-hidden",
        hasEvent && "border-destructive/35",
        device.archived && "opacity-60",
      )}
    >
      <span className={cn("absolute inset-x-0 top-0 h-px bg-gradient-to-r", meta.bar)} aria-hidden />
      <div className="pointer-events-none absolute -top-20 -right-20 size-44 rounded-full bg-primary/[0.045] blur-3xl" aria-hidden />

      <div className="relative flex flex-1 flex-col gap-4 p-5">
        <div className="flex items-start gap-3">
          <span className={cn("relative flex size-11 shrink-0 items-center justify-center rounded-xl border", meta.icon)}>
            <DriveGlyph className="size-6" />
            {hasEvent && (
              <span className="bg-destructive absolute -top-0.5 -right-0.5 flex size-2.5 items-center justify-center rounded-full ring-2 ring-card">
                <span className="bg-destructive/70 radar-ping absolute inset-0 rounded-full" />
              </span>
            )}
          </span>

          <div className="min-w-0 flex-1 pt-0.5">
            <p className="font-display truncate text-[15px] leading-snug font-semibold tracking-[-0.015em]" title={device.model_name}>
              {device.model_name}
            </p>
            <div className="text-muted-foreground mt-1 flex min-w-0 items-center gap-1.5 text-[11px]">
              <span className="truncate">{device.vendor_guess || device.vendor || t("device.unknownVendor")}</span>
              <span className="bg-border size-0.5 shrink-0 rounded-full" />
              <span className="shrink-0 font-mono text-[10px] tracking-[0.12em] uppercase">{meta.label}</span>
            </div>
          </div>

          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={device.archived ? t("device.unarchive") : t("device.archive")}
                className="text-muted-foreground/60 hover:text-foreground -mt-1 -mr-1 opacity-100 transition-opacity sm:opacity-0 sm:group-hover:opacity-100"
                onClick={(e) => {
                  e.stopPropagation();
                  void toggleArchive();
                }}
              >
                {device.archived ? <ArchiveRestore className="size-4" /> : <Archive className="size-4" />}
              </Button>
            </TooltipTrigger>
            <TooltipContent>{device.archived ? t("device.unarchive") : t("device.archive")}</TooltipContent>
          </Tooltip>
        </div>

        <div className="grid grid-cols-2 gap-x-4 gap-y-3.5">
          <DataField label={t("device.capacity")} value={formatBytes(device.total_capacity_bytes)} />
          <DataField label={t("device.firmware")} value={device.firmware_version || "—"} mono />
          <DataField label={t("device.serial")} value={device.serial_number} mono title={device.serial_number} />
          <DataField
            label={t("device.node")}
            value={nodeName || "—"}
            title={nodeName}
            icon={<Server className="size-2.5" />}
          />
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border/50 pt-3">
          <SmartBadge device={device} />
          <span className="text-muted-foreground/75 flex items-center gap-1 font-mono text-[9px] tracking-[0.1em] uppercase">
            <CalendarDays className="size-3" />
            {formatDate(device.reg_at)}
          </span>
        </div>

        <TagEditor
          tags={device.tags ?? []}
          onSave={saveTags}
          compact
          className="opacity-100 transition-opacity sm:opacity-45 sm:group-hover:opacity-100"
        />
      </div>
    </article>
  );
}
