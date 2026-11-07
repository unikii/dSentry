import { useEffect, useState } from "react";
import { Check, HardDrive, Pencil, Server, Trash2, WifiOff, X } from "lucide-react";
import { deleteNode, updateNode, type NodeResponse } from "@/client";
import { TagEditor } from "@/components/TagEditor";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useEnvs } from "@/context/use-envs";
import { useLanguage } from "@/context/use-lang";
import { unwrap } from "@/lib/api";
import { formatDate, formatRelative, parseUTC } from "@/lib/format";
import { useNow } from "@/lib/use-now";
import { toastError } from "@/lib/toast";
import { cn } from "@/lib/utils";

interface NodeCardProps {
  node: NodeResponse;
  onChanged: (node: NodeResponse) => void;
  onDeleted: (id: number) => void;
}

function DataField({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <p className="mono-label text-muted-foreground/65 mb-1">{label}</p>
      <p className="truncate text-[12px] leading-snug">{value}</p>
    </div>
  );
}

export function NodeCard({ node, onChanged, onDeleted }: NodeCardProps) {
  const { envs } = useEnvs();
  const { t } = useLanguage();
  const [editingName, setEditingName] = useState(false);
  const [nameValue, setNameValue] = useState(node.hostname ?? "");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmText, setConfirmText] = useState("");
  const [deleting, setDeleting] = useState(false);

  useEffect(() => setNameValue(node.hostname ?? ""), [node.hostname]);

  const hostname = node.hostname || `Node #${node.id}`;
  const deviceCount = node.last_device_push?.length ?? 0;

  const intervalMs = ((envs?.global_push_interval ?? 5) + 5) * 60_000;
  const now = useNow();
  const lastPush = parseUTC(node.last_metrics_push);
  const offline = !lastPush || now - lastPush.getTime() > intervalMs;

  const saveHostname = async () => {
    setEditingName(false);
    const v = nameValue.trim();
    if (!v || v === node.hostname) {
      setNameValue(node.hostname ?? "");
      return;
    }
    try {
      const updated = await unwrap(updateNode({ path: { node_id: node.id }, body: { hostname: v } }));
      onChanged(updated);
    } catch (e) {
      toastError(e, t("node.failedHostname"));
      setNameValue(node.hostname ?? "");
    }
  };

  const saveTags = async (tags: string[]) => {
    try {
      const updated = await unwrap(updateNode({ path: { node_id: node.id }, body: { tags } }));
      onChanged(updated);
    } catch (e) {
      toastError(e, t("node.failedTags"));
    }
  };

  const doDelete = async () => {
    setDeleting(true);
    try {
      await unwrap(deleteNode({ path: { node_id: node.id } }));
      onDeleted(node.id);
    } catch (e) {
      toastError(e, t("node.failedDelete"));
    } finally {
      setDeleting(false);
      setConfirmOpen(false);
    }
  };

  return (
    <article className={cn("panel panel-hover group relative flex flex-col overflow-hidden", !offline && "border-success/25")}>
      <span
        className={cn(
          "absolute inset-x-0 top-0 h-px bg-gradient-to-r",
          offline ? "from-warning/60 via-warning/15 to-transparent" : "from-success/70 via-success/20 to-transparent",
        )}
        aria-hidden
      />
      <div className="pointer-events-none absolute -top-20 -right-20 size-44 rounded-full bg-primary/[0.04] blur-3xl" aria-hidden />

      <div className="relative flex flex-col gap-4 p-5">
        <div className="flex items-start gap-3">
          <span
            className={cn(
              "relative flex size-11 shrink-0 items-center justify-center rounded-xl border",
              offline
                ? "border-warning/20 bg-warning/[0.07] text-warning"
                : "border-success/20 bg-success/[0.07] text-success",
            )}
          >
            <Server className="size-5" strokeWidth={1.6} />
            <span
              className={cn(
                "ring-card absolute -right-0.5 -bottom-0.5 size-2.5 rounded-full ring-2",
                offline ? "bg-warning" : "bg-success",
              )}
            >
              {!offline && <span className="bg-success/70 radar-ping absolute inset-0 rounded-full" />}
            </span>
          </span>

          <div className="min-w-0 flex-1 pt-0.5">
            {editingName ? (
              <span className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
                <Input
                  autoFocus
                  value={nameValue}
                  onChange={(e) => setNameValue(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void saveHostname();
                    if (e.key === "Escape") {
                      setNameValue(node.hostname ?? "");
                      setEditingName(false);
                    }
                  }}
                  className="h-8 w-44"
                />
                <Button variant="ghost" size="icon-sm" aria-label={t("node.saveHostname")} onClick={() => void saveHostname()}>
                  <Check className="size-4" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={t("node.cancelEdit")}
                  onClick={() => {
                    setNameValue(node.hostname ?? "");
                    setEditingName(false);
                  }}
                >
                  <X className="size-4" />
                </Button>
              </span>
            ) : (
              <div className="flex min-w-0 items-center gap-1.5">
                <p className="font-display truncate text-[15px] leading-snug font-semibold tracking-[-0.015em]" title={hostname}>
                  {hostname}
                </p>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={t("node.editHostname")}
                  className="text-muted-foreground/60 hover:text-foreground -my-1 opacity-100 transition-opacity sm:opacity-0 sm:group-hover:opacity-100"
                  onClick={() => setEditingName(true)}
                >
                  <Pencil className="size-3.5" />
                </Button>
              </div>
            )}
            <p className="text-muted-foreground mt-1 truncate font-mono text-[10px] tracking-[0.08em] uppercase">
              #{String(node.id).padStart(2, "0")}
            </p>
          </div>

          <div className="flex shrink-0 items-center gap-1">
            {offline ? (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Badge variant="outline" className="border-warning/30 bg-warning/10 text-warning gap-1.5">
                    <WifiOff className="size-3" /> {t("node.offline")}
                  </Badge>
                </TooltipTrigger>
                <TooltipContent>{t("node.offlineTip", { minutes: (envs?.global_push_interval ?? 5) + 5 })}</TooltipContent>
              </Tooltip>
            ) : (
              <Badge variant="outline" className="border-success/25 bg-success/10 text-success gap-1.5">
                <span className="status-dot" /> {t("node.online")}
              </Badge>
            )}
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={t("node.delete")}
                  className="text-muted-foreground/60 hover:text-destructive -mr-1 opacity-100 transition-opacity sm:opacity-0 sm:group-hover:opacity-100"
                  onClick={() => {
                    setConfirmText("");
                    setConfirmOpen(true);
                  }}
                >
                  <Trash2 className="size-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>{t("node.delete")}</TooltipContent>
            </Tooltip>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-x-4 gap-y-3.5">
          <DataField label={t("node.os")} value={node.host_os || "—"} />
          <DataField
            label={t("node.devices")}
            value={
              <span className="flex items-center gap-1.5">
                <HardDrive className="text-muted-foreground/70 size-3" /> {deviceCount}
              </span>
            }
          />
          <DataField label={t("node.lastPush")} value={formatRelative(node.last_metrics_push)} />
          <DataField label={t("node.pushes")} value={<span className="tnum font-mono text-[11px]">{node.push_count.toLocaleString()}</span>} />
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border/50 pt-3">
          <TagEditor
            tags={node.tags ?? []}
            onSave={saveTags}
            compact
            className="opacity-100 transition-opacity sm:opacity-45 sm:group-hover:opacity-100"
          />
          <span className="text-muted-foreground/75 font-mono text-[9px] tracking-[0.1em] uppercase">
            {formatDate(node.reg_at)}
          </span>
        </div>
      </div>

      <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("node.deleteTitle", { name: hostname })}</AlertDialogTitle>
            <AlertDialogDescription asChild>
              <div className="flex flex-col gap-3">
                <p>{t("node.deleteDesc")}</p>
                <p>
                  {t("common.typeToConfirmPrefix")}{" "}
                  <code className="bg-primary/10 text-primary rounded-md px-1.5 py-0.5 font-mono text-xs font-semibold">{hostname}</code>{" "}
                  {t("common.typeToConfirmSuffix")}
                </p>
                <Input
                  value={confirmText}
                  onChange={(e) => setConfirmText(e.target.value)}
                  placeholder={hostname}
                  autoFocus
                />
              </div>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("common.cancel")}</AlertDialogCancel>
            <AlertDialogAction
              disabled={confirmText !== hostname || deleting}
              onClick={(e) => {
                e.preventDefault();
                void doDelete();
              }}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {deleting ? t("common.deleting") : t("node.deleteConfirm")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </article>
  );
}
