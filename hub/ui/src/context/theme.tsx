import { useCallback, useEffect, useState, type ReactNode } from "react";
import { ThemeContext, type Theme } from "@/context/theme-context";

const THEME_KEY = "dsentry.theme";

/**
 * Resolve the OS theme. Falls back to light when the system style cannot
 * be determined (no matchMedia, or no dark preference advertised).
 */
function systemTheme(): "light" | "dark" {
  try {
    return globalThis.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  } catch {
    return "light";
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(() => {
    const saved = localStorage.getItem(THEME_KEY);
    return saved === "light" || saved === "dark" || saved === "system" ? saved : "system";
  });
  const [resolved, setResolved] = useState<"light" | "dark">(() => (theme === "system" ? systemTheme() : theme));

  useEffect(() => {
    const apply = () => {
      const r = theme === "system" ? systemTheme() : theme;
      setResolved(r);
      document.documentElement.classList.toggle("dark", r === "dark");
      document.documentElement.style.colorScheme = r;
    };
    apply();
    if (theme === "system") {
      // matchMedia may not exist in some embedded browsers — without it
      // there is nothing to subscribe to; apply() already fell back to light.
      const mq = globalThis.matchMedia?.("(prefers-color-scheme: dark)");
      if (!mq) return;
      mq.addEventListener("change", apply);
      return () => mq.removeEventListener("change", apply);
    }
  }, [theme]);

  const setTheme = useCallback((t: Theme) => {
    localStorage.setItem(THEME_KEY, t);
    setThemeState(t);
  }, []);

  return <ThemeContext.Provider value={{ theme, resolved, setTheme }}>{children}</ThemeContext.Provider>;
}
