import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Bell, Loader2, Mail, MessageCircle, MessageSquare, Plus, Radio, Send, Smartphone, Trash2, Users, Webhook, Zap } from "lucide-react";
import {
  createAlert,
  deleteAlert,
  listAlerts,
  testAlert,
  updateAlert,
  type AlertResponse,
} from "@/client";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { RefreshButton } from "@/components/RefreshButton";
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
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useEnvs } from "@/context/use-envs";
import { useLanguage } from "@/context/use-lang";
import { tStatic } from "@/i18n";
import { unwrap } from "@/lib/api";
import { MAX_ENABLED_ALERTS, ALERT_TYPES, ALERT_TYPE_KEYS } from "@/lib/constants";
import { formatRelative } from "@/lib/format";
import { toastError, toastOk } from "@/lib/toast";
import { cn } from "@/lib/utils";

const ALERT_ICONS: Record<string, typeof Mail> = {
  email: Mail,
  discord: MessageCircle,
  telegram: Send,
  slack: MessageSquare,
  ntfy: Bell,
  gotify: Radio,
  pushover: Smartphone,
  pushbullet: Smartphone,
  generic_webhook: Webhook,
  google_chat: MessageSquare,
  matrix: Users,
  mattermost: MessageSquare,
  msteams: MessageSquare,
  wechat_work: MessageCircle,
  dingtalk: MessageCircle,
  feishu: Send,
  prowl: Bell,
  ifttt: Zap,
  linenotify: MessageCircle,
};

const ALERT_TONES: Record<string, string> = {
  email: "border-info/20 bg-info/[0.08] text-info",
  discord: "border-nvme/20 bg-nvme/[0.08] text-nvme",
  telegram: "border-info/20 bg-info/[0.08] text-info",
  slack: "border-scsi-ssd/20 bg-scsi-ssd/[0.08] text-scsi-ssd",
  generic_webhook: "border-primary/20 bg-primary/[0.08] text-primary",
};

