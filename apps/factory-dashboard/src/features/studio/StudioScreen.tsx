import React, { useState } from "react";

export interface ProposedChange {
  id: string;
  variant_id: string;
  at_s: number;
  text: string;
  source_revision: number;
  status: "proposed" | "stale" | "applied";
}

/** Owned Hypit Studio session + comment import. Comments map to an
 * exact revision + timeline position and become proposed changes —
 * never immediate regeneration. */
export function StudioScreen(
  { session, changes, onOpen, onClose, onImport }: {
    session: { id: string; state: string; port?: number } | null;
    changes: ProposedChange[];
    onOpen?: () => void;
    onClose?: () => void;
    onImport?: (at_s: number, text: string, revision: number) => void;
  },
) {
  const [at, setAt] = useState("0");
  const [text, setText] = useState("");
  const [rev, setRev] = useState("0");
  const open = session?.state === "open";

  return (
    <section aria-label="studio">
      <h2>Studio preview</h2>
      {open
        ? <>
            <p>Session {session!.id} · port {session!.port}</p>
            <button onClick={onClose}>Stop preview</button>
          </>
        : <button onClick={onOpen}>Open Studio preview</button>}
      <fieldset disabled={!open}>
        <legend>Import comment</legend>
        <label htmlFor="at">at (s)</label>
        <input id="at" value={at} onChange={(e) => setAt(e.target.value)} />
        <label htmlFor="comment">comment</label>
        <input id="comment" value={text}
               onChange={(e) => setText(e.target.value)} />
        <label htmlFor="rev">source revision</label>
        <input id="rev" value={rev} onChange={(e) => setRev(e.target.value)} />
        <button onClick={() =>
          onImport?.(Number(at), text, Number(rev))}>
          Create proposed change
        </button>
      </fieldset>
      <ul aria-label="proposed changes">
        {changes.map((c) => (
          <li key={c.id} className={c.status}>
            [{c.status}] r{c.source_revision} @{c.at_s}s — {c.text}
          </li>
        ))}
      </ul>
    </section>
  );
}
