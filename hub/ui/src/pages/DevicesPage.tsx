import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, Outlet, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { CircleAlert, HardDrive, Plus, Search, Server, ShieldCheck } from "lucide-react";
import { listDevices, listNodes, type DeviceResponse } from "@/client";
import { EmptyState } from "@/components/EmptyState";
import { HealthRing } from "@/components/HealthRing";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { RefreshButton } from "@/components/RefreshButton";
import { StatCard } from "@/components/StatCard";
import { DeviceCard } from "@/components/device/DeviceCard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useEnvs } from "@/context/use-envs";
import { useNow } from "@/lib/use-now";
import { unwrap } from "@/lib/api";
import { toastError } from "@/lib/toast";
import { useLanguage } from "@/context/use-lang";
import { tStatic } from "@/i18n";
import { DEVICE_TYPE_META, PAGE_SIZE_OPTIONS, smartState } from "@/lib/constants";
import { parseUTC } from "@/lib/format";
import { usePagedList } from "@/lib/use-paged-list";
import { cn } from "@/lib/utils";

type ArchivedFilter = "active" | "archived";
type SortKey = "newest" | "oldest" | "capacity_desc" | "capacity_asc";

const SORT_MAP: Record<SortKey, { sort_by: "reg_at" | "capacity"; sort_order: "asc" | "desc" }> = {
  newest: { sort_by: "reg_at", sort_order: "desc" },
  oldest: { sort_by: "reg_at", sort_order: "asc" },
  capacity_desc: { sort_by: "capacity", sort_order: "desc" },
  capacity_asc: { sort_by: "capacity", sort_order: "asc" },
};

function parsePositiveInt(value: string | null, fallback: number): number {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}

