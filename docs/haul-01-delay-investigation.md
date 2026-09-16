# Haul 01 delay investigation — September 16, 2026

## Finding

The retained logs do not show a multi-hour pause at “6 of 20 sections rendered.”
They show continuous rendering and a stale conversational progress snapshot.
The earlier hours of production include a separate, avoidable continuation
problem: the producing agent repeatedly ended its turn after submitting the
next clip and waited for the scheduled heartbeat to resume creative review.

## Render timeline

All times below are Vancouver time (PDT, UTC−7), September 16.

| Event | Time |
|---|---|
| Section 1 render started | 6:47:16 a.m. |
| Section 6 verified | 6:55:43 a.m. |
| Section 7 started | 6:55:50 a.m. |
| Assistant sent “6 of 20 sections rendered” as a final reply | 6:56:23 a.m. |
| User asked to continue the allegedly stopped process | 6:58:50 a.m. |
| Section 20 verified | 7:18:30 a.m. |
| Drive upload verified | 7:25:33 a.m. |
| Video cleanup verified | 7:25:35 a.m. |

Section 7 started 6.45 seconds after section 6 was verified. All twenty
sections rendered in approximately 31 minutes 14 seconds. The progress message
was followed by the user's continuation request about 2 minutes 27 seconds
later; the underlying worker had advanced to section 9. No restart was needed.
The final join's timestamp defect was discovered only after section 20, so it
cannot explain an earlier stall at section 6. That separate defect was fixed
and the existing frames were reused without paid regeneration.

## Where the hours went

The initial implementation request was at 11:30 p.m. on September 15; delivery
was approximately 7 hours 55 minutes later, including implementation/setup,
generation, creative review, picture timing corrections, rendering and QC.

Across the earlier generation phase, the task history contains twenty gaps
between agent turns totaling about 263 minutes (median 13.05 minutes). Some
background generation continued during these gaps, so that total must not be
described as fully idle time.

More specifically, seventeen native clip files had already been downloaded
while no agent turn was active. Comparing their retained file modification
times with the next task-start event gives **173.91 minutes** waiting for the
agent to return, approximately 10.03–10.50 minutes per clip. File modification
times are local download evidence, not authoritative provider completion times.
This excludes time actually spent reviewing each artifact. It supports an
avoidable scheduling delay of roughly **2 hours 54 minutes** before reviews
could even begin.

The runner intentionally requires real artifact reviews. Those checks were
appropriate; ending the producing agent's turn between each clip was not
necessary. The agent could have waited for the existing job and continued the
review within the same active turn. The heartbeat became the normal handoff
instead of a recovery mechanism. The final reply at 6/20 also made a live
background process look stopped in conversation.

## Correction applied

Updated the existing `produce-sequential-msdressly-hauls` heartbeat instructions
to keep the producing agent active through the current video's generation,
reviews, rendering, QC, verified upload and cleanup. It must wait on existing
jobs, promptly inspect actual artifacts, and continue after status questions.
The ten-minute heartbeat remains recovery for interrupted execution. Existing
budgets, single-job policy, quality gates and stop conditions are unchanged.

This is an instruction correction, not proof that the next video's elapsed
time has improved. Verify that on the next run using download-to-review and
render timestamps. No new generation was submitted for this investigation.

## Evidence

- `data/production/next-15-video-plan-20260915/productions/haul-01/rendered-sections/clip-01.json`
  through `clip-20.json`: saved build starts; verified receipt modification times.
- The same production's original `assets/clip-NN.jimeng.mp4` modification times,
  `upload-receipt.json`, `cleanup-receipt.json`, and batch review timestamps.
- Current task `01a0a379-b4c9-7a10-a2c4-5bb62682ba80`: persisted task-start/end
  events and exact 6/20 message timestamp. No credentials or private transcripts
  are reproduced in this report.
- `modules/batch/runner.py`: `require_review` and its per-artifact calls.
- Existing automation inspected and updated through the Codex automation tool.
