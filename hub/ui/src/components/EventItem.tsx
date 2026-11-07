import { ShieldAlert, ShieldCheck, Siren, TriangleAlert, Wifi, WifiOff, type LucideIcon } from "lucide-react";
import { actEvent, type EventResponse } from "@/client";
import { Badge } from "@/components/ui/badge";
import { unwrap } from "@/lib/api";
import { toastError } from "@/lib/toast";
import { eventTypeLabel, eventTypeMeta } from "@/lib/constants";
import { useLanguage } from "@/context/use-lang";
import { formatDateTime, formatRelative } from "@/lib/format";
import { cn } from "@/lib/utils";

interface EventItemProps {
  event: EventResponse;
  onAct?: (id: number) => void;
  onOpenNote?: (event: EventResponse) => void;
  showDevice?: boolean;
}

const NOTE_PREVIEW_LEN = 160;

const EVENT_ICONS: Record<string, LucideIcon> = {
  device_smart_fail: ShieldAlert,
  device_smart_success: ShieldCheck,
  device_threshold_warning: TriangleAlert,
  device_threshold_critical: Siren,
  device_missing: WifiOff,
  device_online: Wifi,
};

const EVENT_TONES: Record<string, string> = {
  device_smart_fail: "border-destructive/25 bg-destructive/10 text-destructive",
  device_smart_success: "border-success/25 bg-success/10 text-success",
  device_threshold_warning: "border-warning/25 bg-warning/10 text-warning",
  device_threshold_critical: "border-destructive/25 bg-destructive/10 text-destructive",
  device_missing: "border-warning/25 bg-warning/10 text-warning",
  device_online: "border-success/25 bg-success/10 text-success",
};

export function EventItem({ event, onAct, onOpenNote, showDevice = true }: EventItemProps) {
  const { t } = useLanguage();
  const meta = eventTypeMeta(event.event_type);
  const unread = !event.act_at;
  const note = event.note ?? "";
  const longNote = note.length > NOTE_PREVIEW_LEN;
  const Icon = EVENT_ICONS[event.event_type] ?? TriangleAlert;
  const tone = EVENT_TONES[event.event_type] ?? "border-border/70 bg-secondary/60 text-muted-foreground";

  const handleClick = () => {
    if (unread) {
      unwrap(actEvent({ path: { event_id: event.id } }))
        .then(() => onAct?.(event.id))
        .catch((e) => toastError(e, t("event.failedAct")));
    }
    if (longNote && onOpenNote) onOpenNote(event);
  };

  return (
    <div className="relative pl-12 sm:pl-14">
      <span className="absolute top-2 bottom-0 left-[21px] w-px bg-gradient-to-b from-border/70 via-border/30 to-transparent" aria-hidden />
      <span className={cn("absolute top-4 left-0 flex size-10 items-center justify-center rounded-xl border", tone)}>
        <Icon className="size-[18px]" strokeWidth={1.7} />
        {unread && <span className="bg-primary absolute -top-0.5 -right-0.5 size-2 rounded-full ring-2 ring-card" />}
      </span>

      <button
        type="button"
        onClick={handleClick}
        className={cn(
          "group w-full cursor-pointer rounded-2xl border p-4 text-left backdrop-blur-xl transition-[border-color,background-color,box-shadow,transform] duration-300 hover:-translate-y-px",
          unread
            ? "border-primary/20 bg-card/65 shadow-[inset_0_1px_0_0_oklch(1_0_0/0.05)] hover:border-primary/35 hover:bg-card/85"
            : "border-border/55 bg-card/35 hover:border-border/80 hover:bg-card/55",
        )}
      >
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline" className={meta.className}>
            {eventTypeLabel(event.event_type, t)}
          </Badge>
          {showDevice && event.device_name && (
            <span className="max-w-full truncate text-[13px] font-medium">{event.device_name}</span>
          )}
          {unread && (
            <span className="border-primary/25 bg-primary/10 text-primary ml-0.5 rounded-full border px-1.5 py-0.5 font-mono text-[9px] tracking-[0.1em] uppercase">
              {t("events.new")}
            </span>
          )}
          <span className="text-muted-foreground/80 ml-auto shrink-0 font-mono text-[10px] tracking-[0.06em]" title={formatDateTime(event.add_at)}>
            {formatRelative(event.add_at)}
          </span>
        </div>

        {note && (
          <p className={cn("text-muted-foreground mt-2.5 text-[13px] leading-relaxed break-words", !longNote && "whitespace-pre-wrap")}>
            {longNote ? `${note.slice(0, NOTE_PREVIEW_LEN)}…` : note}
            {longNote && <span className="text-primary ml-1 text-xs font-medium">{t("event.viewFull")}</span>}
          </p>
        )}

        <div className="text-muted-foreground/70 mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[10px] tracking-[0.04em]">
          <span>{formatDateTime(event.add_at)}</span>
          {event.alert_at && <span>· {t("event.alerted", { when: formatRelative(event.alert_at) })}</span>}
          {event.act_at && <span>· {t("event.read", { when: formatRelative(event.act_at) })}</span>}
        </div>
      </button>
    </div>
  );
}