export function DevicesPage() {
  const { t } = useLanguage();
  const { envs } = useEnvs();
  const now = useNow();
  const [searchParams, setSearchParams] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const { deviceId } = useParams();

  const initialPage = parsePositiveInt(searchParams.get("page"), 1);
  const parsedLimit = Number(searchParams.get("limit"));
  const initialLimit = PAGE_SIZE_OPTIONS.includes(parsedLimit) ? parsedLimit : 20;
  const initialSortParam = searchParams.get("sort");
  const initialSort = initialSortParam && Object.hasOwn(SORT_MAP, initialSortParam) ? (initialSortParam as SortKey) : "newest";

  const [page, setPage] = useState(initialPage);
  const [limit, setLimit] = useState(initialLimit);
  const [searchInput, setSearchInput] = useState(searchParams.get("q") ?? "");
  const [keyword, setKeyword] = useState(searchParams.get("q") ?? "");
  const [nodeFilter, setNodeFilter] = useState(searchParams.get("node") ?? "all");
  const [typeFilter, setTypeFilter] = useState(searchParams.get("type") ?? "all");
  const [archivedFilter, setArchivedFilter] = useState<ArchivedFilter>(searchParams.get("archived") === "1" ? "archived" : "active");
  const [sort, setSort] = useState<SortKey>(initialSort);

  const [nodes, setNodes] = useState<{ id: number; hostname: string; deviceIds: number[]; lastMetricsPush: string | null }[]>([]);

  /* Explicit search: button click or Enter commits the draft, so typing
     never fires requests by itself. */
  const commitSearch = () => {
    setKeyword(searchInput.trim());
    setPage(1);
  };

  /* Keep list state in the URL so a detail page can return to this exact view. */
  useEffect(() => {
    const next = new URLSearchParams();
    if (page > 1) next.set("page", String(page));
    if (limit !== 20) next.set("limit", String(limit));
    if (keyword) next.set("q", keyword);
    if (nodeFilter !== "all") next.set("node", nodeFilter);
    if (typeFilter !== "all") next.set("type", typeFilter);
    if (archivedFilter === "archived") next.set("archived", "1");
    if (sort !== "newest") next.set("sort", sort);
    setSearchParams(next, { replace: true });
  }, [page, limit, keyword, nodeFilter, typeFilter, archivedFilter, sort, setSearchParams]);

  /* nodes for the filter + device->node map */
  useEffect(() => {
    unwrap(listNodes({ query: { plimit: 200, pnum: 1 } }))
      .then((res) =>
        setNodes(
          res.items.map((n) => ({
            id: n.id,
            hostname: n.hostname || `Node #${n.id}`,
            deviceIds: n.last_device_push ?? [],
            lastMetricsPush: n.last_metrics_push,
          })),
        ),
      )
      .catch((e) => toastError(e, tStatic("devices.failedNodesFilter")));
  }, []);

  const deviceNodeInfo = useMemo(() => {
    const m = new Map<number, { hostname: string; id: number }>();
    for (const n of nodes) for (const id of n.deviceIds) m.set(id, { hostname: n.hostname, id: n.id });
    return m;
  }, [nodes]);

  const fetchDevices = useCallback(() => {
    const { sort_by, sort_order } = SORT_MAP[sort];
    const parsedNodeId = Number(nodeFilter);
    return listDevices({
      query: {
        plimit: limit,
        pnum: page,
        keyword: keyword || undefined,
        node_id:
          nodeFilter === "all" || !Number.isInteger(parsedNodeId)
            ? undefined
            : parsedNodeId,
        device_type: typeFilter === "all" ? undefined : typeFilter,
        archived: archivedFilter === "archived",
        sort_by,
        sort_order,
      },
    });
  }, [limit, page, keyword, nodeFilter, typeFilter, archivedFilter, sort]);

  const { items, total, pages, loading, reload, patchItem, removeItem } = usePagedList<DeviceResponse>(
    fetchDevices,
    t("devices.failedLoad"),
  );

  const hasFilters = keyword !== "" || nodeFilter !== "all" || typeFilter !== "all" || archivedFilter === "archived";

  const health = useMemo(() => {
    let passed = 0;
    let warning = 0;
    let critical = 0;
    let unknown = 0;
    for (const d of items) {
      if (d.smart_status === 1 || d.threshold_status === 2) critical++;
      else if (d.threshold_status === 1) warning++;
      else if (smartState(d) === "passed") passed++;
      else unknown++;
    }
    return { passed, warning, critical, unknown };
  }, [items]);

  const intervalMs = ((envs?.global_push_interval ?? 5) + 5) * 60_000;
  const nodesOnline = nodes.filter((n) => {
    const last = parseUTC(n.lastMetricsPush);
    return !!last && now - last.getTime() <= intervalMs;
  }).length;

  const passRate = items.length > 0 ? Math.round((health.passed / items.length) * 100) : 0;
  const attention = health.warning + health.critical;
  const ringTone = health.critical > 0 ? "danger" : health.warning > 0 ? "warning" : "success";

  return (
    <>
      <div className={deviceId ? "hidden" : undefined}>
        <PageHeader
          title={t("devices.title")}
          description={loading ? t("common.loading") : t("devices.monitored", { count: total })}
        >
          <RefreshButton onRefresh={() => reload(true)} disabled={loading} label={t("devices.refresh")} />
        </PageHeader>

        {loading ? (
          <Skeleton className="mb-5 h-[108px] w-full" />
        ) : (
          <div className="panel mb-5 grid grid-cols-2 gap-px overflow-hidden bg-border/25 sm:grid-cols-4">
            <StatCard
              icon={HardDrive}
              label={t("nav.devices")}
              value={total}
              hint={t("devices.inView", { shown: items.length, total })}
              tone="primary"
              className="bg-card/70 backdrop-blur-xl"
            />
            <StatCard
              icon={ShieldCheck}
              label={t("devices.statHealth")}
              value={`${passRate}%`}
              hint={`${health.passed} ${t("smart.passed")}`}
              tone={health.critical > 0 ? "danger" : health.warning > 0 ? "warning" : "success"}
              visual={<HealthRing value={passRate} size={50} tone={ringTone} />}
              className="bg-card/70 backdrop-blur-xl"
            />
            <StatCard
              icon={CircleAlert}
              label={t("devices.statAttention")}
              value={attention}
              hint={`${health.warning} ${t("smart.warning")} · ${health.critical} ${t("smart.critical")}`}
              tone={health.critical > 0 ? "danger" : health.warning > 0 ? "warning" : "success"}
              className="bg-card/70 backdrop-blur-xl"
            />
            <StatCard
              icon={Server}
              label={t("devices.statNodesOnline")}
              value={`${nodesOnline}`}
              hint={`${nodes.length} ${t("nav.nodes")}`}
              tone="info"
              className="bg-card/70 backdrop-blur-xl"
            />
          </div>
        )}

        <div className="panel mb-5 flex flex-wrap items-center gap-2 p-2.5">
          <div className="relative min-w-52 flex-1 sm:max-w-sm">
            <Search className="text-muted-foreground/70 pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2" />
            <Input
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") commitSearch();
              }}
              placeholder={t("devices.searchPh")}
              className="border-transparent bg-transparent pr-12 pl-9 shadow-none hover:border-transparent hover:bg-transparent focus-visible:border-border/70 focus-visible:bg-background/40"
            />
            <kbd className="border-border/60 bg-card/60 text-muted-foreground/60 pointer-events-none absolute top-1/2 right-2.5 hidden h-5 -translate-y-1/2 items-center rounded border px-1.5 font-mono text-[9px] sm:flex">
              ↵
            </kbd>
          </div>
          <Button onClick={commitSearch} aria-label={t("common.search")} className="h-10">
            <Search className="size-4" />
            <span className="hidden sm:inline">{t("common.search")}</span>
          </Button>

          <span className="bg-border/60 mx-0.5 hidden h-6 w-px sm:block" aria-hidden />

          <Select
            value={nodeFilter}
            onValueChange={(v) => {
              setNodeFilter(v);
              setPage(1);
            }}
          >
            <SelectTrigger className="w-40 border-transparent bg-transparent shadow-none hover:border-border/60 hover:bg-card/50">
              <SelectValue placeholder={t("devices.allNodes")} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t("devices.allNodes")}</SelectItem>
              {nodes.map((n) => (
                <SelectItem key={n.id} value={String(n.id)}>
                  {n.hostname}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select
            value={typeFilter}
            onValueChange={(v) => {
              setTypeFilter(v);
              setPage(1);
            }}
          >
            <SelectTrigger className="w-36 border-transparent bg-transparent shadow-none hover:border-border/60 hover:bg-card/50">
              <SelectValue placeholder={t("devices.allTypes")} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t("devices.allTypes")}</SelectItem>
              {Object.entries(DEVICE_TYPE_META).map(([k, m]) => (
                <SelectItem key={k} value={k}>
                  {m.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <div className="border-border/60 bg-secondary/40 flex items-center rounded-full border p-1" role="group">
            {(["active", "archived"] as const).map((value) => (
              <button
                key={value}
                type="button"
                aria-pressed={archivedFilter === value}
                onClick={() => {
                  setArchivedFilter(value);
                  setPage(1);
                }}
                className={cn(
                  "cursor-pointer rounded-full px-3 py-1.5 font-mono text-[10px] tracking-[0.08em] uppercase transition-colors",
                  archivedFilter === value
                    ? "bg-card text-foreground shadow-[0_1px_2px_0_oklch(0_0_0/0.08)]"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {value === "active" ? t("devices.active") : t("devices.archived")}
              </button>
            ))}
          </div>

          <Select
            value={sort}
            onValueChange={(v) => {
              setSort(v as SortKey);
              setPage(1);
            }}
          >
            <SelectTrigger className="ml-auto w-40 border-transparent bg-transparent shadow-none hover:border-border/60 hover:bg-card/50">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="newest">{t("devices.sortNewest")}</SelectItem>
              <SelectItem value="oldest">{t("devices.sortOldest")}</SelectItem>
              <SelectItem value="capacity_desc">{t("devices.sortCapacityDown")}</SelectItem>
              <SelectItem value="capacity_asc">{t("devices.sortCapacityUp")}</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {loading ? (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-[268px]" />
            ))}
          </div>
        ) : items.length === 0 ? (
          hasFilters ? (
            <EmptyState icon={HardDrive} title={t("devices.emptyFilteredTitle")} description={t("devices.emptyFilteredDesc")} />
          ) : (
            <EmptyState
              icon={HardDrive}
              title={t("devices.emptyTitle")}
              description={t("devices.emptyDesc")}
              action={
                <Button asChild>
                  <Link to="/nodes">
                    <Plus className="size-4" /> {t("devices.registerNode")}
                  </Link>
                </Button>
              }
            />
          )
        ) : (
          <div className="stagger grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {items.map((d) => (
              <DeviceCard
                key={d.id}
                device={d}
                nodeName={deviceNodeInfo.get(d.id)?.hostname}
                onOpen={(dev) =>
                  navigate(`/devices/${dev.id}`, {
                    state: {
                      from: `${location.pathname}${location.search}`,
                      nodeName: deviceNodeInfo.get(dev.id)?.hostname,
                      nodeId: deviceNodeInfo.get(dev.id)?.id,
                    },
                  })
                }
                onChanged={patchItem}
                onArchived={removeItem}
              />
            ))}
          </div>
        )}

        <div className="mt-6">
          <Pagination page={page} pages={pages} total={total} limit={limit} onPage={setPage} onLimit={(l) => { setLimit(l); setPage(1); }} />
        </div>
      </div>
      {deviceId ? (
        <Outlet
          context={{
            onChanged: patchItem,
            nodeName: deviceNodeInfo.get(Number(deviceId))?.hostname,
            nodeId: deviceNodeInfo.get(Number(deviceId))?.id,
          }}
        />
      ) : null}
    </>
  );
}
