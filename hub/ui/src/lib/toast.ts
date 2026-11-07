import { toast } from "sonner";
import { ApiError } from "@/lib/api";
import { dictionaries, getCurrentLocale, translate } from "@/i18n";

/** Default fallback in the active locale (English when missing). */
function defaultFallback(): string {
  return translate(dictionaries[getCurrentLocale()], "common.error") ?? "Something went wrong";
}

/** Toast an API failure; `notify=true` failures stay on screen longer. */
export function toastError(e: unknown, fallback?: string) {
  fallback ??= defaultFallback();
  if (e instanceof ApiError) {
    toast.error(e.message || fallback, e.notify ? { duration: 10_000 } : undefined);
  } else if (e instanceof Error) {
    toast.error(e.message || fallback);
  } else {
    toast.error(fallback);
  }
}

export function toastOk(message: string) {
  toast.success(message);
}
