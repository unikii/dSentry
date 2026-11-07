import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  Check,
  ChevronRight,
  KeyRound,
  Loader2,
  LogOut,
  Monitor,
  Moon,
  Palette,
  PanelLeft,
  PanelRight,
  ShieldCheck,
  Sun,
  UserRound,
} from "lucide-react";
import { deleteUser, updateUser } from "@/client";
import { PageHeader } from "@/components/PageHeader";
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
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useAuth } from "@/context/use-auth";
import { useEnvs } from "@/context/use-envs";
import { useLanguage } from "@/context/use-lang";
import { usePrefs } from "@/context/use-prefs";
import { useTheme } from "@/context/use-theme";
import type { Theme } from "@/context/theme-context";
import type { MessageKey } from "@/context/lang-context";
import { LOCALES } from "@/i18n";
import { unwrap } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { toastError, toastOk } from "@/lib/toast";
import { cn } from "@/lib/utils";

const THEMES: { value: Theme; labelKey: MessageKey; icon: typeof Sun }[] = [
  { value: "light", labelKey: "settings.themeLight", icon: Sun },
  { value: "dark", labelKey: "settings.themeDark", icon: Moon },
  { value: "system", labelKey: "settings.themeSystem", icon: Monitor },
];

function SectionHeading({ icon: Icon, title, description }: { icon: typeof Palette; title: string; description: string }) {
  return (
    <div className="flex items-start gap-3">
      <span className="border-primary/20 bg-primary/[0.08] text-primary flex size-9 shrink-0 items-center justify-center rounded-xl border">
        <Icon className="size-[18px]" strokeWidth={1.7} />
      </span>
      <div className="min-w-0">
        <h2 className="font-display text-[15px] font-semibold tracking-[-0.015em]">{title}</h2>
        <p className="text-muted-foreground mt-0.5 text-xs leading-relaxed">{description}</p>
      </div>
    </div>
  );
}

function SettingRow({ title, description, children }: { title: string; description: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border/50 pt-4">
      <div>
        <p className="text-[13px] font-medium">{title}</p>
        <p className="text-muted-foreground mt-0.5 text-[11px]">{description}</p>
      </div>
      {children}
    </div>
  );
}

function ThemePreview({ mode }: { mode: Theme }) {
  const isDark = mode === "dark" || mode === "system";
  return (
    <div
      className={cn(
        "relative mb-2.5 h-14 overflow-hidden rounded-lg border border-border/60 p-1.5",
        mode === "system"
          ? "bg-[linear-gradient(100deg,#eef2f7_0%,#eef2f7_49%,#0a101a_50%,#0a101a_100%)]"
          : isDark
            ? "bg-[#0a101a]"
            : "bg-[#eef2f7]",
      )}
    >
      <div className="flex h-full gap-1.5">
        <div
          className={cn(
            "w-5 rounded-[4px] border",
            isDark ? "border-white/10 bg-white/[0.06]" : "border-slate-200 bg-white",
          )}
        />
        <div className="flex flex-1 flex-col gap-1 py-0.5">
          <div className={cn("h-1 w-8 rounded-full", isDark ? "bg-cyan-300/60" : "bg-teal-600/60")} />
          <div className={cn("h-1 w-11 rounded-full", isDark ? "bg-white/15" : "bg-slate-300")} />
          <div className={cn("h-1 w-6 rounded-full", isDark ? "bg-white/10" : "bg-slate-200")} />
          <div className="mt-auto flex gap-1">
            <div className={cn("h-2.5 flex-1 rounded-[3px] border", isDark ? "border-white/10 bg-white/[0.05]" : "border-slate-200 bg-white")} />
            <div className={cn("h-2.5 flex-1 rounded-[3px] border", isDark ? "border-cyan-300/20 bg-cyan-300/10" : "border-teal-600/20 bg-teal-600/10")} />
          </div>
        </div>
      </div>
    </div>
  );
}

