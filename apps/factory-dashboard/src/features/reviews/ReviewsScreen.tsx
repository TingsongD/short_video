import React, { useState } from "react";
import { Blocked } from "../../components/States";

export interface QcFailure {
  check: string;
  detail: string;            // e.g. "black_section@1.0-2.0s"
  frames?: number[];
  words?: string[];
  product_ref?: string;
}

export interface ReviewTarget {
  variant: string;
  sha256: string;
  revision: number;
  stale: boolean;
  failures: QcFailure[];
}

/** QC failures with exact locations; accept/reject binds the exact
 * artifact hash; a stale target can never be accepted. */
export function ReviewsScreen(
  { target, onVerdict }: {
    target: ReviewTarget;
    onVerdict?: (verdict: "accept" | "reject", notes: string) => void;
  },
) {
  const [notes, setNotes] = useState("");
  return (
    <section aria-label="review">
      <h2>Review — variant {target.variant}</h2>
      <p>
        final sha <code>{target.sha256.slice(0, 12)}</code> · r
        {target.revision}
      </p>
      {target.stale && (
        <Blocked why="This review belongs to an older final"
                 action="Inspect the current render — the old verdict
                   cannot accept it." />
      )}
      {target.failures.length > 0 && (
        <table aria-label="failures">
          <thead>
            <tr><th>check</th><th>location</th><th>detail</th></tr>
          </thead>
          <tbody>
            {target.failures.map((f, i) => (
              <tr key={i}>
                <td>{f.check}</td>
                <td>
                  {f.frames?.length
                    ? `frames ${f.frames.join(",")}`
                    : f.words?.length
                      ? `words "${f.words.join(" ")}"`
                      : f.product_ref ?? "—"}
                </td>
                <td>{f.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <label htmlFor="notes">reviewer notes</label>
      <textarea id="notes" value={notes}
                onChange={(e) => setNotes(e.target.value)} />
      <button disabled={target.stale}
              onClick={() => onVerdict?.("accept", notes)}>
        Accept this final
      </button>
      <button onClick={() => onVerdict?.("reject", notes)}>
        Needs changes
      </button>
    </section>
  );
}
