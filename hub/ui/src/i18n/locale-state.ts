import { DEFAULT_LOCALE, type Locale } from "./locales";

/**
 * Module-level current locale for non-component code (e.g. date/relative
 * formatting in lib/format.ts) that cannot use the React hook. The
 * LanguageProvider keeps this in sync; defaults to English.
 */
let currentLocale: Locale = DEFAULT_LOCALE;

export function setCurrentLocale(locale: Locale): void {
  currentLocale = locale;
}

export function getCurrentLocale(): Locale {
  return currentLocale;
}
