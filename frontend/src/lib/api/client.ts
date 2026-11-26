import { config } from "@/lib/config";
import type { ProblemDetails } from "./types";

/** RFC 7807 error surfaced to UI code. */
export class ApiError extends Error {
  readonly status: number;
  readonly problem: ProblemDetails;

  constructor(problem: ProblemDetails) {
    super(problem.detail ?? problem.title);
    this.name = "ApiError";
    this.status = problem.status;
    this.problem = problem;
  }

  /** Field-level validation errors keyed by field name, for mapping onto forms. */
  fieldErrors(): Record<string, string> {
    return Object.fromEntries((this.problem.errors ?? []).map((e) => [e.field, e.message]));
  }
}

type TokenProvider = () => Promise<string | null>;
type HeaderProvider = () => Record<string, string>;

let tokenProvider: TokenProvider = async () => null;
let extraHeaders: HeaderProvider = () => ({});

/** Registered by the auth provider (MSAL in live mode, persona in mock mode). */
export function setTokenProvider(fn: TokenProvider) {
  tokenProvider = fn;
}
export function setExtraHeaders(fn: HeaderProvider) {
  extraHeaders = fn;
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined | null>;
  /** Public endpoints (signed action links) must not send the user's token. */
  anonymous?: boolean;
  signal?: AbortSignal;
}

function buildUrl(path: string, query?: RequestOptions["query"]) {
  const base = config.apiUrl.replace(/\/$/, "");
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(query ?? {})) {
    if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  }
  const q = qs.toString();
  return `${base}${path}${q ? `?${q}` : ""}`;
}

function idempotencyKey() {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export async function apiFetch<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const method = opts.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json", ...extraHeaders() };

  if (!opts.anonymous) {
    const token = await tokenProvider();
    if (token) headers.Authorization = `Bearer ${token}`;
  }
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") headers["Idempotency-Key"] = idempotencyKey();

  let res: Response;
  try {
    res = await fetch(buildUrl(path, opts.query), {
      method,
      headers,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      signal: opts.signal,
    });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw new ApiError({ title: "Network error", status: 0, detail: "Could not reach the Scrum Bot API." });
  }

  if (res.status === 204) return undefined as T;

  const isJson = (res.headers.get("content-type") ?? "").includes("json");
  const payload: unknown = isJson ? await res.json() : await res.text();

  if (!res.ok) {
    const problem: ProblemDetails =
      isJson && payload && typeof payload === "object" && "title" in payload
        ? (payload as ProblemDetails)
        : { title: res.statusText || "Request failed", status: res.status };
    throw new ApiError({ ...problem, status: res.status });
  }
  return payload as T;
}
