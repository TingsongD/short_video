import React, { useRef, useState } from "react";

export interface CompareEntry {
  key: string;               // "source" | "A" | "B" | "C" | "D"
  label: string;             // e.g. "B — new hook (r1)"
  media_url: string;
  media_sha: string;         // exact identity label
  regions?: { start_s: number; end_s: number; label: string }[];
  duration_s?: number;
}

/** Source + A/B/C/D synchronized playback; declared changed regions
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
            <video ref={(v) => { videos.current[e.key] = v; }}
                   src={e.media_url} controls preload="metadata"
                   aria-label={`${e.label} playback`}
                   onSeeked={(ev) =>
                     syncAll((ev.target as HTMLVideoElement)
                       .currentTime)} />
            <figcaption>
              {e.label}
              <span className="identity"> sha {e.media_sha.slice(0, 8)}
              </span>
            </figcaption>
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
          </figure>
        ))}
      </div>
      <output aria-label="sync position">{syncT.toFixed(1)}s</output>
    </section>
  );
}
