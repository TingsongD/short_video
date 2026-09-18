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
export async function actionKey(method: string, path: string, body: unknown, rev?: number): Promise<string> {
  const canonical = (v: unknown): unknown => Array.isArray(v) ? v.map(canonical) :
    v !== null && typeof v === "object" ? Object.fromEntries(Object.entries(v).sort(([a],[b])=>a.localeCompare(b)).map(([k,x])=>[k,canonical(x)])) : v;
  const bytes = new TextEncoder().encode(JSON.stringify([method,path,rev ?? null,canonical(body)]));
  const hash = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",bytes))).map(x=>x.toString(16).padStart(2,"0")).join("");
  // Retain an unacknowledged action across tabs/reloads. Advance its generation
  // only after a successful response, so a later pause/resume remains actionable.
  const storageKey = `factory-action:${hash}`;
  const key = window.localStorage.getItem(storageKey) || `ui-v3-${hash}-0`;
  window.localStorage.setItem(storageKey,key);
  return key;
}

function acknowledge(key: string) {
  const match = /^ui-v3-([a-f0-9]+)-(\d+)$/.exec(key);
  if (!match) return;
  const storageKey=`factory-action:${match[1]}`;
  if(window.localStorage.getItem(storageKey)===key)
    window.localStorage.setItem(storageKey,`ui-v3-${match[1]}-${Number(match[2])+1}`);
}

export async function session(): Promise<string> {
  const r = await fetch("/api/session", { method: "POST" });
  if (!r.ok) throw new ApiError(r.status, "session_failed", undefined,
                              "could not establish local session");
  csrfToken = (await r.json()).session_token as string;
  return csrfToken as string;
}

export async function call<T>(
  method: string,
  path: string,
  opts: { body?: unknown; key?: string; rev?: number } = {},
): Promise<T> {
  const headers: Record<string, string> = {};
  if (opts.body !== undefined) headers["content-type"] = "application/json";
  if (method !== "GET") {
    if (!csrfToken) await session();
    headers["idempotency-key"] = opts.key ?? await actionKey(method,path,opts.body,opts.rev);
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
  if (r.ok && headers["idempotency-key"]) acknowledge(headers["idempotency-key"]);
  return json as T;
}

export const api = {
  health: () => call<Record<string, unknown>>("GET", "/api/health"),
  providers: (refresh = false) =>
    call<Record<string, ProviderReadiness>>("GET", `/api/providers${refresh ? "?refresh=1" : ""}`),
  getSeed: (id: string) => call<Record<string, unknown>>("GET", `/api/seeds/${id}`),
  results: (id: string) =>
    call<Record<string, unknown>>("GET", `/api/experiments/${id}/results`),

  createSeed: (url: string) =>
    call("POST", "/api/seeds", { body: { url } }),
  importFile: async (file: File) => {
    if (!csrfToken) await session();
    const digest = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",await file.arrayBuffer()))).map(x=>x.toString(16).padStart(2,"0")).join("");
    const key = await actionKey("POST","/api/imports",{name:file.name,sha256:digest});
    return fetch("/api/imports", {
      method: "POST",
      headers: {
        "x-filename": file.name,
        "idempotency-key": key,
        ...(csrfToken ? { "x-csrf-token": csrfToken } : {}),
      },
      body: file,
    }).then(async (r) => {
      const j = await r.json();
      if (!r.ok)
        throw new ApiError(r.status, j.error ?? "http_error", j.field,
                           j.detail ?? "");
      acknowledge(key);
      return j;
    });
  },
  analyze: (seedId: string) =>
    call("POST", `/api/seeds/${seedId}/analyze`, { body: {} }),
  getAnalysis: (seedId: string) =>
    call<Record<string, unknown> | null>("GET", `/api/analysis/${seedId}`),
  startAnalysis: (seedId: string, reviewer: string) =>
    call("POST", `/api/seeds/${seedId}/analysis`, { body: { reviewer } }),
  rerunAnalysis: (seedId: string) =>
    call("POST", `/api/analysis/${seedId}/rerun`, { body: {} }),
  saveAnalysis: (seedId: string, section: string,
                 body: Record<string, unknown>) =>
    call("PUT", `/api/analysis/${seedId}/${section}`, { body }),
  importTranscript: (seedId: string, body: Record<string, unknown>) =>
    call("POST", `/api/analysis/${seedId}/transcript`, { body }),
  declareAnalysis: (seedId: string, body: Record<string, unknown>) =>
    call("POST", `/api/analysis/${seedId}/declare`, { body }),
  reviewAnalysis: (seedId: string, body: Record<string, unknown>) =>
    call("POST", `/api/analysis/${seedId}/review`, { body }),
  createExperiment: (body: Record<string, unknown>) =>
    call("POST", "/api/experiments", { body }),
  patchDraft: (id: string, patch: Record<string, unknown>, rev: number) =>
    call("PATCH", `/api/experiments/${id}/draft`, { body: patch, rev }),
  quote: (id: string, rev?: number) =>
    call<{ quote: Quote }>("POST", `/api/experiments/${id}/quote`,
                           { body: {}, rev }),
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
  deliver: (variantId: string, body: Record<string, unknown>, rev?: number) =>
    call("POST", `/api/variants/${variantId}/deliver`, { body, rev }),
};

/** SSE with Last-Event-ID reconnect — the durable log guarantees no
 * missed events; a disconnect never cancels server work. */
export function events(
  stream: string,
  onEvent: (seq: number, type: string, body: unknown) => void,
): EventSource {
  const cursorKey = `factory-events:${stream}`;
  const after = window.localStorage.getItem(cursorKey) || "0";
  let seen = Number(after);
  const es = new EventSource(`/api/events?stream=${encodeURIComponent(stream)}&follow=1&after=${encodeURIComponent(after)}`);
  es.addEventListener("factory", (event) => {
    const m = event as MessageEvent<string>;
    const seq = Number(m.lastEventId || 0);
    if (seq <= seen) return;
    seen = seq;
    const data = JSON.parse(m.data) as {type:string;body:unknown};
    onEvent(seq,data.type,data.body);
    window.localStorage.setItem(cursorKey,String(Math.max(seq,Number(window.localStorage.getItem(cursorKey)||0))));
  });
  return es;
}
