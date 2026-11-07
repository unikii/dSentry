import { useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { AlertCircle, ArrowRight, Globe, KeyRound, Loader2, Moon, ShieldCheck, Sun, User } from "lucide-react";
import { login } from "@/client";
import { LogoMark } from "@/components/Logo";
import { GithubIcon } from "@/components/GithubIcon";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/context/use-auth";
import { useEnvs } from "@/context/use-envs";
import { useLanguage } from "@/context/use-lang";
import { useTheme } from "@/context/use-theme";
import { API_BASE, GITHUB_URL, unwrap } from "@/lib/api";
import { toastError } from "@/lib/toast";
import { cn } from "@/lib/utils";

function GoogleIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden>
      <path
        fill="currentColor"
        d="M21.35 11.1h-9.17v2.73h6.51c-.33 3.81-3.5 5.44-6.5 5.44C8.36 19.27 5 16.25 5 12c0-4.1 3.2-7.27 7.2-7.27c3.09 0 4.9 1.97 4.9 1.97L19 4.72S16.56 2 12.1 2C6.42 2 2.03 6.8 2.03 12c0 5.05 4.13 10 10.22 10c5.35 0 9.25-3.67 9.25-9.09c0-1.15-.15-1.81-.15-1.81Z"
      />
    </svg>
  );
}

function oauthLoginUrl(provider: "github" | "google"): string {
  const base = API_BASE.startsWith("http") ? API_BASE : `${globalThis.location.origin}${API_BASE}`;
  const redirectUri = `${globalThis.location.origin}/oauth/callback/${provider}`;
  return `${base}/oauth/providers/${provider}/login?redirect_uri=${encodeURIComponent(redirectUri)}`;
}

function EnvFact({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className="border-border/55 bg-card/35 rounded-xl border p-3 backdrop-blur-sm">
      <p className="mono-label text-muted-foreground/65">{label}</p>
      <p className={cn("mt-1 font-mono text-[12px] font-medium tracking-tight", accent && "text-primary")}>{value}</p>
    </div>
  );
}

function Radar() {
  return (
    <div className="relative mx-auto aspect-square w-full max-w-[390px]" aria-hidden>
      <div className="border-primary/10 absolute inset-0 rounded-full border" />
      <div className="border-border/50 absolute inset-[11%] rounded-full border border-dashed" />
      <div className="border-primary/15 absolute inset-[26%] rounded-full border" />
      <div className="border-border/60 absolute inset-[41%] rounded-full border" />
      <div className="radar-sweep absolute inset-[6%] rounded-full opacity-60" />
      <div className="bg-primary/10 absolute inset-[30%] rounded-full blur-3xl" />

      <div className="border-primary/20 bg-background/60 absolute inset-[35%] flex items-center justify-center rounded-full border shadow-[inset_0_1px_0_0_oklch(1_0_0/0.08),0_30px_90px_-45px_var(--primary)] backdrop-blur-xl">
        <LogoMark className="size-[38%]" />
      </div>

      <span className="bg-primary absolute top-[18%] left-[26%] size-1.5 rounded-full shadow-[0_0_12px_var(--primary)]" />
      <span className="bg-success absolute top-[33%] right-[12%] size-1.5 rounded-full shadow-[0_0_12px_var(--success)]" />
      <span className="bg-info absolute bottom-[21%] left-[13%] size-1.5 rounded-full shadow-[0_0_12px_var(--info)]" />
      <span className="bg-warning absolute right-[28%] bottom-[12%] size-1.5 rounded-full shadow-[0_0_12px_var(--warning)]" />
      <span className="bg-primary/70 radar-ping absolute top-[18%] left-[26%] size-6 rounded-full" />

      <div className="border-border/60 bg-card/60 absolute top-[16%] right-0 flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-mono text-[9px] tracking-[0.14em] text-muted-foreground uppercase backdrop-blur-md">
        <span className="status-dot text-success" /> SMART · 24/7
      </div>
      <div className="border-border/60 bg-card/60 text-muted-foreground absolute bottom-[18%] left-0 rounded-full border px-2.5 py-1 font-mono text-[9px] tracking-[0.14em] uppercase backdrop-blur-md">
        SATA · NVMe · SAS
      </div>
    </div>
  );
}

