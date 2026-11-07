/** A dictionary entry: plain string, or singular/plural pair selected by `count`. */
export type Entry = string | { one: string; other: string };

export type Vars = Record<string, string | number | null | undefined>;

import { dictionaries, en } from "./dictionaries";
import { getCurrentLocale } from "./locale-state";

/**
 * Translate outside React render (fetch callbacks, effects): resolves the
 * key against the *current* module locale with English fallback, so async
 * code never needs the `t` hook in its dependency list.
 */
export function tStatic(key: string, vars?: Vars): string {
  const messages = dictionaries[getCurrentLocale()];
  return translate(messages, key, vars) ?? translate(en, key, vars) ?? key;
}

/** Look up a dotted key and interpolate `{placeholders}`. Returns undefined when missing. */
export function translate(
  messages: Record<string, Entry>,
  key: string,
  vars?: Vars,
): string | undefined {
  const entry = messages[key];
  if (entry === undefined) return undefined;
  const template = typeof entry === "string" ? entry : vars?.count === 1 ? entry.one : entry.other;
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (_, name: string) => {
    const value = vars[name];
    return value === null || value === undefined ? "" : String(value);
  });
}
