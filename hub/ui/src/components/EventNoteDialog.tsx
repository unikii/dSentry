import type { EventResponse } from "@/client";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useLanguage } from "@/context/use-lang";
import { eventTypeLabel } from "@/lib/constants";
import { formatDateTime } from "@/lib/format";

interface EventNoteDialogProps {
  event: EventResponse | null;
  onOpenChange: (open: boolean) => void;
  showDevice?: boolean;
}

/** Shared event-note dialog used by the events list and the device detail page. */
export function EventNoteDialog({ event, onOpenChange, showDevice = false }: EventNoteDialogProps) {
  const { t } = useLanguage();

  return (
    <Dialog open={!!event} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[80vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{event ? eventTypeLabel(event.event_type, t) : t("deviceEvents.eventFallback")}</DialogTitle>
          <DialogDescription>
            {event ? (
              <>
                {showDevice && event.device_name ? `${event.device_name} · ` : ""}
                {formatDateTime(event.add_at)}
              </>
            ) : null}
          </DialogDescription>
        </DialogHeader>
        <p className="text-sm break-words whitespace-pre-wrap">{event?.note}</p>
      </DialogContent>
    </Dialog>
  );
}
