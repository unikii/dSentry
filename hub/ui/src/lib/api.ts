import { client } from "@/client/client.gen";

export const TOKEN_KEY = "dsentry.token";
export const USER_KEY = "dsentry.user";

/** Base URL for API requests. In dev, vite proxies /api -> the hub; in docker, nginx does. */
export const API_BASE: string = import.meta.env.VITE_API_BASE ?? "/api";

/** Join a base URL and a path without producing `hosthttps://...` or `//`. */
export function joinUrl(base: string, path: string): string {
  if (/^https?:\/\//i.test(path)) return path.replace(/\/+$/, "");
  if (!base) return path;
  return `${base.replace(/\/+$/, "")}/${path.replace(/^\/+/, "")}`.replace(/\/+$/, "");
}

/** Public endpoint shown to users in the dsnode install command. */
export const API_ENDPOINT: string =
  (import.meta.env.VITE_API_ENDPOINT ?? "").trim() ||
  joinUrl(globalThis.location?.origin ?? "", API_BASE);

/** GitHub repo used by the one-line dsnode installers shown in the UI. */
export const GITHUB_REPO: string = import.meta.env.VITE_GITHUB_REPO || "unikii/dsentry";

/** Repository URL shown in the UI (login page and navigation). */
export const GITHUB_URL: string = `https://github.com/${GITHUB_REPO}`;

client.setConfig({ baseUrl: API_BASE });

client.interceptors.request.use((request) => {
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) {
    request.headers.set("Authorization", `Bearer ${token}`);
  }
  return request;
});

export const UNAUTHORIZED_EVENT = "dsentry:unauthorized";

export class ApiError extends Error {
  status: number;
  notify: boolean;
  httpStatus?: number;

  constructor(message: string, status = 1, notify = false, httpStatus?: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.notify = notify;
    this.httpStatus = httpStatus;
  }
}

/** One generated SDK call: resolves to { data, error, response } fields. */
export type SdkResult<Envelope = unknown> = Promise<{
  data?: Envelope | undefined;
  error?: unknown;
  response?: Response;
}>;

/**
 * Extract the payload type from a generated envelope type, so unwrap() is
 * linked to the endpoint's declared schema: `unwrap(listDevices(...))`
 * returns the payload type openapi.json declares for GET /devices, and a
 * spec/backend mismatch surfaces as a compile error at the call site.
 */
export type PayloadOf<Envelope> =
  Envelope extends { payload?: infer P | null } ? NonNullable<P> : never;

interface EnvelopeShape {
  status: number;
  message?: string;
  notify?: boolean;
  payload?: unknown;
}

/**
 * Unwrap the uniform APIResponse envelope.
 * status=0 -> payload, anything else -> ApiError.
 *
 * Two forms:
 *  - `unwrap(sdkCall(...))` infers the payload type from the generated
 *    client, keeping call sites compile-time checked against openapi.json.
 *  - `unwrap<T>(promise)` asserts T explicitly — only for endpoints whose
 *    response the spec leaves untyped (e.g. /envs).
 */
export async function unwrap<Envelope>(p: SdkResult<Envelope>): Promise<PayloadOf<Envelope>>;
export async function unwrap<T>(p: SdkResult): Promise<T>;
export async function unwrap<T>(p: SdkResult): Promise<PayloadOf<T> | T> {
  let result: { data?: unknown; error?: unknown; response?: Response };
  try {
    result = await p;
  } catch (e) {
    throw new ApiError(e instanceof Error ? e.message : "Network error", 1);
  }

  const { data, error, response } = result;
  const body = (data ?? error) as EnvelopeShape | undefined;

  if (response?.status === 401) {
    globalThis.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT));
    throw new ApiError(body?.message || "Unauthorized", body?.status ?? 1, body?.notify ?? false, 401);
  }

  if (!body || typeof body.status !== "number") {
    if (response && !response.ok) {
      throw new ApiError(`Request failed (HTTP ${response.status})`, 1, false, response.status);
    }
    throw new ApiError("Invalid server response", 1);
  }

  if (body.status !== 0) {
    throw new ApiError(body.message || "Request failed", body.status, body.notify ?? false, response?.status);
  }

  return body.payload as PayloadOf<T> | T;
}

/**
 * Dedupe concurrent identical fetches: concurrent callers share one
 * in-flight promise, which is dropped from the cache on settle.
 */
export function dedupeRequest<K, V>(cache: Map<K, Promise<V>>, key: K, create: () => Promise<V>): Promise<V> {
  const existing = cache.get(key);
  if (existing) return existing;
  const request = create();
  cache.set(key, request);
  const cleanup = () => {
    if (cache.get(key) === request) cache.delete(key);
  };
  request.then(cleanup, cleanup);
  return request;
}
