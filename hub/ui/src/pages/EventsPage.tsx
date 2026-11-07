import { useCallback, useState } from "react";
import { Activity, CheckCheck } from "lucide-react";
import { actEvent, listEvents, type EventResponse } from "@/client";
import { EmptyState } from "@/components/EmptyState";
import { EventItem } from "@/components/EventItem";
import { EventNoteDialog } from "@/components/EventNoteDialog";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { RefreshButton } from "@/components/RefreshButton";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { unwrap } from "@/lib/api";
import { toastError } from "@/lib/toast";
import { useLanguage } from "@/context/use-lang";
import { usePagedList } from "@/lib/use-paged-list";

export function EventsPage() {
  const { t } = useLanguage();
  const [page, setPage] = useState(1);
  const [limit, setLimit] = useState(20);
  const [noteEvent, setNoteEvent] = useState<EventResponse | null>(null);

  const fetchEvents = useCallback(
    () => listEvents({ query: { plimit: limit, pnum: page } }),
    [limit, page],
  );

  const { items, total, pages, loading, patchItem, reload } = usePagedList<EventResponse>(
    fetchEvents,
    t("events.failedLoad"),
  );

  const unread = items.filter((e) => !e.act_at).length;
  const [ackingAll, setAckingAll] = useState(false);

  const ackAll = async () => {
    const targets = items.filter((e) => !e.act_at);
    if (targets.length === 0) return;
    setAckingAll(true);
    try {
      await Promise.all(targets.map((e) => unwrap(actEvent({ path: { event_id: e.id } }))));
      const now = new Date().toISOString();
      targets.forEach((e) => patchItem({ ...e, act_at: now }));
    } catch (err) {
      toastError(err, t("events.failedAckAll"));
    } finally {
      setAckingAll(false);
      // Reload even after a partial failure so the list reflects whichever
      // events were acknowledged successfully.
      void reload(true);
    }
  };

  return (
    <>
      <PageHeader
        title={t("events.title")}
        description={
          loading
            ? t("common.loading")
            : `${t("events.count", { total })}${unread > 0 ? t("events.unread", { count: unread }) : ""}`
        }
      >
        <RefreshButton onRefresh={() => reload(true)} disabled={loading} label={t("events.refresh")} />
        {unread > 0 && (
          <Button variant="outline" size="sm" onClick={() => void ackAll()} disabled={ackingAll}>
            <CheckCheck className="size-4" />
            {ackingAll ? t("events.marking") : t("events.markRead")}
          </Button>
        )}
      </PageHeader>

      {loading ? (
        <div className="flex flex-col gap-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-20" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <EmptyState
          icon={Activity}
          title={t("events.emptyTitle")}
          description={t("events.emptyDesc")}
        />
      ) : (
        <div className="flex flex-col gap-3">
          {items.map((e) => (
            <EventItem
              key={e.id}
              event={e}
              onOpenNote={setNoteEvent}
              onAct={(id) => {
                const found = items.find((x) => x.id === id);
                if (found) patchItem({ ...found, act_at: new Date().toISOString() });
              }}
            />
          ))}
        </div>
      )}

      <div className="mt-6">
        <Pagination page={page} pages={pages} total={total} limit={limit} onPage={setPage} onLimit={(l) => { setLimit(l); setPage(1); }} />
      </div>

      <EventNoteDialog
        event={noteEvent}
        onOpenChange={(o) => !o && setNoteEvent(null)}
        showDevice
      />
    </>
  );
}
