import { useCallback, useEffect, useState } from "react";
import { Activity, HardDrive, Plus, Search, Server, Wifi, WifiOff } from "lucide-react";
import { listNodes, type NodeResponse } from "@/client";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { RefreshButton } from "@/components/RefreshButton";
import { StatCard } from "@/components/StatCard";
import { AddNodeDialog } from "@/components/nodes/AddNodeDialog";
import { NodeCard } from "@/components/nodes/NodeCard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/context/use-auth";
import { useEnvs } from "@/context/use-envs";
import { useLanguage } from "@/context/use-lang";
import { unwrap } from "@/lib/api";
import { parseUTC } from "@/lib/format";
import { useNow } from "@/lib/use-now";
import { usePagedList } from "@/lib/use-paged-list";

type NodeSortKey = "last_metrics_push" | "reg_at";
type NodeSort = "last_push_desc" | "last_push_asc" | "reg_desc" | "reg_asc";

const SORT_MAP: Record<NodeSort, { sort_by: NodeSortKey; sort_order: "asc" | "desc" }> = {
  last_push_desc: { sort_by: "last_metrics_push", sort_order: "desc" },
  last_push_asc: { sort_by: "last_metrics_push", sort_order: "asc" },
  reg_desc: { sort_by: "reg_at", sort_order: "desc" },
  reg_asc: { sort_by: "reg_at", sort_order: "asc" },
};

export function NodesPage() {
  const { t } = useLanguage();
  const { envs } = useEnvs();
  const { user } = useAuth();
  const now = useNow();

  const [page, setPage] = useState(1);
  const [limit, setLimit] = useState(20);
  const [searchInput, setSearchInput] = useState("");
  const [keyword, setKeyword] = useState("");
  const [sort, setSort] = useState<NodeSort>("last_push_desc");
  const [addOpen, setAddOpen] = useState(false);

  const commitSearch = () => {
    setKeyword(searchInput.trim());
    setPage(1);
  };

  const fetchNodes = useCallback(() => {
    const { sort_by, sort_order } = SORT_MAP[sort];
    return listNodes({ query: { plimit: limit, pnum: page, keyword: keyword || undefined, sort_by, sort_order } });
  }, [limit, page, keyword, sort]);

  const { items, total, pages, loading, patchItem, removeItem, reload } = usePagedList<NodeResponse>(
    fetchNodes,
    t("nodes.failedLoad"),
  );

  // The paged list's `total` is filtered by the active search. The add-node
  // limit and the "N / limit registered" header need the unfiltered count.
  const [allNodes, setAllNodes] = useState<number | null>(null);
  const reloadAllNodes = useCallback(async () => {
    try {
      const res = await unwrap(listNodes({ query: { plimit: 1, pnum: 1 } }));
      setAllNodes(res.total);
    } catch {
      // The list itself surfaces connectivity errors via usePagedList.
    }
  }, []);

  useEffect(() => {
    void reloadAllNodes();
  }, [reloadAllNodes]);

  const nodeLimit = user?.node_limit ?? envs?.global_node_per_user ?? 20;
  const registeredNodes = allNodes ?? total;
  const canAdd = registeredNodes < nodeLimit;

  const intervalMs = ((envs?.global_push_interval ?? 5) + 5) * 60_000;
  const online = items.filter((n) => {
    const last = parseUTC(n.last_metrics_push);
    return !!last && now - last.getTime() <= intervalMs;
  }).length;
  const offline = items.length - online;
  const linkedDevices = items.reduce((sum, n) => sum + (n.last_device_push?.length ?? 0), 0);
  const totalPushes = items.reduce((sum, n) => sum + (n.push_count ?? 0), 0);

  return (
    <>
      <PageHeader
        title={t("nodes.title")}
        description={loading ? t("common.loading") : t("nodes.registered", { total: registeredNodes, limit: nodeLimit })}
      >
        <RefreshButton
          onRefresh={() => {
            void reloadAllNodes();
            void reload(true);
          }}
          disabled={loading}
          label={t("nodes.refresh")}
        />
        <Button onClick={() => setAddOpen(true)} disabled={!canAdd} title={canAdd ? undefined : t("nodes.limitReached", { limit: nodeLimit })}>
          <Plus className="size-4" /> {t("nodes.add")}
        </Button>
      </PageHeader>

      {loading ? (
        <Skeleton className="mb-5 h-[108px] w-full" />
      ) : (
        <div className="panel mb-5 grid grid-cols-2 gap-px overflow-hidden bg-border/25 sm:grid-cols-4">
          <StatCard
            icon={Wifi}
            label={t("node.online")}
            value={online}
            hint={t("nodes.registered", { total: registeredNodes, limit: nodeLimit })}
            tone={online > 0 ? "success" : "neutral"}
            className="bg-card/70 backdrop-blur-xl"
          />
          <StatCard
            icon={WifiOff}
            label={t("node.offline")}
            value={offline}
            hint={t("node.offlineTip", { minutes: (envs?.global_push_interval ?? 5) + 5 })}
            tone={offline > 0 ? "warning" : "success"}
            className="bg-card/70 backdrop-blur-xl"
          />
          <StatCard
            icon={HardDrive}
            label={t("node.devices")}
            value={linkedDevices}
            hint={t("nodes.title")}
            tone="primary"
            className="bg-card/70 backdrop-blur-xl"
          />
          <StatCard
            icon={Activity}
            label={t("node.pushes")}
            value={totalPushes.toLocaleString()}
            hint={`${items.length} ${t("nav.nodes")}`}
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
            placeholder={t("nodes.searchPh")}
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
        <span className="text-muted-foreground hidden items-center gap-1.5 px-2 font-mono text-[10px] tracking-[0.1em] uppercase lg:flex">
          <Server className="size-3.5" />
          {items.length} / {total}
        </span>
        <Select
          value={sort}
          onValueChange={(v) => {
            setSort(v as NodeSort);
            setPage(1);
          }}
        >
          <SelectTrigger className="ml-auto w-44 border-transparent bg-transparent shadow-none hover:border-border/60 hover:bg-card/50">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="last_push_desc">{t("nodes.sortPushDown")}</SelectItem>
            <SelectItem value="last_push_asc">{t("nodes.sortPushUp")}</SelectItem>
            <SelectItem value="reg_desc">{t("nodes.sortRegDown")}</SelectItem>
            <SelectItem value="reg_asc">{t("nodes.sortRegUp")}</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {loading ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-[250px]" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <EmptyState
          icon={Server}
          title={keyword ? t("nodes.emptySearchTitle") : t("nodes.emptyTitle")}
          description={keyword ? t("nodes.emptySearchDesc") : t("nodes.emptyDesc")}
          action={
            !keyword && canAdd ? (
              <Button onClick={() => setAddOpen(true)}>
                <Plus className="size-4" /> {t("nodes.add")}
              </Button>
            ) : undefined
          }
        />
      ) : (
        <div className="stagger grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {items.map((n) => (
            <NodeCard
              key={n.id}
              node={n}
              onChanged={patchItem}
              onDeleted={(id) => {
                removeItem(id);
                setAllNodes((count) => Math.max(0, (count ?? total) - 1));
              }}
            />
          ))}
        </div>
      )}

      <div className="mt-6">
        <Pagination page={page} pages={pages} total={total} limit={limit} onPage={setPage} onLimit={(l) => { setLimit(l); setPage(1); }} />
      </div>

      <AddNodeDialog
        open={addOpen}
        onOpenChange={(o) => {
          setAddOpen(o);
          if (!o) {
            void reload();
            void reloadAllNodes();
          }
        }}
      />
    </>
  );
}
