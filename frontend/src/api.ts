import { idToken } from "./auth";

export class ApiError extends Error {
  status: number;
  code?: string;
  constructor(status: number, message: string, code?: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

type Listener = (e: ApiError) => void;
const limitListeners = new Set<Listener>();
/** Subscribe to plan-limit errors (HTTP 402) so the app can show the upgrade prompt. */
export function onLimit(fn: Listener) {
  limitListeners.add(fn);
  return () => limitListeners.delete(fn);
}

/** Open the upgrade prompt without a server round trip (e.g. the user is already at their book limit). */
export function showLimit(message: string, code = "limit") {
  const err = new ApiError(402, message, code);
  limitListeners.forEach((fn) => fn(err));
}

export async function api<T = any>(path: string, opts: { method?: string; body?: unknown; raw?: boolean } = {}): Promise<T> {
  const token = await idToken();
  const isForm = opts.body instanceof FormData; // files: let the browser set the multipart boundary
  const res = await fetch(`/api${path}`, {
    method: opts.method ?? (opts.body !== undefined ? "POST" : "GET"),
    headers: {
      ...(opts.body !== undefined && !isForm ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: opts.body === undefined ? undefined : isForm ? (opts.body as FormData) : JSON.stringify(opts.body),
  });
  if (opts.raw && res.ok) return res as any;
  if (!res.ok) {
    let detail: any = null;
    try { detail = (await res.json()).detail; } catch { /* not JSON */ }
    const message = typeof detail === "string" ? detail : detail?.message ?? `Request failed (${res.status})`;
    const err = new ApiError(res.status, message, typeof detail === "object" ? detail?.code : undefined);
    if (res.status === 402) limitListeners.forEach((fn) => fn(err));
    if (res.status === 401 && path !== "/me") window.dispatchEvent(new Event("lectern:signed-out"));
    throw err;
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

export async function apiBlobUrl(path: string): Promise<string> {
  const res: Response = await api(path, { raw: true });
  return URL.createObjectURL(await res.blob());
}

export async function download(path: string, filename: string) {
  const url = await apiBlobUrl(path);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

/** PUT a file straight to S3 with a presigned URL, reporting progress 0..1. */
export function uploadToS3(url: string, file: File, onProgress: (p: number) => void): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    xhr.setRequestHeader("Content-Type", "application/pdf");
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => (xhr.status < 300 ? resolve() : reject(new Error(`Upload failed (${xhr.status})`)));
    xhr.onerror = () => reject(new Error("Upload failed. Check your connection and try again."));
    xhr.send(file);
  });
}

let pending = 0;
let timer: number | undefined;
/** Count study time while a learning page is open and visible; flushed every minute. */
export function trackStudy(bookId: string) {
  let last = Date.now();
  const tick = () => {
    const now = Date.now();
    if (document.visibilityState === "visible") pending += Math.min(90, (now - last) / 1000);
    last = now;
    if (pending >= 30) {
      const seconds = Math.round(pending);
      pending = 0;
      api("/activity", { body: { book_id: bookId, seconds } }).catch(() => undefined);
    }
  };
  window.clearInterval(timer);
  timer = window.setInterval(tick, 15000);
  return () => { tick(); window.clearInterval(timer); };
}
