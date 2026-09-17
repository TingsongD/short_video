import React from "react";

/** Every screen renders one of these states — loading, empty,
 * blocked, stale or error are first-class, never blank. */

export function Loading({ what }: { what: string }) {
  return <p role="status" aria-live="polite">Loading {what}…</p>;
}

export function Empty({ what, hint }: { what: string; hint?: string }) {
  return (
    <p role="status">
      No {what} yet.{hint ? ` ${hint}` : ""}
    </p>
  );
}

export function Blocked({ why, action }: { why: string; action?: string }) {
  return (
    <div role="alert" className="blocked">
      <strong>Blocked:</strong> {why}
      {action ? <span> — {action}</span> : null}
    </div>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  const e = error as { code?: string; detail?: string; message?: string };
  return (
    <div role="alert" className="error">
      {e.code === "stale_revision" || e.code === "idempotency_conflict"
        ? <>This view is stale — {e.detail ?? "refresh to see the latest"}
           </>
        : <>{e.detail ?? e.message ?? "Something went wrong"}</>}
    </div>
  );
}

export function StaleBadge() {
  return <span aria-label="stale" title="Changed elsewhere">stale</span>;
}

export function RevisionBadge({ rev }: { rev: number }) {
  return <span aria-label={`revision ${rev}`}>r{rev}</span>;
}

/** Generic async-resource hook shape used by every screen. */
export type Remote<T> =
  | { state: "loading" }
  | { state: "error"; error: unknown }
  | { state: "empty" }
  | { state: "ready"; data: T }
  | { state: "blocked"; why: string; action?: string };

export function remoteOf<T>(list: T[] | undefined, error: unknown): Remote<T[]> {
  if (error) return { state: "error", error };
  if (list === undefined) return { state: "loading" };
  if (list.length === 0) return { state: "empty" };
  return { state: "ready", data: list };
}
