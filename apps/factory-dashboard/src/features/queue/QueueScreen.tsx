import React from "react";

export interface JobEvent {
  seq: number;
  type: string;
  at: string;
}

export interface JobView {
  id: string;
  variant: string;
  stage: string;
  state: "queued" | "running" | "done" | "failed" | "blocked";
  started_at?: string;
  finished_at?: string;
}

/** Stage labels are honest pipeline states — never a guessed %.
 * `reduceJobs` replays durable events into per-variant progress. */
export const STAGES = [
  "ready", "queued", "provider_running", "downloaded", "review",
  "render", "upload", "cleanup",
] as const;

export function reduceJobs(events: JobEvent[]): JobView[] {
  const jobs = new Map<string, JobView>();
  for (const e of events) {
    const [jobId, stage] = e.type.split(":", 2) as [string, string];
    const prev = jobs.get(jobId);
    const terminal = stage === "cleanup" || stage === "failed";
    jobs.set(jobId, {
      id: jobId,
      variant: jobId.split("-")[1] ?? "?",
      stage: (STAGES as readonly string[]).includes(stage) ? stage
        : "queued",
      state: stage === "failed" ? "failed"
        : stage === "cleanup" ? "done"
        : "running",
      started_at: prev?.started_at ?? e.at,
      finished_at: terminal ? e.at : undefined,
    });
  }
  return [...jobs.values()];
}

export function elapsedBreakdown(events: JobEvent[]): Record<string, number> {
  const spans: Record<string, number> = {};
  for (let i = 1; i < events.length; i++) {
    const stage = events[i - 1].type.split(":", 2)[1] ?? "?";
    const dt = new Date(events[i].at).getTime()
      - new Date(events[i - 1].at).getTime();
    spans[stage] = (spans[stage] ?? 0) + dt;
  }
  return spans;
}

export function QueueScreen(
  { jobs, onPause, onResume, onReconcile, onRetry, onRelease }: {
    jobs: JobView[];
    onPause?: () => void;
    onResume?: () => void;
    onReconcile?: (jobId: string) => void;
    onRetry?: (jobId: string) => void;
    onRelease?: (jobId: string) => void;
  },
) {
  const done = jobs.filter((j) => j.state === "done").length;
  return (
    <section aria-label="queue">
      <h2>Queue</h2>
      <p>{done}/{jobs.length} complete</p>
      <button onClick={onPause}>Pause new work</button>
      <button onClick={onResume}>Resume</button>
      <table>
        <thead>
          <tr><th>job</th><th>variant</th><th>stage</th><th>state</th>
              <th>action</th></tr>
        </thead>
        <tbody>
          {jobs.map((j) => (
            <tr key={j.id}>
              <td>{j.id}</td><td>{j.variant}</td>
              <td>{j.stage.replace("_", " ")}</td>
              <td>{j.state === "running" ? "Waiting for provider"
                  : j.state}</td>
              <td>
                {["failed","blocked"].includes(j.state) &&
                  <button onClick={() => onReconcile?.(j.id)}>
                    Reconcile
                  </button>}
                {j.state === "failed" && <><button onClick={()=>onRetry?.(j.id)}>Retry local work</button>{j.stage === "render" && <button onClick={()=>onRelease?.(j.id)}>Clean up failed render</button>}</>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="note">
        Pause stops new dispatch — accepted work keeps running.
        Resume continues existing jobs; it never regenerates.
      </p>
    </section>
  );
}
