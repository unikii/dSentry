import type { Locale } from "./locales";
import { en, type Messages } from "./en";
import { zhCN } from "./zhCN";
import { zhTW } from "./zhTW";
import { es } from "./es";

export type { Messages };
export { en };

export const dictionaries: Record<Locale, Messages> = {
  en,
  "zh-CN": zhCN,
  "zh-TW": zhTW,
  es,
};
