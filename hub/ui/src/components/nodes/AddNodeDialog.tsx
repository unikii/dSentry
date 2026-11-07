import { useEffect, useState } from "react";
import { Loader2, TerminalSquare } from "lucide-react";
import { createNode, type NodeCreateResponse } from "@/client";
import { CopyButton } from "@/components/CopyButton";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useLanguage } from "@/context/use-lang";
import { tStatic } from "@/i18n";
import { API_ENDPOINT, GITHUB_REPO, unwrap } from "@/lib/api";
import { toastError } from "@/lib/toast";

interface AddNodeDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

type InstallTab = "linux" | "windows" | "manual";

export function AddNodeDialog({ open, onOpenChange }: AddNodeDialogProps) {
  const { t } = useLanguage();
  const [node, setNode] = useState<NodeCreateResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState<InstallTab>("linux");

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setNode(null);
    unwrap(createNode())
      .then((created) => {
        if (!cancelled) setNode(created);
      })
      .catch((e) => {
        if (cancelled) return;
        toastError(e, tStatic("addNode.failed"));
        onOpenChange(false);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, onOpenChange]);

  const pushKey = node?.push_key ?? "";
  const commands: Record<InstallTab, string> = {
    linux: `export GITHUB_REPO="${GITHUB_REPO}"; curl -fsSL https://raw.githubusercontent.com/${GITHUB_REPO}/main/scripts/install.sh | sudo GITHUB_REPO="$GITHUB_REPO" sh -s -- "${API_ENDPOINT}" "${pushKey}"`,
    windows: `$env:GITHUB_REPO="${GITHUB_REPO}"; $env:API_ENDPOINT="${API_ENDPOINT}"; $env:PUSH_KEY="${pushKey}"; iwr -useb https://raw.githubusercontent.com/${GITHUB_REPO}/main/scripts/install.ps1 | iex`,
    manual: `dsnode --api-endpoint ${API_ENDPOINT} --push-key ${pushKey}`,
  };
  const hints: Record<InstallTab, string> = {
    linux: t("addNode.linuxHint"),
    windows: t("addNode.windowsHint"),
    manual: t("addNode.manualHint"),
  };
  const activeCmd = node ? commands[tab] : "";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{t("addNode.title")}</DialogTitle>
          <DialogDescription>
            {t("addNode.desc")}
          </DialogDescription>
        </DialogHeader>

        {loading || !node ? (
          <div className="flex h-40 items-center justify-center">
            <Loader2 className="text-muted-foreground size-6 animate-spin" />
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            <div>
              <p className="text-muted-foreground mb-1.5 text-xs font-medium tracking-wide uppercase">{t("addNode.pushKey")}</p>
              <code className="bg-secondary/35 border-border/55 block w-full rounded-xl border px-3 py-2.5 font-mono text-[12px] break-all select-all">
                {node.push_key}
              </code>
            </div>

            <div>
              <p className="text-muted-foreground mb-1.5 text-xs font-medium tracking-wide uppercase">
                {t("addNode.installCmd")}
              </p>
              <Tabs value={tab} onValueChange={(v) => setTab(v as InstallTab)}>
                <TabsList>
                  <TabsTrigger value="linux">{t("addNode.tabLinux")}</TabsTrigger>
                  <TabsTrigger value="windows">{t("addNode.tabWindows")}</TabsTrigger>
                  <TabsTrigger value="manual">{t("addNode.tabManual")}</TabsTrigger>
                </TabsList>
                {(Object.keys(commands) as InstallTab[]).map((key) => (
                  <TabsContent key={key} value={key} className="flex flex-col gap-2">
                    <div className="bg-secondary/35 border-border/55 relative rounded-xl border">
                      <TerminalSquare className="text-muted-foreground absolute top-3 left-3 size-4" />
                      <code className="block overflow-x-auto py-2.5 pr-3 pl-9 font-mono text-sm break-all select-all">
                        {commands[key]}
                      </code>
                    </div>
                    <p className="text-muted-foreground text-xs leading-relaxed">{hints[key]}</p>
                  </TabsContent>
                ))}
              </Tabs>
            </div>

            <CopyButton text={activeCmd} label={t("addNode.copyCmd")} className="self-start" />

            <p className="border-border/55 bg-secondary/25 text-muted-foreground rounded-xl border border-dashed p-3 text-xs leading-relaxed">
              {t("addNode.note")}
            </p>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
