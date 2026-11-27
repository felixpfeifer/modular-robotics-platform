import axios, { type AxiosError } from "axios";

/**
 * The only module that talks HTTP. Everything else goes through the typed
 * endpoint functions in this folder, so tests can replace `get`, `post` and
 * `upload` here and still see the exact path and body each call sends.
 */

const baseURL = import.meta.env.VITE_API_URL || "/";

/** Absolute URL of an API path, for links, `<img>` sources and downloads. */
export function apiUrl(path: string): string {
  return `${baseURL.replace(/\/$/, "")}/${path.replace(/^\//, "")}`;
}

/** WebSocket URL of an API path, using `wss:` when the API is served over HTTPS. */
export function wsUrl(path: string): URL {
  const url = new URL(apiUrl(path), window.location.href);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url;
}

type PathValue = string | number;

/** Builds a path, URL-encoding every interpolated segment: path`/projects/${id}/rename`. */
export function path(strings: TemplateStringsArray, ...values: PathValue[]): string {
  return strings.reduce(
    (out, part, index) =>
      out + part + (index < values.length ? encodeURIComponent(String(values[index])) : ""),
    "",
  );
}

/** Appends a query string, leaving out `undefined` values. */
export function withQuery(
  target: string,
  params: Record<string, PathValue | boolean | undefined>,
): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params))
    if (value !== undefined) query.set(key, String(value));
  const text = query.toString();
  return text ? `${target}?${text}` : target;
}

/** An HTTP or network failure, carrying the backend's own message when it sent one. */
export class ApiError extends Error {
  readonly status?: number;
  readonly data?: unknown;

  constructor(message: string, status?: number, data?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.data = data;
  }
}

/** The backend answers errors as `{ "error": "..." }`; see the exception handlers in server.py. */
function backendMessage(data: unknown): string | undefined {
  if (data && typeof data === "object" && "error" in data) {
    const { error } = data as { error: unknown };
    if (typeof error === "string" && error) return error;
  }
  return undefined;
}

/** The message to show for any thrown value, with a fallback for non-Error throws. */
export function errorMessage(error: unknown, fallback = "Operation failed"): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

const client = axios.create({
  baseURL,
  headers: { Accept: "application/json" },
});

client.interceptors.response.use(undefined, (error: unknown) => {
  if (!axios.isAxiosError(error)) return Promise.reject(error);
  const { response, message } = error as AxiosError;
  return Promise.reject(
    new ApiError(backendMessage(response?.data) ?? message, response?.status, response?.data),
  );
});

export async function get<T>(target: string): Promise<T> {
  return (await client.get<T>(target)).data;
}

/**
 * POSTs JSON. The body defaults to `{}` because the backend rejects writes with
 * an empty body or without `Content-Type: application/json`.
 */
export async function post<T = void>(target: string, body: object = {}): Promise<T> {
  return (await client.post<T>(target, body)).data;
}

/** POSTs a file as the raw request body (ZIP and tar.gz bundles). */
export async function upload<T>(target: string, file: Blob, contentType: string): Promise<T> {
  return (await client.post<T>(target, file, { headers: { "Content-Type": contentType } })).data;
}
