import React, { useRef, useState } from "react";

export interface CompareDetails {
  changes?: {
    summary?: string; factor?: string; metric?: string;
    label?: string;
    regions?: { start_s: number; end_s: number }[];
    changed_segments?: { segment: string; fields: string[];
                         a_copy?: string; b_copy?: string }[];
  };
  checks?: { check_type?: string; verdict?: string; reviewer?: string;
             limitations?: string[] }[];
  captions?: string[];
  script?: string[];
}

export interface CompareEntry {
  key: string;               // "source" | "A" | "B" | "C" | "D"
  label: string;             // e.g. "B — new hook (r1)"
  media_url?: string;
  media_sha?: string;        // exact identity label
  pending?: boolean;
  state?: string;            // ready_for_review|validation_blocked|stale|…
  problems?: string[];       // actionable validation failures
  regions?: { start_s: number; end_s: number; label: string }[];
  duration_s?: number;
  details?: CompareDetails;
}

/** Source + A/B/C/D linked seeking; declared changed regions
 * are visibly marked so unchanged content stays comparable. */
export function CompareScreen({ entries }: { entries: CompareEntry[] }) {
  const videos = useRef<Record<string, HTMLVideoElement | null>>({});
  const [syncT, setSyncT] = useState(0);

  function syncAll(t: number) {
    setSyncT(t);
    for (const v of Object.values(videos.current)) {
      if (v && Math.abs(v.currentTime - t) > 0.1) v.currentTime = t;
    }
  }

  return (
    <section aria-label="compare">
      <h2>Compare</h2>
      <div className="grid">
        {entries.map((e) => (
          <figure key={e.key}>
            {e.pending ? (
              <div className="pending" role="status"
                   aria-label={`${e.label} still rendering`}>
                Rendering…
              </div>
            ) : (
              <video ref={(v) => { videos.current[e.key] = v; }}
                     src={e.media_url} controls preload="metadata"
                     aria-label={`${e.label} playback`}
                     onSeeked={(ev) =>
                       syncAll((ev.target as HTMLVideoElement)
                         .currentTime)} />
            )}
            <figcaption>
              {e.label}
              {e.media_sha ? (
                <span className="identity"> sha {e.media_sha.slice(0, 8)}
                </span>) : null}
              {e.state ? (
                <span className={`final-state ${e.state}`}
                      aria-label={`${e.key} validation state`}>
                  {" "}{e.state.replace(/_/g, " ")}
                </span>) : null}
            </figcaption>
            {(e.problems || []).length > 0 && (
              <ul className="validation-problems" role="alert">
                {e.problems!.map((p, i) => <li key={i}>{p}</li>)}
              </ul>)}
            {e.regions && e.duration_s ? (
              <div className="regions" aria-label={`${e.key} changes`}>
                {e.regions.map((r, i) => (
                  <span key={i} className="region"
                        title={`${r.label} ${r.start_s}–${r.end_s}s`}
                        style={{
                          left: `${(r.start_s / e.duration_s!) * 100}%`,
                          width: `${((r.end_s - r.start_s)
                                     / e.duration_s!) * 100}%`,
                        }} />
                ))}
              </div>
            ) : null}
            {e.details ? <VariantDetails d={e.details} /> : null}
          </figure>
        ))}
      </div>
      <output aria-label="sync position">Linked seeking: {syncT.toFixed(1)}s (play/pause separately)</output>
    </section>
  );
}

function VariantDetails({ d }: { d: CompareDetails }) {
  const c = d.changes;
  return (
    <details className="variant-details">
      <summary>
        {c?.factor === "control" || !c?.factor
          ? "Control" : `Test: ${c.label || c.factor}`}
        {c?.metric ? ` · metric ${c.metric}` : ""}
      </summary>
      {c?.summary ? <p className="hypothesis">{c.summary}</p> : null}
      {(c?.changed_segments || []).map((s) => (
        <div key={s.segment} className="changed">
          <strong>{s.segment}</strong> changed: {s.fields.join(", ")}
          {s.a_copy !== s.b_copy ? (
            <p><em>was:</em> {s.a_copy || "—"}<br />
               <em>now:</em> {s.b_copy || "—"}</p>) : null}
        </div>))}
      {(d.script || []).length > 0 && (
        <p className="script">Script: {d.script!.join(" · ")}</p>)}
      {(d.captions || []).length > 0 && (
        <p className="captions">Captions: {d.captions!.join(" · ")}</p>)}
      {(d.checks || []).length > 0 && (
        <ul className="checks">
          {d.checks!.map((k, i) => (
            <li key={i} className={k.verdict}>
              {k.check_type}: {k.verdict}
              {k.reviewer === "auto-pipeline" ? " (automated)" : ""}
              {(k.limitations || []).length
                ? ` — ${k.limitations!.join("; ")}` : ""}
            </li>))}
        </ul>)}
    </details>
  );
}