export function AlertsPage() {
  const { t } = useLanguage();
  const { envs } = useEnvs();
  const [items, setItems] = useState<AlertResponse[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<AlertResponse | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  // add form
  const [type, setType] = useState("email");
  const [name, setName] = useState("");
  const [target, setTarget] = useState("");
  const [adding, setAdding] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await unwrap(listAlerts());
      setItems(res);
      setLoadError(null);
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : tStatic("alerts.failedLoad"));
      toastError(e, tStatic("alerts.failedLoad"));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const enabledCount = items?.filter((n) => n.enabled).length ?? 0;

  const submitAdd = async (e: FormEvent) => {
    e.preventDefault();
    if (!target.trim()) return;
    setAdding(true);
    try {
      await unwrap(
        createAlert({ body: { alert_type: type, alert_target: target.trim(), alert_name: name.trim() || undefined } }),
      );
      setAddOpen(false);
      setName("");
      setTarget("");
      toastOk(t("alerts.addedOk"));
      void load();
    } catch (err) {
      toastError(err, t("alerts.failedAdd"));
    } finally {
      setAdding(false);
    }
  };

  const toggle = async (n: AlertResponse, enabled: boolean) => {
    setBusyId(n.id);
    try {
      const updated = await unwrap(updateAlert({ path: { alert_id: n.id }, body: { enabled } }));
      setItems((prev) => prev?.map((x) => (x.id === n.id ? updated : x)) ?? prev);
    } catch (e) {
      toastError(e, t("alerts.failedUpdate"));
    } finally {
      setBusyId(null);
    }
  };

  const sendTest = async (n: AlertResponse) => {
    setBusyId(n.id);
    try {
      await unwrap(testAlert({ path: { alert_id: n.id } }));
      toastOk(t("alerts.testSent", { label: ALERT_TYPES[n.alert_type]?.label ?? n.alert_type }));
    } catch (e) {
      toastError(e, t("alerts.failedTest"));
    } finally {
      setBusyId(null);
    }
  };

  const doDelete = async () => {
    if (!deleteTarget) return;
    setBusyId(deleteTarget.id);
    try {
      await unwrap(deleteAlert({ path: { alert_id: deleteTarget.id } }));
      setItems((prev) => prev?.filter((x) => x.id !== deleteTarget.id) ?? prev);
      setDeleteTarget(null);
    } catch (e) {
      toastError(e, t("alerts.failedDelete"));
    } finally {
      setBusyId(null);
    }
  };

  const typeMeta = ALERT_TYPES[type];

  return (
    <>
      <PageHeader
        title={t("alerts.title")}
        description={
          items
            ? `${t("alerts.count", { count: items.length })} · ${t("alerts.enabledCount", { enabled: enabledCount, max: MAX_ENABLED_ALERTS })}`
            : t("alerts.descDefault")
        }
      >
        <RefreshButton onRefresh={load} disabled={items === null && loadError === null} label={t("alerts.refresh")} />
        <Button onClick={() => setAddOpen(true)}>
          <Plus className="size-4" /> {t("alerts.add")}
        </Button>
      </PageHeader>

      {items === null ? (
        loadError ? (
          <EmptyState
            icon={Bell}
            title={t("alerts.failedLoad")}
            description={loadError}
            action={
              <Button onClick={() => void load()}>
                {t("alerts.refresh")}
              </Button>
            }
          />
        ) : (
          <div className="flex flex-col gap-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-20" />
            ))}
          </div>
        )
      ) : items.length === 0 ? (
        <EmptyState
          icon={Bell}
          title={t("alerts.emptyTitle")}
          description={t("alerts.emptyDesc")}
          action={
            <Button onClick={() => setAddOpen(true)}>
              <Plus className="size-4" /> {t("alerts.add")}
            </Button>
          }
        />
      ) : (
        <div className="stagger flex flex-col gap-3">
          {items.map((n) => {
            const meta = ALERT_TYPES[n.alert_type];
            const isEmail = n.alert_type === "email";
            const emailBlocked = isEmail && !envs?.smtp_enabled && !n.enabled;
            const atLimit = !n.enabled && enabledCount >= MAX_ENABLED_ALERTS;
            const toggleDisabled = busyId === n.id || emailBlocked || atLimit;
            const Icon = ALERT_ICONS[n.alert_type] ?? Mail;
            const tone = ALERT_TONES[n.alert_type] ?? "border-border/70 bg-secondary/60 text-muted-foreground";

            return (
              <div
                key={n.id}
                className={cn(
                  "panel panel-hover group relative flex flex-wrap items-start gap-4 overflow-hidden p-4 sm:items-center sm:p-5",
                  n.enabled && "border-success/25",
                )}
              >
                <span
                  className={cn(
                    "absolute inset-y-3 left-0 w-[2px] rounded-full transition-opacity",
                    n.enabled ? "bg-success shadow-[0_0_12px_var(--success)] opacity-80" : "bg-border opacity-0",
                  )}
                  aria-hidden
                />

                <span className={cn("flex size-11 shrink-0 items-center justify-center rounded-xl border", tone)}>
                  <Icon className="size-5" strokeWidth={1.7} />
                </span>

                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="font-display truncate text-[14px] font-semibold tracking-[-0.01em]">
                      {n.alert_name || meta?.label || n.alert_type}
                    </p>
                    <Badge variant="outline">{meta?.label ?? n.alert_type}</Badge>
                    {n.enabled ? (
                      <Badge variant="outline" className="border-success/25 bg-success/10 text-success gap-1.5">
                        <span className="status-dot" /> {t("alerts.enabled")}
                      </Badge>
                    ) : (
                      <span className="text-muted-foreground/60 font-mono text-[9px] tracking-[0.12em] uppercase">
                        {t("alerts.disabled")}
                      </span>
                    )}
                  </div>
                  <p className="text-muted-foreground mt-1.5 truncate font-mono text-[11px]" title={n.alert_target}>
                    {n.alert_target}
                  </p>
                  <p className="text-muted-foreground/65 mt-0.5 text-[11px]">{t("alerts.added", { when: formatRelative(n.add_at) })}</p>
                </div>

                <div className="flex w-full items-center justify-end gap-1.5 border-t border-border/40 pt-3 sm:w-auto sm:border-0 sm:pt-0">
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        variant="outline"
                        size="icon-sm"
                        aria-label={t("alerts.testAria")}
                        disabled={busyId === n.id}
                        onClick={() => void sendTest(n)}
                        className="opacity-100 transition-opacity sm:opacity-60 sm:group-hover:opacity-100"
                      >
                        {busyId === n.id ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />}
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>{t("alerts.testTip")}</TooltipContent>
                  </Tooltip>

                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        variant="outline"
                        size="icon-sm"
                        aria-label={t("alerts.deleteAria")}
                        className="hover:text-destructive opacity-100 transition-opacity sm:opacity-60 sm:group-hover:opacity-100"
                        disabled={busyId === n.id}
                        onClick={() => setDeleteTarget(n)}
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>{t("alerts.deleteTip")}</TooltipContent>
                  </Tooltip>

                  <span className="bg-border/60 mx-1 hidden h-6 w-px sm:block" aria-hidden />

                  <Tooltip>
                    <TooltipTrigger asChild>
                      <span>
                        <Switch
                          checked={n.enabled}
                          disabled={toggleDisabled}
                          onCheckedChange={(v) => void toggle(n, v)}
                          aria-label={n.enabled ? t("alerts.disable") : t("alerts.enable")}
                        />
                      </span>
                    </TooltipTrigger>
                    {emailBlocked ? (
                      <TooltipContent>{t("alerts.smtpTip")}</TooltipContent>
                    ) : atLimit ? (
                      <TooltipContent>{t("alerts.limitTip", { max: MAX_ENABLED_ALERTS })}</TooltipContent>
                    ) : null}
                  </Tooltip>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* add dialog */}
      <Dialog open={addOpen} onOpenChange={setAddOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("alerts.addTitle")}</DialogTitle>
            <DialogDescription>
              {t("alerts.addDesc", { max: MAX_ENABLED_ALERTS })}
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={submitAdd} className="flex flex-col gap-3">
            <div className="grid gap-1.5">
              <Label htmlFor="alert-type">{t("alerts.typeLabel")}</Label>
              <Select value={type} onValueChange={setType}>
                <SelectTrigger id="alert-type" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="max-h-64">
                  {ALERT_TYPE_KEYS.map((k) => (
                    <SelectItem key={k} value={k}>
                      {ALERT_TYPES[k].label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {typeMeta?.hintKey && <p className="text-muted-foreground text-xs">{t(typeMeta.hintKey)}</p>}
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="alert-name">{t("alerts.nameLabel")}</Label>
              <Input id="alert-name" value={name} onChange={(e) => setName(e.target.value)} placeholder={t("alerts.namePh")} />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="alert-target">{t("alerts.targetLabel")}</Label>
              <Input
                id="alert-target"
                value={target}
                onChange={(e) => setTarget(e.target.value)}
                placeholder={typeMeta?.placeholder}
                required
                className="font-mono text-sm"
              />
            </div>
            <DialogFooter>
              <Button type="submit" disabled={adding || !target.trim()}>
                {adding && <Loader2 className="size-4 animate-spin" />}
                {t("alerts.addBtn")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* delete confirm */}
      <AlertDialog open={!!deleteTarget} onOpenChange={(o) => !o && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("alerts.deleteTitle")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("alerts.deleteDesc", {
                name:
                  deleteTarget?.alert_name ||
                  ALERT_TYPES[deleteTarget?.alert_type ?? ""]?.label ||
                  deleteTarget?.alert_type ||
                  "",
                target: deleteTarget?.alert_target,
              })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("common.cancel")}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              disabled={busyId === deleteTarget?.id}
              onClick={(e) => {
                e.preventDefault();
                void doDelete();
              }}
            >
              {busyId === deleteTarget?.id ? <Loader2 className="size-4 animate-spin" /> : null}
              {t("common.delete")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
