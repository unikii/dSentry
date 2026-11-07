import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  Activity,
  Bell,
  ChevronRight,
  HardDrive,
  LogOut,
  Moon,
  PanelLeftClose,
  PanelRightClose,
  Server,
  Settings,
  Sun,
} from "lucide-react";
import { useAuth } from "@/context/use-auth";
import { usePrefs } from "@/context/use-prefs";
import { useLanguage } from "@/context/use-lang";
import { useEnvs } from "@/context/use-envs";
import { useTheme } from "@/context/use-theme";
import type { MessageKey } from "@/context/lang-context";
import { LogoMark } from "@/components/Logo";
import { GithubIcon } from "@/components/GithubIcon";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { GITHUB_URL } from "@/lib/api";
import { useNow } from "@/lib/use-now";
import { cn } from "@/lib/utils";

const NAV_ITEMS: { to: string; labelKey: MessageKey; icon: typeof HardDrive }[] = [
  { to: "/devices", labelKey: "nav.devices", icon: HardDrive },
  { to: "/nodes", labelKey: "nav.nodes", icon: Server },
  { to: "/events", labelKey: "nav.events", icon: Activity },
  { to: "/alerts", labelKey: "nav.alerts", icon: Bell },
  { to: "/settings", labelKey: "nav.settings", icon: Settings },
];

const SECTION_KEYS: Record<string, MessageKey> = {
  devices: "nav.devices",
  nodes: "nav.nodes",
  events: "nav.events",
  alerts: "nav.alerts",
  settings: "nav.settings",
};

function Logo({ slim }: { slim: boolean }) {
  const { t } = useLanguage();
  return (
    <div className={cn("flex items-center gap-3", slim && "justify-center")}>
      <span className="relative flex size-10 shrink-0 items-center justify-center rounded-xl border border-primary/20 bg-primary/[0.08] shadow-[inset_0_1px_0_0_oklch(1_0_0/0.08),0_10px_30px_-18px_var(--primary)]">
        <LogoMark className="size-7" />
        <span className="bg-primary absolute -right-0.5 -bottom-0.5 size-2 rounded-full ring-2 ring-card" />
      </span>
      {!slim && (
        <span className="min-w-0 leading-tight">
          <span className="font-display block text-[17px] font-semibold tracking-[-0.02em]">dSentry</span>
          <span className="mono-label text-muted-foreground mt-0.5 block text-[9px] tracking-[0.2em]">
            {t("misc.appTagline")}
          </span>
        </span>
      )}
    </div>
  );
}

