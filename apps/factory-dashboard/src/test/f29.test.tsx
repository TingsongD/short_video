import React from "react";
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { QueueScreen, reduceJobs, elapsedBreakdown, JobEvent, queueJobView }
  from "../features/queue/QueueScreen";
import { CompareScreen } from "../features/compare/CompareScreen";
import { ReviewsScreen } from "../features/reviews/ReviewsScreen";
import { DeliveryScreen } from "../features/delivery/DeliveryScreen";
import { StudioScreen } from "../features/studio/StudioScreen";

const ev = (seq: number, type: string, at: string): JobEvent =>
  ({ seq, type, at });

describe("queue reducer", () => {
  it('labels deferred jobs as waiting without offering unsafe retries', () => {
    render(<QueueScreen jobs={['remote_unfinished','capacity_full','retry_backoff'].map((reason,i)=>queueJobView({id:String(i),status:'ready',phase:'generate',blocked_reason:reason}))}/>);
    expect(screen.getByText('Waiting for provider')).toBeInTheDocument();
    expect(screen.getByText('Waiting for capacity')).toBeInTheDocument();
    expect(screen.getByText('Waiting for retry backoff')).toBeInTheDocument();
    expect(screen.queryByText('Reconcile')).toBeNull();
  });
  it("replays events into honest stage labels and counts", () => {
    const jobs = reduceJobs([
      ev(1, "job-A:queued", "2026-09-17T00:00:00Z"),
      ev(2, "job-A:provider_running", "2026-09-17T00:00:05Z"),
      ev(3, "job-A:cleanup", "2026-09-17T00:00:20Z"),
      ev(4, "job-B:queued", "2026-09-17T00:00:01Z"),
      ev(5, "job-B:failed", "2026-09-17T00:00:09Z"),
    ]);
    const a = jobs.find((j) => j.id === "job-A")!;
    const b = jobs.find((j) => j.id === "job-B")!;
    expect(a.state).toBe("done");
    expect(a.stage).toBe("cleanup");
    expect(b.state).toBe("failed");
    const spans = elapsedBreakdown([
      ev(1, "job-A:queued", "2026-09-17T00:00:00Z"),
      ev(2, "job-A:provider_running", "2026-09-17T00:00:05Z"),
      ev(3, "job-A:cleanup", "2026-09-17T00:00:20Z"),
    ]);
    expect(spans.queued).toBe(5000);
    expect(spans.provider_running).toBe(15000);
  });

  it("renders distinct stages, completed count and reconcile", () => {
    const onReconcile = vi.fn();
    render(<QueueScreen onReconcile={onReconcile} jobs={[
      { id: "job-A", variant: "A", stage: "cleanup", state: "done" },
      { id: "job-B", variant: "B", stage: "provider_running",
        state: "running" },
      { id: "job-C", variant: "C", stage: "render", state: "failed" },
    ]} />);
    expect(screen.getByText("1/3 complete")).toBeInTheDocument();
    expect(screen.getByText("provider running")).toBeInTheDocument();
    expect(screen.getByText("Waiting for provider")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Reconcile"));
    expect(onReconcile).toHaveBeenCalledWith("job-C");
    expect(screen.getByText(/never regenerates/)).toBeInTheDocument();
  });
});

describe("compare", () => {
  it("labels exact media identity and marks changed regions", () => {
    render(<CompareScreen entries={[
      { key: "source", label: "Source", media_url: "/m/src",
        media_sha: "aaaaaaaaaaaaaaaa", duration_s: 10 },
      { key: "B", label: "B — new hook (r1)", media_url: "/m/b",
        media_sha: "bbbbbbbbbbbbbbbb", duration_s: 10,
        regions: [{ start_s: 0, end_s: 4, label: "hook" }] },
    ]} />);
    expect(screen.getByText(/sha aaaaaaaa/)).toBeInTheDocument();
    const regions = screen.getByLabelText("B changes")
      .querySelectorAll(".region");
    expect(regions).toHaveLength(1);
    expect((regions[0] as HTMLElement).style.width).toBe("40%");
    expect(screen.getByLabelText("Source playback"))
      .toBeInTheDocument();
  });
});

describe("reviews", () => {
  const target = {
    variant: "C", sha256: "deadbeefcafe1234", revision: 2,
    stale: false,
    failures: [
      { check: "caption_text", detail: "entity defect",
        words: ["don&#x27;t"] },
      { check: "black_section", detail: "black@1-2s",
        frames: [30, 45] },
    ],
  };

  it("shows failures with exact locations and verdict names hash", () => {
    const onVerdict = vi.fn();
    render(<ReviewsScreen target={target} onVerdict={onVerdict} />);
    expect(screen.getByText('words "don&#x27;t"')).toBeInTheDocument();
    expect(screen.getByText("frames 30,45")).toBeInTheDocument();
    expect(screen.getByText("deadbeefcafe")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Accept this final"));
    expect(onVerdict).toHaveBeenCalledWith("accept", "");
  });

  it("stale target blocks acceptance with an explanation", () => {
    render(<ReviewsScreen target={{ ...target, stale: true }} />);
    expect(screen.getByRole("alert"))
      .toHaveTextContent("older final");
    expect(screen.getByText("Accept this final")).toBeDisabled();
    expect(screen.getByText("Needs changes")).toBeEnabled();
  });
});

describe("delivery", () => {
  it("shows verified links, cleanup state and blocked actions", () => {
    render(<DeliveryScreen items={[
      { variant: "A", status: "verified",
        link: "https://drive.google.com/file/d/x/view",
        cleanup_state: "verified" },
      { variant: "B", status: "conflict", cleanup_state: "blocked",
        problems: ["size_mismatch"] },
    ]} />);
    expect(screen.getByText(/Upload verified/)).toBeInTheDocument();
    expect(screen.getByRole("link")).toHaveAttribute("href",
      "https://drive.google.com/file/d/x/view");
    expect(screen.getByRole("alert"))
      .toHaveTextContent("already uses this name");
    expect(screen.getByText(/cleanup blocked/)).toBeInTheDocument();
  });
});

describe("studio", () => {
  it("imports a comment as a revision-bound proposed change", () => {
    const onImport = vi.fn();
    render(<StudioScreen
      session={{ id: "s1", state: "open", port: 5100 }}
      changes={[{ id: "c1", variant_id: "v-C", at_s: 4,
                  text: "hook slow", source_revision: 2,
                  status: "proposed" }]}
      onImport={onImport} />);
    fireEvent.change(screen.getByLabelText("comment"),
                     { target: { value: "tighter" } });
    fireEvent.change(screen.getByLabelText("source revision"),
                     { target: { value: "2" } });
    fireEvent.click(screen.getByText("Create proposed change"));
    expect(onImport).toHaveBeenCalledWith(0, "tighter", 2);
    expect(screen.getByText(/\[proposed\] r2 @4s/)).toBeInTheDocument();
  });

  it("comment fieldset is disabled without an open session", () => {
    render(<StudioScreen session={null} changes={[]} />);
    expect(screen.getByRole("group")).toBeDisabled();
    expect(screen.getByText("Open Studio preview")).toBeEnabled();
  });
});
