import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { getUser, logout, type UserResponse } from "@/client";
import { AuthContext } from "@/context/auth-context";
import { TOKEN_KEY, UNAUTHORIZED_EVENT, USER_KEY, unwrap } from "@/lib/api";

function loadStoredUser(): UserResponse | null {
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as UserResponse) : null;
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem(TOKEN_KEY));
  const [user, setUser] = useState<UserResponse | null>(loadStoredUser);
  const [ready, setReady] = useState(false);

  const signOut = useCallback(() => {
    const currentToken = localStorage.getItem(TOKEN_KEY);
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    setToken(null);
    setUser(null);
    if (currentToken) {
      // Best effort: revoke the server-side session as well. Use the captured
      // token explicitly because local storage is already cleared.
      void unwrap(
        logout({ headers: { Authorization: `Bearer ${currentToken}` } }),
      ).catch(() => {});
    }
  }, []);

  const signIn = useCallback((t: string, u: UserResponse) => {
    localStorage.setItem(TOKEN_KEY, t);
    localStorage.setItem(USER_KEY, JSON.stringify(u));
    setToken(t);
    setUser(u);
  }, []);

  const refreshUser = useCallback(async () => {
    const uid = loadStoredUser()?.id;
    if (!uid) return;
    try {
      const u = await unwrap(getUser({ path: { user_id: uid } }));
      localStorage.setItem(USER_KEY, JSON.stringify(u));
      setUser(u);
    } catch {
      /* keep stale user */
    }
  }, []);

  useEffect(() => {
    const onUnauthorized = () => signOut();
    globalThis.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => globalThis.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, [signOut]);

  useEffect(() => {
    if (token) {
      void refreshUser().finally(() => setReady(true));
    } else {
      setReady(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const value = useMemo(
    () => ({ token, user, ready, signIn, signOut, refreshUser }),
    [token, user, ready, signIn, signOut, refreshUser],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