function SidebarIconButton({
  label,
  children,
  onClick,
  href,
}: {
  label: string;
  children: React.ReactNode;
  onClick?: () => void;
  href?: string;
}) {
  const cls =
    "text-muted-foreground hover:bg-accent/70 hover:text-foreground flex size-9 cursor-pointer items-center justify-center rounded-lg transition-colors";
  const button = href ? (
    <a href={href} target="_blank" rel="noopener noreferrer" aria-label={label} className={cls}>
      {children}
    </a>
  ) : (
    <button type="button" onClick={onClick} aria-label={label} className={cls}>
      {children}
    </button>
  );

  return (
    <Tooltip>
      <TooltipTrigger asChild>{button}</TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}

function NavColumn() {
  const { navSide, navSlim, setNavSlim } = usePrefs();
  const { signOut, user } = useAuth();
  const { envs } = useEnvs();
  const { resolved, setTheme } = useTheme();
  const { t } = useLanguage();
  const navigate = useNavigate();
  const slim = navSlim;
  const iconSide = navSide === "right" ? "left" : "right";

  const logout = () => {
    signOut();
    navigate("/login", { replace: true });
  };

  const modeLabel = envs?.run_mode === "public" ? t("login.modePublic") : t("login.modePrivate");

  return (
    <aside
      className={cn(
        "panel-strong relative z-20 m-3 hidden h-[calc(100dvh-1.5rem)] shrink-0 flex-col overflow-hidden transition-[width] duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] md:flex",
        slim ? "w-[82px]" : "w-[250px]",
      )}
    >
      <div className="pointer-events-none absolute inset-x-0 top-0 h-44 bg-gradient-to-b from-primary/[0.09] to-transparent" aria-hidden />
      <div className="pointer-events-none absolute -top-16 -left-20 size-52 rounded-full bg-primary/10 blur-3xl" aria-hidden />

      <div className={cn("relative flex items-center px-4 pt-5 pb-4", slim ? "justify-center px-2" : "justify-between")}>
        <Logo slim={slim} />
      </div>

      <div className={cn("mx-3 mb-3", slim && "mx-2")}>
        <div className="hairline" />
      </div>

      <nav className={cn("flex flex-1 flex-col gap-1 px-3", slim && "items-center px-2")} aria-label="Primary">
        {!slim && <p className="mono-label text-muted-foreground/70 mb-1.5 px-2.5">{t("nav.workspace")}</p>}
        {NAV_ITEMS.map(({ to, labelKey, icon: Icon }) => {
          const label = t(labelKey);
          const link = (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                cn(
                  "group text-muted-foreground relative flex h-11 w-full items-center gap-2.5 rounded-xl border border-transparent px-2 text-[13px] font-medium transition-[color,background-color,border-color,box-shadow] duration-200",
                  slim && "w-11 justify-center px-0",
                  isActive
                    ? "border-border/65 bg-card/75 text-foreground shadow-[inset_0_1px_0_0_oklch(1_0_0/0.055),0_8px_24px_-18px_oklch(0_0_0/0.8)]"
                    : "hover:bg-accent/45 hover:text-foreground",
                )
              }
            >
              {({ isActive }) => (
                <>
                  <span
                    className={cn(
                      "bg-primary absolute top-1/2 h-5 w-[2px] -translate-y-1/2 rounded-full opacity-0 shadow-[0_0_12px_var(--primary)] transition-opacity duration-200",
                      navSide === "right" ? "-right-px" : "-left-px",
                      isActive && "opacity-100",
                    )}
                    aria-hidden
                  />
                  <span
                    className={cn(
                      "flex size-8 shrink-0 items-center justify-center rounded-lg border transition-colors duration-200",
                      isActive
                        ? "border-primary/20 bg-primary/[0.12] text-primary"
                        : "group-hover:bg-accent/60 group-hover:text-foreground border-transparent",
                    )}
                  >
                    <Icon className="size-[17px]" strokeWidth={isActive ? 2 : 1.7} />
                  </span>
                  {!slim && <span className="truncate">{label}</span>}
                  {!slim && (
                    <ChevronRight
                      className={cn(
                        "ml-auto size-3.5 -translate-x-1 opacity-0 transition-[opacity,transform] duration-200",
                        isActive && "translate-x-0 opacity-45",
                      )}
                      strokeWidth={1.75}
                    />
                  )}
                </>
              )}
            </NavLink>
          );
          return slim ? (
            <Tooltip key={to}>
              <TooltipTrigger asChild>{link}</TooltipTrigger>
              <TooltipContent side={iconSide}>{label}</TooltipContent>
            </Tooltip>
          ) : (
            link
          );
        })}
      </nav>

      <div className={cn("relative flex flex-col gap-2 p-3", slim && "items-center px-2")}>
        {!slim && (
          <div className="border-border/60 bg-background/25 rounded-2xl border p-3">
            <div className="flex items-center justify-between gap-2">
              <span className="mono-label text-success flex items-center gap-1.5">
                <span className="status-dot" />
                {t("node.online")}
              </span>
              <span className="mono-label text-muted-foreground/70">{modeLabel}</span>
            </div>
            <div className="mt-2.5 flex items-center gap-2.5">
              <span className="from-primary/25 to-primary/5 text-primary border-primary/20 flex size-8 shrink-0 items-center justify-center rounded-full border bg-gradient-to-br text-xs font-semibold">
                {(user?.username ?? "?").slice(0, 1).toUpperCase()}
              </span>
              <span className="min-w-0">
                <span className="block truncate text-[13px] font-medium">{user?.username ?? "—"}</span>
                <span className="text-muted-foreground block truncate text-[11px]">
                  {user?.oauth_provider ? `@${user.oauth_provider}` : t("settings.account")}
                </span>
              </span>
            </div>
          </div>
        )}

        <div className={cn("flex items-center gap-0.5 border-t border-border/50 pt-2", slim ? "flex-col" : "justify-between")}>
          <div className="flex items-center gap-0.5">
            <SidebarIconButton label={t("misc.githubRepo")} href={GITHUB_URL}>
              <GithubIcon className="size-4" />
            </SidebarIconButton>
            <SidebarIconButton
              label={resolved === "dark" ? t("login.toggleTheme") : t("login.toggleTheme")}
              onClick={() => setTheme(resolved === "dark" ? "light" : "dark")}
            >
              {resolved === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
            </SidebarIconButton>
          </div>
          <div className="flex items-center gap-0.5">
            <SidebarIconButton
              label={slim ? t("nav.expandNav") : t("nav.collapseNav")}
              onClick={() => setNavSlim(!slim)}
            >
              {slim ? (
                navSide === "right" ? <PanelLeftClose className="size-4" /> : <PanelRightClose className="size-4" />
              ) : navSide === "right" ? (
                <PanelRightClose className="size-4" />
              ) : (
                <PanelLeftClose className="size-4" />
              )}
            </SidebarIconButton>
            <SidebarIconButton label={t("nav.logout")} onClick={logout}>
              <LogOut className="size-4" />
            </SidebarIconButton>
          </div>
        </div>
      </div>
    </aside>
  );
}

function TopBar() {
  const { t, lang } = useLanguage();
  const { resolved, setTheme } = useTheme();
  const { user, signOut } = useAuth();
  const { envs } = useEnvs();
  const location = useLocation();
  const navigate = useNavigate();
  const now = useNow(30_000);

  const sectionKey = SECTION_KEYS[location.pathname.split("/")[1] ?? ""] ?? "nav.devices";
  const sectionLabel = t(sectionKey);
  const modeLabel = envs?.run_mode === "public" ? t("login.modePublic") : t("login.modePrivate");

  const dateLabel = new Intl.DateTimeFormat(lang, {
    weekday: "short",
    day: "2-digit",
    month: "short",
  })
    .format(now)
    .replace(/,/g, "")
    .toUpperCase();
  const timeLabel = new Intl.DateTimeFormat(lang, { hour: "2-digit", minute: "2-digit", hour12: false }).format(now);

  return (
    <header className="border-border/45 bg-background/55 sticky top-0 z-30 flex h-16 shrink-0 items-center justify-between gap-3 border-b px-4 backdrop-blur-xl sm:px-6 lg:px-8">
      <div className="flex min-w-0 items-center gap-2.5">
        <span className="border-primary/20 bg-primary/[0.08] flex size-8 shrink-0 items-center justify-center rounded-lg border md:hidden">
          <LogoMark className="size-5" />
        </span>
        <span className="text-muted-foreground hidden font-mono text-[11px] tracking-[0.14em] uppercase md:inline">
          dSentry
        </span>
        <ChevronRight className="text-muted-foreground/50 hidden size-3.5 md:block" />
        <span className="truncate text-[13px] font-medium tracking-tight">{sectionLabel}</span>
        <span className="border-border/60 bg-card/40 text-muted-foreground ml-1.5 hidden items-center gap-1.5 rounded-full border px-2.5 py-1 font-mono text-[9px] tracking-[0.14em] uppercase sm:inline-flex">
          <span className="status-dot text-success" />
          {modeLabel}
        </span>
      </div>

      <div className="flex items-center gap-1">
        <span className="text-muted-foreground/80 mr-1 hidden font-mono text-[10px] tracking-[0.12em] lg:inline">
          {dateLabel} <span className="text-border mx-1">/</span> {timeLabel}
        </span>
        <button
          type="button"
          onClick={() => setTheme(resolved === "dark" ? "light" : "dark")}
          aria-label={t("login.toggleTheme")}
          className="text-muted-foreground hover:bg-accent/60 hover:text-foreground flex size-9 cursor-pointer items-center justify-center rounded-lg transition-colors"
        >
          {resolved === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
        </button>
        <a
          href={GITHUB_URL}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={t("misc.githubRepo")}
          className="text-muted-foreground hover:bg-accent/60 hover:text-foreground hidden size-9 items-center justify-center rounded-lg transition-colors sm:flex"
        >
          <GithubIcon className="size-4" />
        </a>
        <button
          type="button"
          onClick={() => {
            signOut();
            navigate("/login", { replace: true });
          }}
          aria-label={t("nav.logout")}
          className="text-muted-foreground hover:bg-destructive/10 hover:text-destructive flex size-9 cursor-pointer items-center justify-center rounded-lg transition-colors md:hidden"
        >
          <LogOut className="size-4" />
        </button>
        <NavLink
          to="/settings"
          className="border-border/60 bg-card/40 hover:border-primary/25 hover:bg-card/70 ml-1 flex items-center gap-2 rounded-full border py-1 pr-3 pl-1 transition-colors"
        >
          <span className="from-primary/25 to-primary/5 text-primary border-primary/20 flex size-7 items-center justify-center rounded-full border bg-gradient-to-br text-[11px] font-semibold">
            {(user?.username ?? "?").slice(0, 1).toUpperCase()}
          </span>
          <span className="hidden max-w-28 truncate text-xs font-medium sm:block">{user?.username ?? "—"}</span>
        </NavLink>
      </div>
    </header>
  );
}

function MobileNav() {
  const { t } = useLanguage();

  return (
    <nav className="panel-strong fixed inset-x-3 bottom-[calc(0.75rem+env(safe-area-inset-bottom))] z-40 flex items-stretch gap-0.5 overflow-hidden rounded-2xl p-1.5 md:hidden">
      {NAV_ITEMS.map(({ to, labelKey, icon: Icon }) => (
        <NavLink
          key={to}
          to={to}
          className={({ isActive }) =>
            cn(
              "text-muted-foreground relative flex flex-1 flex-col items-center gap-1 rounded-xl py-2 font-mono text-[9px] tracking-[0.08em] uppercase transition-colors",
              isActive ? "text-primary bg-primary/[0.09]" : "hover:text-foreground",
            )
          }
        >
          <Icon className="size-[19px]" strokeWidth={1.8} />
          <span className="max-w-full truncate px-0.5">{t(labelKey)}</span>
        </NavLink>
      ))}
    </nav>
  );
}

export function AppLayout() {
  const { navSide } = usePrefs();

  return (
    <div className="bg-background relative flex h-dvh overflow-hidden">
      <div className="app-aurora pointer-events-none fixed inset-0" aria-hidden />
      <div className="bg-grid-faint pointer-events-none fixed inset-0" aria-hidden />

      {navSide === "left" && <NavColumn />}
      <div className="relative z-10 flex min-w-0 flex-1 flex-col">
        <TopBar />
        <main className="scrollbar-thin relative min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-[1480px] px-4 pt-2 pb-[calc(7rem+env(safe-area-inset-bottom))] sm:px-6 md:pb-12 lg:px-8">
            <Outlet />
          </div>
        </main>
      </div>
      {navSide === "right" && <NavColumn />}
      <MobileNav />
    </div>
  );
}