export function LoginPage() {
  const { t } = useLanguage();
  const { envs, loading: envsLoading } = useEnvs();
  const { signIn } = useAuth();
  const { resolved, setTheme } = useTheme();
  const navigate = useNavigate();
  const location = useLocation();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const from = (location.state as { from?: string } | null)?.from ?? "/devices";

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const res = await unwrap(
        login({ body: { username: username || undefined, password: password || undefined } }),
      );
      signIn(res.token, res.user);
      navigate(from, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : t("login.signInFailed"));
      toastError(err, t("login.signInFailed"));
    } finally {
      setSubmitting(false);
    }
  };

  if (envsLoading) {
    return (
      <div className="bg-background relative flex min-h-dvh items-center justify-center">
        <div className="app-aurora pointer-events-none absolute inset-0" />
        <div className="relative flex flex-col items-center gap-4">
          <LogoMark className="size-14" />
          <Loader2 className="text-muted-foreground size-5 animate-spin" />
        </div>
      </div>
    );
  }

  const isPrivate = envs?.run_mode !== "public";

  return (
    <div className="bg-background relative min-h-dvh overflow-hidden">
      <div className="app-aurora pointer-events-none fixed inset-0" aria-hidden />
      <div className="bg-grid-faint pointer-events-none fixed inset-0" aria-hidden />

      <div className="relative mx-auto flex min-h-dvh w-full max-w-[1500px] flex-col lg:grid lg:grid-cols-[minmax(0,1.05fr)_minmax(420px,0.95fr)] lg:px-6">
        {/* ------------------------------- Brand / hero ------------------------------- */}
        <section className="relative hidden flex-col justify-between px-10 py-10 lg:flex xl:px-14">
          <div className="flex items-center gap-3">
            <span className="border-primary/20 bg-primary/[0.08] flex size-11 items-center justify-center rounded-xl border shadow-[inset_0_1px_0_0_oklch(1_0_0/0.08)]">
              <LogoMark className="size-8" />
            </span>
            <span>
              <span className="font-display block text-lg leading-none font-semibold tracking-[-0.02em]">dSentry</span>
              <span className="mono-label text-muted-foreground mt-1 block text-[9px] tracking-[0.2em]">
                {t("login.subtitle")}
              </span>
            </span>
          </div>

          <div className="animate-rise max-w-[560px]">
            <div className="mb-5 flex items-center gap-2">
              <span className="from-primary h-px w-8 bg-gradient-to-r to-transparent" />
              <span className="mono-label text-primary/80">{t("login.heroKicker")}</span>
            </div>
            <h1 className="font-display text-5xl leading-[1.03] font-semibold tracking-[-0.055em] xl:text-[58px]">
              {t("login.heroTitle")}
            </h1>
            <p className="text-muted-foreground mt-5 max-w-[490px] text-[14px] leading-relaxed">{t("login.heroDesc")}</p>

            <div className="mt-8">
              <Radar />
            </div>
          </div>

          <div className="text-muted-foreground flex items-center justify-between gap-4 border-t border-border/50 pt-5 text-[11px]">
            <span className="flex items-center gap-2">
              <ShieldCheck className="text-success size-4" />
              {t("login.selfHosted")}
            </span>
            <span className="font-mono text-[9px] tracking-[0.16em] uppercase">dSentry / {t("login.subtitle")}</span>
          </div>
        </section>

        {/* --------------------------------- Sign-in --------------------------------- */}
        <section className="relative flex flex-1 flex-col px-4 py-5 sm:px-6 lg:py-8">
          <div className="flex items-center justify-between lg:justify-end">
            <div className="flex items-center gap-2.5 lg:hidden">
              <span className="border-primary/20 bg-primary/[0.08] flex size-9 items-center justify-center rounded-lg border">
                <LogoMark className="size-6" />
              </span>
              <span>
                <span className="font-display block text-[15px] leading-none font-semibold tracking-[-0.02em]">dSentry</span>
                <span className="mono-label text-muted-foreground mt-1 block text-[8px] tracking-[0.18em]">
                  {t("login.subtitle")}
                </span>
              </span>
            </div>
            <div className="flex items-center gap-1">
              <Button variant="ghost" size="icon" asChild>
                <a
                  href={GITHUB_URL}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label={t("misc.githubRepo")}
                  title={t("misc.githubRepo")}
                >
                  <GithubIcon className="size-4" />
                </a>
              </Button>
              <Button
                variant="ghost"
                size="icon"
                aria-label={t("login.toggleTheme")}
                onClick={() => setTheme(resolved === "dark" ? "light" : "dark")}
              >
                {resolved === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
              </Button>
            </div>
          </div>

          {envs?.login_notify_banner && (
            <div className="border-primary/20 bg-primary/[0.08] text-primary mx-auto mt-4 flex w-full max-w-md items-center gap-2 rounded-xl border px-3.5 py-2.5 text-xs font-medium backdrop-blur-sm">
              <AlertCircle className="size-4 shrink-0" />
              <span>{envs.login_notify_banner}</span>
            </div>
          )}

          <div className="mx-auto flex w-full max-w-[410px] flex-1 flex-col justify-center py-8">
            <div className="panel-strong relative overflow-hidden p-6 sm:p-7">
              <div className="pointer-events-none absolute -top-28 -right-24 size-64 rounded-full bg-primary/[0.08] blur-3xl" aria-hidden />
              <div className="relative">
                <div className="mb-6">
                  <div className="mb-3 flex items-center gap-2">
                    <span className="status-dot text-success" />
                    <span className="mono-label text-muted-foreground/70">
                      {isPrivate ? t("login.modePrivate") : t("login.modePublic")}
                    </span>
                  </div>
                  <h2 className="font-display text-[26px] leading-none font-semibold tracking-[-0.04em]">
                    {isPrivate ? t("login.signIn") : t("login.welcome")}
                  </h2>
                  <p className="text-muted-foreground mt-2 text-[12px] leading-relaxed">
                    {isPrivate ? t("login.privateDesc") : t("login.publicDesc")}
                  </p>
                </div>

                {!isPrivate && (
                  <div className="grid gap-2.5">
                    <Button variant="outline" className="h-11 w-full justify-start" onClick={() => (globalThis.location.href = oauthLoginUrl("github"))}>
                      <GithubIcon className="size-4" />
                      {t("login.continueGithub")}
                    </Button>
                    <Button variant="outline" className="h-11 w-full justify-start" onClick={() => (globalThis.location.href = oauthLoginUrl("google"))}>
                      <GoogleIcon className="size-4" />
                      {t("login.continueGoogle")}
                    </Button>
                  </div>
                )}

                {isPrivate && (
                  <form onSubmit={submit} className="flex flex-col gap-4">
                    <div className="grid gap-1.5">
                      <Label htmlFor="username">{t("login.username")}</Label>
                      <div className="relative">
                        <User className="text-muted-foreground/70 absolute top-1/2 left-3 size-4 -translate-y-1/2" />
                        <Input
                          id="username"
                          autoComplete="username"
                          value={username}
                          onChange={(e) => setUsername(e.target.value)}
                          className="h-11 pl-9"
                          placeholder={t("login.usernameAdminPh")}
                        />
                      </div>
                    </div>
                    <div className="grid gap-1.5">
                      <Label htmlFor="password">{t("login.password")}</Label>
                      <div className="relative">
                        <KeyRound className="text-muted-foreground/70 absolute top-1/2 left-3 size-4 -translate-y-1/2" />
                        <Input
                          id="password"
                          type="password"
                          autoComplete="current-password"
                          value={password}
                          onChange={(e) => setPassword(e.target.value)}
                          className="h-11 pl-9"
                          placeholder={t("login.passwordEmptyPh")}
                        />
                      </div>
                    </div>

                    {error && (
                      <p className="border-destructive/25 bg-destructive/[0.07] text-destructive flex items-start gap-2 rounded-lg border px-3 py-2 text-xs">
                        <AlertCircle className="mt-px size-3.5 shrink-0" /> {error}
                      </p>
                    )}

                    <Button type="submit" disabled={submitting} className="mt-1 h-11 w-full justify-between px-4">
                      <span className="flex items-center gap-2">
                        {submitting ? <Loader2 className="size-4 animate-spin" /> : <ArrowRight className="size-4" />}
                        {t("login.signIn")}
                      </span>
                      <span className="font-mono text-[9px] tracking-[0.14em] opacity-50">ENTER</span>
                    </Button>
                  </form>
                )}
              </div>
            </div>

            {envs && (
              <div className="mt-5">
                <p className="mono-label text-muted-foreground/65 mb-2.5 flex items-center gap-1.5">
                  <Globe className="size-3" /> {t("login.server")}
                </p>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                  <EnvFact
                    label={t("login.mode")}
                    value={envs.run_mode === "public" ? t("login.modePublic") : t("login.modePrivate")}
                    accent
                  />
                  <EnvFact label={t("login.pushInterval")} value={t("login.minutes", { n: envs.global_push_interval })} />
                  <EnvFact
                    label={t("login.dataKept")}
                    value={envs.metrics_data_lifespan.toLowerCase() === "forever" ? t("login.forever") : envs.metrics_data_lifespan}
                  />
                  <EnvFact label={t("login.nodesPerUser")} value={String(envs.global_node_per_user)} />
                  <EnvFact label={t("login.devicesPerNode")} value={String(envs.global_device_per_node)} />
                  <EnvFact label={t("login.emailNotify")} value={envs.smtp_enabled ? t("login.available") : t("login.off")} />
                </div>
                <p className="text-muted-foreground/45 mt-4 text-center text-[10px] lg:hidden">{t("login.selfHosted")}</p>
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
