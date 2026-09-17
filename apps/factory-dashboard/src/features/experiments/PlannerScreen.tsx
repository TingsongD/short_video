import React, { useState } from "react";
import { api, ApiError, Quote } from "../../api/client";
import { Blocked, ErrorBox, RevisionBadge } from "../../components/States";

/** Quote → authorize → run with revision-bound approval. The Run
 * button sends the quoted revision; a stale plan shows a clear
 * conflict instead of running on old approval. */
export function PlannerScreen({ experimentId }: { experimentId: string }) {
  const [quote, setQuote] = useState<Quote | null>(null);
  const [authorized, setAuthorized] = useState<number | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState<"" | "quote" | "auth" | "run">("");

  async function step(kind: "quote" | "auth" | "run") {
    if (busy) return;                        // double-click idempotent
    setBusy(kind);
    setError(null);
    try {
      if (kind === "quote") {
        const r = await api.quote(experimentId);
        setQuote(r.quote);
        setAuthorized(null);                  // new quote → re-approve
      } else if (kind === "auth" && quote) {
        await api.authorize(experimentId, quote.revision);
        setAuthorized(quote.revision);
      } else if (kind === "run" && quote) {
        const r = (await api.run(experimentId, quote.revision)) as {
          run: { job_id: string };
        };
        setJobId(r.run.job_id);
      }
    } catch (e) {
      setError(e);
    } finally {
      setBusy("");
    }
  }

  const ready = quote !== null && authorized === quote.revision;
  return (
    <section aria-label="planner">
      <h2>Experiment {experimentId}</h2>
      {error && (error as ApiError).stale
        ? <Blocked why="This plan changed after it was quoted"
                   action="Re-quote the current revision, then approve
                     it again." />
        : error ? <ErrorBox error={error} /> : null}
      <button onClick={() => step("quote")} disabled={busy !== ""}>
        {busy === "quote" ? "Quoting…" : "Get quote"}
      </button>
      {quote && (
        <div aria-label="quote">
          <RevisionBadge rev={quote.revision} />
          <ul>
            {quote.line_items.map((li, i) => (
              <li key={i}>
                {li.label ?? `item ${i + 1}`}:{" "}
                {li.credits ? `${li.credits} credits ` : ""}
                {li.usd_micros
                  ? `$${(li.usd_micros / 1e6).toFixed(2)}` : ""}
              </li>
            ))}
          </ul>
          <p>
            total: {quote.units.credits} credits, $
            {(quote.units.usd_micros / 1e6).toFixed(2)}
            {quote.unknown_charges.length > 0 &&
              ` — ${quote.unknown_charges.length} charge(s) unknown`}
          </p>
        </div>
      )}
      <button onClick={() => step("auth")}
              disabled={!quote || busy !== ""}>
        {authorized === quote?.revision
          ? `Approved r${authorized}` : "Approve this revision"}
      </button>
      <button onClick={() => step("run")} disabled={!ready || busy !== ""}>
        {busy === "run" ? "Starting…" : "Run"}
      </button>
      {jobId && <output aria-label="job">Started {jobId}</output>}
    </section>
  );
}
