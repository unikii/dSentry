import { createContext } from "react";
import type { Locale } from "@/i18n/locales";
import type { Messages } from "@/i18n/dictionaries";
import type { Vars } from "@/i18n/translate";

export type MessageKey = keyof Messages;

export interface LangContextValue {
  lang: Locale;
  setLang: (lang: Locale) => void;
  /** Translate a key with optional `{placeholder}` vars and `count` plural selection. */
  t: (key: MessageKey, vars?: Vars) => string;
}

export const LangContext = createContext<LangContextValue>({
  lang: "en",
  setLang: () => {},
  t: (key) => key,
});
