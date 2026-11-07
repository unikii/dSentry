import { useEffect, useState } from "react";
import { getDeviceEvents, type EventResponse } from "@/client";
import { EventItem } from "@/components/EventItem";
import { EventNoteDialog } from "@/components/EventNoteDialog";
import { Skeleton } from "@/components/ui/skeleton";
import { unwrap } from "@/lib/api";
import { useLanguage } from "@/context/use-lang";
import { tStatic } from "@/i18n";
import { toastError } from "@/lib/toast";

export function DeviceEventsPanel({ deviceId }: { deviceId: number }) {
  const { t } = useLanguage();
  const [events, setEvents] = useState<EventResponse[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [noteEvent, setNoteEvent] = useState<EventResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    setEvents(null);
    setFailed(false);
    unwrap(getDeviceEvents({ path: { device_id: deviceId } }))
      .then((result) => {
        if (!cancelled) setEvents(result);
      })
      .catch((e) => {
        if (!cancelled) {
          setFailed(true);
          toastError(e, tStatic("deviceEvents.failed"));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [deviceId]);

  if (events === null) {
    if (failed) {
      return (
        <p className="border-border/55 bg-card/25 text-muted-foreground rounded-2xl border border-dashed py-10 text-center text-[13px]">
          {t("deviceEvents.failed")}
        </p>
      );
    }
    return (
      <div className="flex flex-col gap-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-20" />
        ))}
      </div>
    );
  }

  if (events.length === 0) {
    return (
      <p className="border-border/55 bg-card/25 text-muted-foreground rounded-2xl border border-dashed py-10 text-center text-[13px]">
        {t("deviceEvents.none")}
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {events.map((e) => (
        <EventItem
          key={e.id}
          event={e}
          showDevice={false}
          onOpenNote={setNoteEvent}
          onAct={(id) =>
            setEvents((prev) => prev?.map((x) => (x.id === id ? { ...x, act_at: new Date().toISOString() } : x)) ?? prev)
          }
        />
      ))}

      <EventNoteDialog event={noteEvent} onOpenChange={(o) => !o && setNoteEvent(null)} />
    </div>
  );
}
