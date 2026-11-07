import { useCallback, useEffect, useRef, useState } from "react";
import { unwrap, type SdkResult } from "@/lib/api";
import { toastError } from "@/lib/toast";

type WithId = { id: number };

/**
 * Shared paginated-list loader for the list pages. Lists load on mount and
 * whenever the fetcher identity changes (page, filters, sort); updates after
 * that are manual via the returned `reload` (pages render a refresh button).
 *
 * Every load is tagged with a request id: when filters or page change in
 * quick succession, the stale response is discarded instead of overwriting
 * the newer one (the classic race of hand-rolled list fetching).
 */
export function usePagedList<T extends WithId>(
  fetcher: () => SdkResult<{ payload?: { items: T[]; total: number; pages: number } | null }>,
  errorMessage: string,
) {
  const [items, setItems] = useState<T[]>([]);
  const [total, setTotal] = useState(0);
  const [pages, setPages] = useState(0);
  const [loading, setLoading] = useState(true);
  const requestRef = useRef(0);

  const load = useCallback(async (silent = false) => {
    const requestId = ++requestRef.current;
    if (!silent) setLoading(true);
    try {
      const payload = await unwrap(fetcher());
      if (requestId !== requestRef.current) return;
      setItems(payload.items);
      setTotal(payload.total);
      setPages(payload.pages);
    } catch (e) {
      if (requestId !== requestRef.current) return;
      toastError(e, errorMessage);
    } finally {
      if (!silent && requestId === requestRef.current) setLoading(false);
    }
  }, [fetcher, errorMessage]);

  useEffect(() => {
    void load();
  }, [load]);

  const patchItem = useCallback((updated: T) => {
    setItems((prev) => prev.map((x) => (x.id === updated.id ? updated : x)));
  }, []);

  const removeItem = useCallback((id: number) => {
    setItems((prev) => prev.filter((x) => x.id !== id));
    setTotal((t) => Math.max(0, t - 1));
  }, []);

  return { items, total, pages, loading, reload: load, patchItem, removeItem };
}
