# Seed pre-generation dry-run QA — complete

2026-09-23. Seed: https://www.youtube.com/shorts/l0mEEJPDl1A

**Two consecutive clean passes on the same final code and harness. Zero new paid
requests, zero live generation submissions.** Completion evidence:
`data/factory-qa/seed-l0mEEJPDl1A-dry/completion-audit.json`.

## Fix

An invalid source link displayed the internal error `no adapter for host ''`.
The dashboard now explains: “Enter a complete HTTPS video link from YouTube,
TikTok or Instagram.” The backend rejection, error code, status and one-request
behavior are preserved. Three regression cases failed before the fix and pass
afterward; the rebuilt actual browser UI was verified.

Changed application files: `apps/factory-dashboard/src/api/client.ts` and
`apps/factory-dashboard/src/test/api.test.ts`. No backend implementation, frozen
schema/fixture, credential, production job or financial record was changed.

The replay harness was also repaired: cached wardrobe data is translated to the
provider wire format; narration lookup accepts original and normalized text;
only proven duplicate cut observations are collapsed (103 observations → 99,
with four adjacent-frame aliases recorded); and the user-confirmed “how much
food I can get” correction is preserved in both transcript and model-response
replay. Original cached evidence remains untouched. All mocks are labeled.

## Completion evidence

All paths below are relative to `data/factory-qa/seed-l0mEEJPDl1A-dry/`.

| Requirement | Verified evidence |
|---|---|
| Two complete fresh-database passes | `final-pass-01/acceptance.json`, `final-pass-02/acceptance.json`; matching source/harness/guard hashes |
| Intake, evidence, analysis, blueprint, scripts, A–D variants | Both full replays use the actual saved seed and real application services; all 1,117 frames decoded/encoded locally |
| Normalization and output clock | 24/25/29.97/30/60 fps and VFR regressions in `pre-generation-baseline-fixed.log`; both seed passes preserve original SHA and enforce 30 fps output plans |
| Narration, timing, captions, editorial planning | Cached waveform/alignment replay through actual fitting; 20 approved segments, 70 two-line-or-shorter cues, four 1,118-frame plans; editorial validation passed |
| Script/scene consistency | Final audit checks 20 distinct variant-owned prompts and the correct source-beat action in each |
| Caption size, color, background and placement | All four actual pixel tests passed, including native rendering: `caption-fixture-check.log`; large white text, padded dark backing, safe placement and at least 7:1 tested contrast; saved PNGs visually inspected |
| Quote/readiness/authorization | Both replays produce accepted revisions and matching authorized quote hashes; `readiness-tests.log` adds 42 mocked readiness/credential-gate tests |
| Malformed/truncated responses | Editorial wire/truncation tests in 47-pass baseline; malformed acknowledgment tests in failure matrix |
| Throttling, timeouts, restart, cancellation, unknown outcomes | `failure-matrix-tests.log`: 70 passed; `recovery-baseline.log`: 69 passed; unknown outcomes retain identity/holds |
| Stale revisions, duplicate submission, reuse, exhausted budgets | Recovery, quote-readiness, budget and Flashcut reuse tests in those logs |
| Parallel generation scheduling without live submission | Parallel-generation tests in 47-pass baseline verify four in-flight mocks, fair refill, budget limits and unknown-operation capacity |
| Actual isolated dashboard | `dashboard-final-plan.txt/.png`, `dashboard-final-console.json`, `dashboard-checks.json`; accepted quote, progress, refresh/reload, errors, controls, worker-disconnection warning; dispatch never clicked |
| Production preservation | Final audit compares every row in jobs, attempts, budgets, reservations, reservation_lines and records with the initial snapshot: identical |
| Cleanup | `cleanup-verification.json`: isolated dashboard stopped, port 8111 free, no caption-test render processes; production services not signaled |

Source fingerprint for both final passes:
`137a434702106b98bad9d0a81cb6cdcf32e268124656d8690ee302d05662fe7a`.
Earlier exploratory passes are not counted. A pass during the UI edit correctly
failed its source-change check. The old transcript replay fails the new “food”
assertion. No known reproducible in-scope failure remains.

## Suite verification

- Full offline backend: **1,738 passed, seven helper-environment skips**. This is
  the completed full run after the final backend edits, not a newly repeated
  40-minute run. `final-suite-scope-verification.json` verifies the complete
  608-file set: only the two frontend files changed; all backend inputs remain
  identical. Original log: `../seed-l0mEEJPDl1A/offline-suite-audio-final.log`.
- Final frontend: **82 passed**, TypeScript and production build passed:
  `ui-tests-final.log`, `ui-build-final.log`.
- Helper runtime: **27 passed, no skips**, covering all seven dependency-skipped
  modules listed in `helper-main-env-skips.log`.
- Current targeted backend batches: **47**, **69**, **70**, and **42** passed;
  overlapping coverage is not added together. The two deselected native caption
  cases in the 70-pass batch passed in the separate **four-pass** pixel run.
- `git diff --check` passes; frozen `schemas/` and `tests/fixtures/` have no diff.

## Exact boundary and safety

Both autoruns stop at `run`, after quote/authorization and **before
`AutoRunService._stage_run` dispatch**. There is no `run_job`, no generation job,
and no fake-generation output. The footage submission sentinel was never called.
Production video entry points are `VertexAdapter.submit` and
`CanvasAdapter.submit`, reached through `EffectWork` and the durable executor.

Seed replays run under the verified macOS `pre-generation.sb`: all outbound
networking, production writes and credential-content access are denied, including
child connections. Local `/bin/ps` is permitted solely for process ownership.
Separate synthetic-caption tests permit loopback renderer traffic while blocking
external traffic and protecting production files; their Python runner also blocks
production API ports. This fixture-only profile is never used for seed replays.
The unsuccessful port-filter experiments are quarantined and were not used for
render tests. Detailed investigation history is retained in `investigation-history.md`.

Live-only uncertainty remains explicit: cached/mocked replies cannot qualify
current provider credentials, availability, prices, throughput, or newly generated
audiovisual quality. No upload, publishing, live qualification or broader module/
legacy acceptance is claimed. Real generation remains a separate authorized action.
