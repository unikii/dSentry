export type Locale = "en" | "zh-CN" | "zh-TW" | "es";

export const DEFAULT_LOCALE: Locale = "en";

export const LOCALES: { value: Locale; label: string }[] = [
  { value: "en", label: "English" },
  { value: "zh-CN", label: "简体中文" },
  { value: "zh-TW", label: "繁體中文" },
  { value: "es", label: "Español" },
];

export function isLocale(value: string | null | undefined): value is Locale {
  return value === "en" || value === "zh-CN" || value === "zh-TW" || value === "es";
}

/** Best-effort match of a BCP 47 tag (e.g. navigator.language) to a supported locale. */
export function matchLocale(tag: string | null | undefined): Locale | null {
  if (!tag) return null;
  const lower = tag.toLowerCase();
  if (lower.startsWith("zh")) {
    // zh-TW, zh-HK, zh-MO, zh-Hant → Traditional; everything else → Simplified.
    if (/tw|hk|mo|hant/.test(lower)) return "zh-TW";
    return "zh-CN";
  }
  if (lower.startsWith("es")) return "es";
  if (lower.startsWith("en")) return "en";
  return null;
}
