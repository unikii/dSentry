import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { getEnvs } from "@/client";
import { EnvsContext, type ServerEnvs } from "@/context/envs-context";
import { unwrap } from "@/lib/api";

const ENVS_KEY = "dsentry.envs";
const ENVS_TTL_MS = 24 * 60 * 60 * 1000; // re-request at most once a day

interface CachedEnvs {
  at: number;
  envs: ServerEnvs;
}

function loadCached(): CachedEnvs | null {
  try {
    const raw = localStorage.getItem(ENVS_KEY);
    return raw ? (JSON.parse(raw) as CachedEnvs) : null;
  } catch {
    return null;
  }
}

export function EnvsProvider({ children }: { children: ReactNode }) {
  const [cached] = useState<CachedEnvs | null>(loadCached);
  const [envs, setEnvs] = useState<ServerEnvs | null>(cached?.envs ?? null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const e = await unwrap(getEnvs());
      localStorage.setItem(ENVS_KEY, JSON.stringify({ at: Date.now(), envs: e } satisfies CachedEnvs));
      setEnvs(e);
      return e;
    } catch {
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const c = cached;
    if (c && Date.now() - c.at < ENVS_TTL_MS) {
      setEnvs(c.envs);
      setLoading(false);
      // background refresh anyway, but don't block on it
      void refresh();
    } else {
      void refresh();
    }
  }, [cached, refresh]);

  const value = useMemo(() => ({ envs, loading, refresh }), [envs, loading, refresh]);
  return <EnvsContext.Provider value={value}>{children}</EnvsContext.Provider>;
}
