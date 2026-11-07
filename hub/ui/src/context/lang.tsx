import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { LangContext, type MessageKey } from "@/context/lang-context";
import {
  DEFAULT_LOCALE,
  dictionaries,
  en,
  isLocale,
  matchLocale,
  setCurrentLocale,
  translate,
  type Locale,
  type Vars,
} from "@/i18n";

const LANG_KEY = "dsentry.lang";

function initialLang(): Locale {
  const saved = localStorage.getItem(LANG_KEY);
  if (isLocale(saved)) return saved;
  return matchLocale(navigator.language) ?? DEFAULT_LOCALE;
}

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Locale>(initialLang);

  useEffect(() => {
    setCurrentLocale(lang);
    document.documentElement.lang = lang;
  }, [lang]);

  const setLang = useCallback((next: Locale) => {
    localStorage.setItem(LANG_KEY, next);
    setLangState(next);
  }, []);

  const t = useCallback(
    (key: MessageKey, vars?: Vars) =>
      translate(dictionaries[lang], key, vars) ?? translate(en, key, vars) ?? key,
    [lang],
  );

  const value = useMemo(() => ({ lang, setLang, t }), [lang, setLang, t]);

  return <LangContext.Provider value={value}>{children}</LangContext.Provider>;
}