export function SettingsPage() {
  const { t, lang, setLang } = useLanguage();
  const { theme, setTheme } = useTheme();
  const { navSide, setNavSide, navSlim, setNavSlim } = usePrefs();
  const { user, refreshUser, signOut } = useAuth();
  const { envs } = useEnvs();
  const navigate = useNavigate();

  const [username, setUsername] = useState(user?.username ?? "");
  const [savingUsername, setSavingUsername] = useState(false);

  const [pwCurrent, setPwCurrent] = useState("");
  const [pw1, setPw1] = useState("");
  const [pw2, setPw2] = useState("");
  const [savingPw, setSavingPw] = useState(false);

  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmText, setConfirmText] = useState("");
  const [deleting, setDeleting] = useState(false);

  const isPublic = envs?.run_mode === "public";

  const saveUsername = async (e: FormEvent) => {
    e.preventDefault();
    if (!user || !username.trim() || username.trim() === user.username) return;
    setSavingUsername(true);
    try {
      await unwrap(updateUser({ path: { user_id: user.id }, body: { username: username.trim() } }));
      await refreshUser();
      toastOk(t("settings.savedUsername"));
    } catch (err) {
      toastError(err, t("settings.failedUsername"));
    } finally {
      setSavingUsername(false);
    }
  };

  const savePassword = async (e: FormEvent) => {
    e.preventDefault();
    if (!user || pw1.length < 6 || pw1 !== pw2) return;
    const hadPassword = user.has_password;
    setSavingPw(true);
    try {
      await unwrap(updateUser({
        path: { user_id: user.id },
        body: {
          password: pw1,
          current_password: user.has_password ? pwCurrent : undefined,
        },
      }));
      await refreshUser();
      setPwCurrent("");
      setPw1("");
      setPw2("");
      toastOk(hadPassword ? t("settings.passwordUpdated") : t("settings.passwordSet"));
    } catch (err) {
      toastError(err, t("settings.failedPassword"));
    } finally {
      setSavingPw(false);
    }
  };

  const doDelete = async () => {
    if (!user) return;
    setDeleting(true);
    try {
      await unwrap(deleteUser({ path: { user_id: user.id }, body: { username: confirmText } }));
      signOut();
      navigate("/login", { replace: true });
    } catch (err) {
      toastError(err, t("settings.failedDelete"));
      setDeleting(false);
    }
  };

  const logout = () => {
    signOut();
    navigate("/login", { replace: true });
  };

  const modeLabel = isPublic ? t("login.modePublic") : t("login.modePrivate");
  const initial = (user?.username ?? "?").slice(0, 1).toUpperCase();

  return (
    <>
      <PageHeader title={t("settings.title")} description={t("settings.desc")} />

      <div className="grid max-w-6xl gap-5 lg:grid-cols-[minmax(0,1fr)_330px]">
        <div className="flex flex-col gap-5">
          {/* ------------------------------ Appearance ------------------------------ */}
          <section className="panel p-5 sm:p-6">
            <SectionHeading icon={Palette} title={t("settings.appearance")} description={t("settings.appearanceDesc")} />

            <div className="mt-5 flex flex-col gap-4">
              <div>
                <p className="text-[13px] font-medium">{t("settings.theme")}</p>
                <p className="text-muted-foreground mt-0.5 text-[11px]">{t("settings.themeDesc")}</p>
                <div className="mt-3 grid grid-cols-3 gap-2.5">
                  {THEMES.map(({ value, labelKey, icon: Icon }) => (
                    <button
                      key={value}
                      type="button"
                      onClick={() => setTheme(value)}
                      className={cn(
                        "group relative cursor-pointer rounded-xl border p-2 text-left transition-[border-color,background-color,box-shadow] duration-200",
                        theme === value
                          ? "border-primary/40 bg-primary/[0.055] ring-1 ring-primary/15"
                          : "border-border/60 bg-card/30 hover:border-border hover:bg-card/50",
                      )}
                    >
                      <ThemePreview mode={value} />
                      <span className="flex items-center gap-1.5 px-0.5 pb-0.5">
                        <Icon className="text-muted-foreground size-3.5" />
                        <span className="text-[11px] font-medium">{t(labelKey)}</span>
                      </span>
                      {theme === value && (
                        <span className="bg-primary text-primary-foreground absolute top-3 right-3 flex size-4 items-center justify-center rounded-full shadow-sm">
                          <Check className="size-2.5" strokeWidth={3} />
                        </span>
                      )}
                    </button>
                  ))}
                </div>
              </div>

              <SettingRow title={t("settings.language")} description={t("settings.languageDesc")}>
                <Select value={lang} onValueChange={(v) => setLang(v as typeof lang)}>
                  <SelectTrigger className="w-40">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {LOCALES.map((l) => (
                      <SelectItem key={l.value} value={l.value}>
                        {l.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </SettingRow>

              <SettingRow title={t("settings.navPosition")} description={t("settings.navPositionDesc")}>
                <div className="border-border/60 bg-secondary/40 flex rounded-lg border p-0.5">
                  {(["left", "right"] as const).map((side) => {
                    const Icon = side === "left" ? PanelLeft : PanelRight;
                    return (
                      <button
                        key={side}
                        type="button"
                        onClick={() => setNavSide(side)}
                        className={cn(
                          "text-muted-foreground flex cursor-pointer items-center gap-1.5 rounded-md px-3 py-1.5 text-xs capitalize transition-colors",
                          navSide === side && "bg-card text-foreground shadow-sm",
                        )}
                      >
                        <Icon className="size-3.5" />
                        {side === "left" ? t("settings.left") : t("settings.right")}
                      </button>
                    );
                  })}
                </div>
              </SettingRow>

              <SettingRow title={t("settings.slimNav")} description={t("settings.slimNavDesc")}>
                <Switch checked={navSlim} onCheckedChange={setNavSlim} aria-label={t("settings.slimNavAria")} />
              </SettingRow>
            </div>
          </section>

          {/* ------------------------------ Account ------------------------------ */}
          <section className="panel p-5 sm:p-6">
            <SectionHeading icon={UserRound} title={t("settings.user")} description={t("settings.account")} />

            <div className="mt-5 flex flex-col gap-5">
              <form onSubmit={saveUsername} className="flex flex-wrap items-end gap-2">
                <div className="grid min-w-52 flex-1 gap-1.5">
                  <Label htmlFor="username">{t("settings.username")}</Label>
                  <Input id="username" value={username} onChange={(e) => setUsername(e.target.value)} />
                </div>
                <Button type="submit" disabled={savingUsername || !username.trim() || username.trim() === user?.username}>
                  {savingUsername ? <Loader2 className="size-4 animate-spin" /> : <Check className="size-4" />}
                  {t("common.save")}
                </Button>
              </form>

              {!isPublic && (
                <form onSubmit={savePassword} className="flex flex-col gap-3 border-t border-border/50 pt-5">
                  <div className="flex items-start gap-2.5">
                    <span className="border-border/60 bg-secondary/60 text-muted-foreground flex size-8 shrink-0 items-center justify-center rounded-lg border">
                      <KeyRound className="size-4" />
                    </span>
                    <div>
                      <p className="text-[13px] font-medium">{user?.has_password ? t("settings.updatePassword") : t("settings.setPassword")}</p>
                      <p className="text-muted-foreground mt-0.5 text-[11px] leading-relaxed">
                        {user?.has_password ? t("settings.updatePasswordDesc") : t("settings.setPasswordDesc")}
                      </p>
                    </div>
                  </div>
                  {user?.has_password && (
                    <div className="grid max-w-sm gap-1.5">
                      <Label htmlFor="pwCurrent">{t("settings.currentPassword")}</Label>
                      <Input id="pwCurrent" type="password" autoComplete="current-password" value={pwCurrent} onChange={(e) => setPwCurrent(e.target.value)} />
                    </div>
                  )}
                  <div className="grid gap-3 sm:grid-cols-2">
                    <div className="grid gap-1.5">
                      <Label htmlFor="pw1">{t("settings.newPassword")}</Label>
                      <Input id="pw1" type="password" autoComplete="new-password" value={pw1} onChange={(e) => setPw1(e.target.value)} />
                    </div>
                    <div className="grid gap-1.5">
                      <Label htmlFor="pw2">{t("settings.repeatPassword")}</Label>
                      <Input id="pw2" type="password" autoComplete="new-password" value={pw2} onChange={(e) => setPw2(e.target.value)} />
                    </div>
                  </div>
                  {pw1 && pw1.length < 6 && <p className="text-destructive text-xs">{t("settings.passwordShort")}</p>}
                  {pw1.length >= 6 && pw2 && pw1 !== pw2 && <p className="text-destructive text-xs">{t("settings.passwordMismatch")}</p>}
                  <div>
                    <Button type="submit" disabled={savingPw || pw1.length < 6 || pw1 !== pw2 || (user?.has_password && !pwCurrent)}>
                      {savingPw && <Loader2 className="size-4 animate-spin" />}
                      {user?.has_password ? t("settings.updatePassword") : t("settings.setPassword")}
                    </Button>
                  </div>
                </form>
              )}
            </div>
          </section>

          {/* ------------------------------ Danger zone ------------------------------ */}
          <section className="panel relative overflow-hidden border-destructive/30 p-5 sm:p-6">
            <div className="bg-destructive/[0.045] pointer-events-none absolute -top-24 -right-24 size-56 rounded-full blur-3xl" aria-hidden />
            <div className="relative flex flex-col gap-5">
              <div className="flex items-start gap-3">
                <span className="border-destructive/25 bg-destructive/10 text-destructive flex size-9 shrink-0 items-center justify-center rounded-xl border">
                  <AlertTriangle className="size-[18px]" strokeWidth={1.7} />
                </span>
                <div>
                  <h2 className="font-display text-destructive text-[15px] font-semibold tracking-[-0.015em]">{t("settings.danger")}</h2>
                  <p className="text-muted-foreground mt-0.5 text-xs">{t("settings.dangerDesc")}</p>
                </div>
              </div>
              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-destructive/15 pt-4">
                <div>
                  <p className="text-[13px] font-medium">{t("settings.deleteAccount")}</p>
                  <p className="text-muted-foreground mt-0.5 text-[11px]">
                    {isPublic ? t("settings.deleteAccountPublic") : t("settings.deleteAccountPrivate")}
                  </p>
                </div>
                <Button variant="destructive" disabled={!isPublic} onClick={() => { setConfirmText(""); setConfirmOpen(true); }}>
                  {t("settings.deleteAccountBtn")}
                </Button>
              </div>
            </div>
          </section>
        </div>

        <aside className="flex flex-col gap-5">
          <div className="panel overflow-hidden">
            <div className="from-primary/25 via-primary/[0.08] relative h-24 overflow-hidden bg-gradient-to-br to-transparent">
              <div className="bg-grid-dense absolute inset-0 opacity-50 [mask-image:linear-gradient(to_bottom,black,transparent)]" aria-hidden />
              <div className="absolute top-3.5 right-3.5">
                <Badge variant="outline" className="border-success/25 bg-success/10 text-success gap-1.5 backdrop-blur-sm">
                  <span className="status-dot" /> {t("node.online")}
                </Badge>
              </div>
            </div>
            <div className="px-5 pb-5">
              <div className="border-card bg-card -mt-8 flex size-16 items-center justify-center rounded-2xl border-2 bg-gradient-to-br from-primary/30 to-primary/5 font-display text-2xl font-semibold text-primary shadow-[0_16px_40px_-20px_var(--primary)]">
                {initial}
              </div>
              <p className="font-display mt-3 truncate text-lg font-semibold tracking-[-0.02em]">
                {user?.username ?? "—"}
              </p>
              <div className="text-muted-foreground mt-1 flex flex-wrap items-center gap-1.5 text-[11px]">
                <span className="font-mono tracking-[0.08em] uppercase">{modeLabel}</span>
                {user?.oauth_provider && (
                  <>
                    <span className="bg-border size-0.5 rounded-full" />
                    <span>{user.oauth_provider}</span>
                  </>
                )}
              </div>

              <div className="mt-4 flex flex-col gap-2.5 border-t border-border/50 pt-4 text-xs">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-muted-foreground">{t("detail.registered")}</span>
                  <span className="font-mono text-[11px]">{formatDate(user?.reg_at)}</span>
                </div>
                <div className="flex items-center justify-between gap-2">
                  <span className="text-muted-foreground">{t("settings.user")}</span>
                  <span className="truncate">{user?.username ?? "—"}</span>
                </div>
                <div className="flex items-center justify-between gap-2">
                  <span className="text-muted-foreground">ID</span>
                  <span className="font-mono text-[11px]">#{user?.id ?? "—"}</span>
                </div>
              </div>

              <Button variant="outline" className="mt-4 w-full justify-between" onClick={logout}>
                <span className="flex items-center gap-2">
                  <LogOut className="size-4" /> {t("nav.logout")}
                </span>
                <ChevronRight className="size-3.5 opacity-50" />
              </Button>
            </div>
          </div>

          <div className="panel p-5">
            <div className="flex items-center gap-2">
              <ShieldCheck className="text-primary size-4" />
              <p className="mono-label text-muted-foreground">{t("login.server")}</p>
            </div>
            <div className="mt-4 flex flex-col gap-3 text-xs">
              <div className="flex items-center justify-between gap-2">
                <span className="text-muted-foreground">{t("login.mode")}</span>
                <span className="font-mono text-[11px]">{modeLabel}</span>
              </div>
              <div className="flex items-center justify-between gap-2">
                <span className="text-muted-foreground">{t("login.pushInterval")}</span>
                <span className="font-mono text-[11px]">{t("login.minutes", { n: envs?.global_push_interval ?? 0 })}</span>
              </div>
              <div className="flex items-center justify-between gap-2">
                <span className="text-muted-foreground">{t("login.dataKept")}</span>
                <span className="font-mono text-[11px]">{envs?.metrics_data_lifespan ?? "—"}</span>
              </div>
              <div className="flex items-center justify-between gap-2">
                <span className="text-muted-foreground">{t("login.nodesPerUser")}</span>
                <span className="font-mono text-[11px]">{envs?.global_node_per_user ?? "—"}</span>
              </div>
              <div className="flex items-center justify-between gap-2">
                <span className="text-muted-foreground">{t("login.devicesPerNode")}</span>
                <span className="font-mono text-[11px]">{envs?.global_device_per_node ?? "—"}</span>
              </div>
              <div className="flex items-center justify-between gap-2">
                <span className="text-muted-foreground">{t("login.emailNotify")}</span>
                <span className={cn("font-mono text-[11px]", envs?.smtp_enabled ? "text-success" : "text-muted-foreground")}>
                  {envs?.smtp_enabled ? t("login.available") : t("login.off")}
                </span>
              </div>
            </div>
          </div>
        </aside>
      </div>

      <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("settings.deleteTitle")}</AlertDialogTitle>
            <AlertDialogDescription asChild>
              <div className="flex flex-col gap-3">
                <p>{t("settings.deleteDesc")}</p>
                <p>
                  {t("settings.deleteTypePrefix")}{" "}
                  <code className="bg-destructive/10 text-destructive rounded-md px-1.5 py-0.5 font-mono text-xs font-semibold">
                    {user?.username}
                  </code>{" "}
                  {t("common.typeToConfirmSuffix")}
                </p>
                <Input value={confirmText} onChange={(e) => setConfirmText(e.target.value)} placeholder={user?.username ?? ""} autoFocus />
              </div>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("common.cancel")}</AlertDialogCancel>
            <AlertDialogAction
              disabled={confirmText !== user?.username || deleting}
              onClick={(e) => {
                e.preventDefault();
                void doDelete();
              }}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {deleting ? t("common.deleting") : t("settings.deleteForever")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
