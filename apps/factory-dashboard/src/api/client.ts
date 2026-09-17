/**
 * Typed client for factory-api.v1 — paths mirror F27 exactly.
 * Mutations send Idempotency-Key + X-CSRF-Token + optional
 * X-Expected-Revision; 409 bodies carry {error, field, detail}.
 */

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    public field: string | undefined,
    detail: string,
  ) {
    super(detail);
  }
  get stale() {
    return this.code === "stale_revision" ||
      this.code === "idempotency_conflict";
  }
}

export interface ProviderReadiness {
  installed: boolean;
  authenticated: boolean;
  catalog_visible: boolean;
  tested: boolean;
  qualified: boolean;
  detail?: Record<string, unknown>;
}

export interface Quote {
  experiment_id: string;
  revision: number;
  units: { credits: number; usd_micros: number };
  unknown_charges: string[];
  line_items: { label?: string; credits?: number; usd_micros?: number }[];
}

let csrfToken: string | null = null;
let keySeq = 0;

export async function session(): Promise<string> {
  const r = await fetch("/api/session", { method: "POST" });
  if (!r.ok) throw new ApiError(r.status, "session_failed", undefined,
                              "could not establish local session");
  csrfToken = (await r.json()).session_token as string;
  return csrfToken as string;
}

async function call<T>(
  method: string,
  path: string,
  opts: { body?: unknown; key?: string; rev?: number } = {},
): Promise<T> {
  const headers: Record<string, string> = {};
  if (opts.body !== undefined) headers["content-type"] = "application/json";
  if (method !== "GET") {
    headers["idempotency-key"] = opts.key ?? `ui-${++keySeq}`;
    if (csrfToken) headers["x-csrf-token"] = csrfToken;
    if (opts.rev !== undefined)
      headers["x-expected-revision"] = String(opts.rev);
  }
  const r = await fetch(path, {
    method,
    headers,
    body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
  });
  const text = await r.text();
  const json = text ? JSON.parse(text) : {};
  if (!r.ok) {
    throw new ApiError(r.status, json.error ?? "http_error",
                       json.field, json.detail ?? r.statusText);
  }
  return json as T;
}

export const api = {
  health: () => call<Record<string, unknown>>("GET", "/api/health"),
  providers: () =>
    call<Record<string, ProviderReadiness>>("GET", "/api/providers"),
  getSeed: (id: string) => call<Record<string, unknown>>("GET", `/api/seeds/${id}`),
  results: (id: string) =>
    call<Record<string, unknown>>("GET", `/api/experiments/${id}/results`),

  createSeed: (url: string) =>
    call("POST", "/api/seeds", { body: { url } }),
  importFile: (file: File) =>
    fetch("/api/imports", {
      method: "POST",
      headers: {
        "x-filename": file.name,
        "idempotency-key": `ui-${++keySeq}`,
        ...(csrfToken ? { "x-csrf-token": csrfToken } : {}),
      },
      body: file,
    }).then(async (r) => {
      const j = await r.json();
      if (!r.ok)
        throw new ApiError(r.status, j.error ?? "http_error", j.field,
                           j.detail ?? "");
      return j;
    }),
  analyze: (seedId: string) =>
    call("POST", `/api/seeds/${seedId}/analyze`, { body: {} }),
  createExperiment: (body: Record<string, unknown>) =>
    call("POST", "/api/experiments", { body }),
  patchDraft: (id: string, patch: Record<string, unknown>, rev: number) =>
    call("PATCH", `/api/experiments/${id}/draft`, { body: patch, rev }),
  quote: (id: string) =>
    call<{ quote: Quote }>("POST", `/api/experiments/${id}/quote`,
                           { body: {} }),
  authorize: (id: string, rev: number) =>
    call("POST", `/api/experiments/${id}/authorize`,
         { body: {}, rev }),
  run: (id: string, rev: number) =>
    call("POST", `/api/experiments/${id}/run`, { body: {}, rev }),
  pause: (id: string) =>
    call("POST", `/api/experiments/${id}/pause`, { body: {} }),
  resume: (id: string) =>
    call("POST", `/api/experiments/${id}/resume`, { body: {} }),
  review: (variantId: string, body: Record<string, unknown>) =>
    call("POST", `/api/variants/${variantId}/reviews`, { body }),
  deliver: (variantId: string, body: Record<string, unknown>) =>
    call("POST", `/api/variants/${variantId}/deliver`, { body }),
};

/** SSE with Last-Event-ID reconnect — the durable log guarantees no
 * missed events; a disconnect never cancels server work. */
export function events(
  stream: string,
  onEvent: (seq: number, type: string, body: unknown) => void,
): EventSource {
  const es = new EventSource(`/api/events?stream=${stream}&follow=1`);
  es.onmessage = (m) => {
    try {
      onEvent(Number(m.lastEventId || 0), "message", JSON.parse(m.data));
    } catch {
      onEvent(Number(m.lastEventId || 0), "message", m.data);
    }
  };
  return es;
}
