import React, { useState } from "react";
import { api, ApiError } from "../../api/client";
import { Blocked, Empty, ErrorBox, Loading } from "../../components/States";

export interface SeedView {
  id: string;
  canonical_url: string;
  status: string;
  outlier_ratio?: number | null;
  baseline_ratio?: number | null;
  observed_at?: string;
  cohort_size?: number;
  confidence?: string;
  media_artifact?: string;
}

/** Seed intake + discovery evidence: both outlier ratios, observation
 * age, cohort/confidence, unavailable-video guidance, and source
 * playback before any blueprint acceptance. */
export function SeedsScreen({ seeds }: { seeds: SeedView[] | undefined }) {
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [added, setAdded] = useState<SeedView[]>([]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (busy || !url.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const r = (await api.createSeed(url.trim())) as {
        seed: SeedView; created: boolean;
      };
      setAdded((a) => [...a, r.seed]);
      setUrl("");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  const list = [...(seeds ?? []), ...added];
  return (
    <section aria-label="seeds">
      <h2>Seeds</h2>
      <form onSubmit={submit}>
        <label htmlFor="seed-url">Reference URL</label>
        <input id="seed-url" value={url}
               onChange={(e) => setUrl(e.target.value)}
               placeholder="https://youtu.be/…" />
        <button type="submit" disabled={busy || !url.trim()}>
          {busy ? "Importing…" : "Import seed"}
        </button>
      </form>
      {error ? <ErrorBox error={error} /> : null}
      {seeds === undefined ? <Loading what="seeds" />
        : list.length === 0
          ? <Empty what="seeds" hint="Import a reference URL to start." />
          : (
        <ul>
          {list.map((s) => (
            <li key={s.id}>
              <strong>{s.canonical_url}</strong> — {s.status}
              {s.status === "needs_source_media" && (
                <Blocked why="Source video unavailable"
                         action="Import the file manually or pick a
                           different reference." />
              )}
              <div className="ratios">
                {s.outlier_ratio == null || s.baseline_ratio == null
                  ? <span>Outlier evidence pending</span>
                  : <>
                      <span>outlier ×{s.outlier_ratio}</span>{" "}
                      <span>cohort baseline ×{s.baseline_ratio}</span>
                    </>}
              </div>
              {s.observed_at && <div>observed {s.observed_at}</div>}
              {s.cohort_size != null &&
                <div>cohort {s.cohort_size} · confidence{" "}
                     {s.confidence ?? "unknown"}</div>}
              {s.media_artifact && (
                <video controls preload="metadata"
                       aria-label="source playback"
                       src={`/api/assets/${s.media_artifact}/media`} />
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
