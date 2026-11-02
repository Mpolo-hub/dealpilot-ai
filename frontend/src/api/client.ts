// One fetch wrapper for the spec 002 API. Requests always go to the page's own origin
// (spec 007 D9: the Vite proxy forwards `/v1` and `/health`), so the API needs no CORS.

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

/** The API could not be reached at all (not running, or the proxy failed). */
export class NetworkError extends Error {
  constructor() {
    super("network error");
    this.name = "NetworkError";
  }
}

export type QueryValue = string | string[] | undefined;

/** Repeated keys for lists (spec 002 section 3.4); undefined and empty lists are left out. */
export function buildQuery(params: Record<string, QueryValue>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined) continue;
    for (const item of Array.isArray(value) ? value : [value]) search.append(key, item);
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

function errorFrom(status: number, body: unknown): ApiError {
  const error = (body as { error?: { code?: unknown; message?: unknown } } | null)?.error;
  const code = typeof error?.code === "string" ? error.code : `http_${status}`;
  const message = typeof error?.message === "string" ? error.message : "";
  return new ApiError(status, code, message);
}

export async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  if (!path.startsWith("/")) throw new Error("API paths must be same-origin paths");
  let response: Response;
  try {
    response = await fetch(path, { signal, headers: { Accept: "application/json" } });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new NetworkError();
  }
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (!response.ok) {
    // A proxy with no API behind it answers 5xx without the spec 002 body.
    if (body === null && response.status >= 500) throw new NetworkError();
    throw errorFrom(response.status, body);
  }
  return body as T;
}
