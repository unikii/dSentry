import { useCallback, useMemo, useState, type ReactNode } from "react";
import { PrefsContext, type NavSide } from "@/context/prefs-context";

const SIDE_KEY = "dsentry.nav.side";
const SLIM_KEY = "dsentry.nav.slim";

export function PrefsProvider({ children }: { children: ReactNode }) {
  const [navSide, setNavSideState] = useState<NavSide>(() =>
    localStorage.getItem(SIDE_KEY) === "right" ? "right" : "left",
  );
  const [navSlim, setNavSlimState] = useState<boolean>(() => localStorage.getItem(SLIM_KEY) === "1");

  const setNavSide = useCallback((s: NavSide) => {
    localStorage.setItem(SIDE_KEY, s);
    setNavSideState(s);
  }, []);

  const setNavSlim = useCallback((v: boolean) => {
    localStorage.setItem(SLIM_KEY, v ? "1" : "0");
    setNavSlimState(v);
  }, []);

  const value = useMemo(
    () => ({ navSide, navSlim, setNavSide, setNavSlim }),
    [navSide, navSlim, setNavSide, setNavSlim],
  );

  return <PrefsContext.Provider value={value}>{children}</PrefsContext.Provider>;
}
