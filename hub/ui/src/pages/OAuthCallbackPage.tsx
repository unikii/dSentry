import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { AlertCircle, Loader2 } from "lucide-react";
import { oauthCallback, type LoginResponse } from "@/client";
import { LogoMark } from "@/components/Logo";
import { useLanguage } from "@/context/use-lang";
import { tStatic } from "@/i18n";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuth } from "@/context/use-auth";
import { unwrap } from "@/lib/api";

export function OAuthCallbackPage() {
  const { t } = useLanguage();
  const { provider } = useParams<{ provider: string }>();
  const [params] = useSearchParams();
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;

    const code = params.get("code");
    const state = params.get("state");
    const p = provider ?? "";

    if (!code || !state || !p) {
      setError(tStatic("oauth.missingParams"));
      return;
    }

    const redirectUri = `${globalThis.location.origin}/oauth/callback/${p}`;

    unwrap<LoginResponse>(
      oauthCallback({
        path: { provider: p },
        query: { code, state, redirect_uri: redirectUri },
      }),
    )
      .then((res) => {
        signIn(res.token, res.user);
        navigate("/devices", { replace: true });
      })
      .catch((e) => {
        setError(e instanceof Error ? e.message : tStatic("oauth.failed"));
      });
  }, [params, provider, signIn, navigate]);

  return (
    <div className="bg-background flex min-h-dvh items-center justify-center px-4">
      <Card className="w-full max-w-sm text-center">
        <CardHeader className="items-center">
          <LogoMark className="size-12" />
          <CardTitle>{error ? t("oauth.failedTitle") : t("oauth.completing")}</CardTitle>
          <CardDescription>{error ? null : t("oauth.authenticating", { provider: provider ?? "" })}</CardDescription>
        </CardHeader>
        <CardContent className="flex justify-center pb-8">
          {error ? (
            <div className="flex flex-col items-center gap-4">
              <p className="text-destructive flex items-center gap-1.5 text-sm">
                <AlertCircle className="size-4" /> {error}
              </p>
              <Button asChild variant="outline">
                <Link to="/login">{t("oauth.back")}</Link>
              </Button>
            </div>
          ) : (
            <Loader2 className="text-muted-foreground size-8 animate-spin" />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
