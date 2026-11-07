import { dictionaries, en, getCurrentLocale, translate, type Locale, type Vars } from "@/i18n";

function locale(): Locale {
  return getCurrentLocale();
}

type TimeKey =
  | "time.never"
  | "time.justNow"
  | "time.pastAffix"
  | "time.futureAffix"
  | "time.patternPast"
  | "time.patternFuture"
  | "time.unitMin"
  | "time.unitHour"
  | "time.unitDay"
  | "time.unitMonth"
  | "time.unitYear";

/** Relative-time fragment in the active locale, with English fallback. */
function timeWord(key: TimeKey, vars?: Vars): string {
  return (
    translate(dictionaries[locale()], key, vars) ?? translate(en, key, vars) ?? key
  );
}

/** SQLite datetimes are UTC ("YYYY-MM-DD HH:MM:SS"); parse them correctly. */
export function parseUTC(ts?: string | null): Date | null {
  if (!ts) return null;
  const normalized = ts.includes("T") ? ts : ts.replace(" ", "T");
  const withZone = /Z|[+-]\d{2}:?\d{2}$/.test(normalized) ? normalized : `${normalized}Z`;
  const d = new Date(withZone);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function formatDateTime(ts?: string | null): string {
  const d = parseUTC(ts);
  if (!d) return "—";
  return d.toLocaleString(locale(), {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatDate(ts?: string | null): string {
  const d = parseUTC(ts);
  if (!d) return "—";
  return d.toLocaleDateString(locale(), { year: "numeric", month: "short", day: "numeric" });
}

export function formatRelative(ts?: string | null): string {
  const d = parseUTC(ts);
  if (!d) return timeWord("time.never");
  const diff = Date.now() - d.getTime();
  const abs = Math.abs(diff);
  const past = diff >= 0;
  const mins = Math.floor(abs / 60_000);
  if (mins < 1) return timeWord("time.justNow");

  let value: number;
  let unitKey: TimeKey;
  if (mins < 60) {
    value = mins;
    unitKey = "time.unitMin";
  } else {
    const hours = Math.floor(mins / 60);
    if (hours < 24) {
      value = hours;
      unitKey = "time.unitHour";
    } else {
      const days = Math.floor(hours / 24);
      if (days < 30) {
        value = days;
        unitKey = "time.unitDay";
      } else {
        const months = Math.floor(days / 30);
        if (months < 12) {
          value = months;
          unitKey = "time.unitMonth";
        } else {
          value = Math.floor(months / 12);
          unitKey = "time.unitYear";
        }
      }
    }
  }

  // Affix placement differs per language ("5m ago" vs "5分钟前" vs
  // "hace 5 min"), so each locale owns its assembly pattern.
  return timeWord(past ? "time.patternPast" : "time.patternFuture", {
    v: value,
    u: timeWord(unitKey, { count: value }),
    a: timeWord(past ? "time.pastAffix" : "time.futureAffix"),
  });
}

export function formatBytes(bytes?: number | null, digits = 1): string {
  if (bytes === null || bytes === undefined || Number.isNaN(bytes)) return "—";
  if (bytes === 0) return "0 B";
  const k = 1024;
  const units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB", "EiB"];
  const i = Math.min(Math.floor(Math.log(Math.abs(bytes)) / Math.log(k)), units.length - 1);
  const v = bytes / k ** i;
  const fixed = v >= 100 || i === 0 || Number.isInteger(v) ? 0 : digits;
  return `${v.toFixed(fixed)} ${units[i]}`;
}

export function formatSiBytes(bytes?: number | null, digits = 1): string {
  if (bytes === null || bytes === undefined || Number.isNaN(bytes)) return "—";
  if (bytes === 0) return "0 B";
  const k = 1000;
  const units = ["B", "KB", "MB", "GB", "TB", "PB", "EB"];
  const i = Math.min(Math.floor(Math.log(Math.abs(bytes)) / Math.log(k)), units.length - 1);
  const v = bytes / k ** i;
  const fixed = v >= 100 || i === 0 || Number.isInteger(v) ? 0 : digits;
  return `${v.toFixed(fixed)} ${units[i]}`;
}

export function formatSpeed(bytesPerSec?: number | null): string {
  if (bytesPerSec === null || bytesPerSec === undefined) return "—";
  return `${formatBytes(bytesPerSec)}/s`;
}

export function formatNumber(n?: number | null): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return n.toLocaleString(locale());
}
