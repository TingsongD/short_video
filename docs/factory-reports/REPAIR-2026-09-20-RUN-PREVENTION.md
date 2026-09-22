# Run prevention and dashboard recovery — 2026-09-20

## Scope

User approved implementing the prevention changes following recovery of run
`auto-bbf59fdd645e4bdb` (seed `7udu-FBXoy8`). This is a code-and-tests change,
not authorization to accept that run's creative flags or dispatch more work.
Frozen contracts and fixtures, existing budgets, credentials and historical
receipt evidence are unchanged. One sequential builder on `feat/factory`.

## Repairs

1. **Approval survives recovery/restart.** Blueprint provenance binds the
   source SHA and raw analysis hash. Draft creation consumes `analysis_reset`;
   acceptance is a separate durable decision. An accepted matching draft is
   reused, not overwritten on Resume. Old unbound blueprints require matching
   source, beats, transcript, music and uncertainty with frame-quantization
   tolerance. Machine review works on a copy, preserving raw observations.
2. **Central analysis recovery.** `AnalysisRecovery` owns typed inspection,
   Resume guards, local revalidation/adoption and conservative settlement.
   Unknown attempts block Resume. Completed-invalid retries require explicit
   reviewer approval bound to the exact failed attempt and validation event,
   recorded in run history. Domain-level replay protection works even with a fresh
   HTTP idempotency key. Failure during adoption rolls settlement back.
3. **Constrained provider output.** The audiovisual request uses a provider-only
   response schema and clearer instructions about passage timing, silence,
   on-screen text and story roles. Local format/temporal validation is still
   authoritative; no scene bounds or narration are fabricated to pass it.
4. **Evidence-led scene review.** Auto shows timestamps, representative frames,
   linked speech and specific review limitations. Provider `reviewed` claims
   and invented evidence IDs cannot bypass local anchor checks. Mechanical
   machine checks are not human creative acceptance. No silent role edits.
5. **Preflight and capacity hygiene.** Live start/Resume checks worker, queue
   flags and dispatch availability. Selected-provider readiness runs before
   new paid authorization. Worker reclamation releases only retained remote
   capacity on terminal jobs with at least one attempt and no unfinished
   attempts; unknown/local holds are preserved.
6. **Actionable dashboard recovery.** Local recovery, settlement and explicitly
   paid retry are separate controls. Unknown outcomes offer no blind retry.
   Credential `request_not_sent` failures retain Google-specific guidance and
   explain that their own hold was released. Estimates are not called invoices.

## Verification

- Reproduced the original approval-reset failure before fixing it. Separate
  red tests reproduced provider self-review bypass and Google guidance being
  replaced with generic retry text.
- Final focused recovery/prevention/auth/pipeline suite: **65 passed**, offline,
  including stale paid-retry rejection, atomic rollback, saved-response replay,
  corrupted recovery-hint files, source drift and preserved global UI warnings.
- Targeted pipeline/analysis/auth/scheduler/application batch: **125 passed**
  before the final self-review/guidance refinements; the dedicated 21-line TTS
  batching regression also passed after adding explicit test-operator review.
- Full backend suite: **1,212 passed**, two dependency deprecation warnings,
  775.09 seconds. It collected before the final approval-audit/binding,
  corrupted-hint and global-warning refinements; the final 65-test run covers
  those backend refinements and the latest source-drift assertion.
- Final dashboard: **48 passed**; TypeScript and production build pass.
  `git diff --check` is clean. Frozen schema/fixture paths have no changes.
- Read-only inspection confirms the current live legacy blueprint matches its
  source/analysis binding. It is still a draft; the run is paused at Blueprint.

## Deployment and live verification

- Restarted only identity-verified, registered factory API/worker services after
  confirming no ready or active jobs. Final deployment at **20:16 UTC**:
  API PID **14565**, port **8100**; worker PID **14674**. Health and heartbeat
  verified; both private durable logs record service startup.
- Before/after hashes match for the entire reservation ledger, budgets and
  attempts, and for the paused run record. There are no new provider attempts,
  settlements, budget changes, run transitions or creative approvals.
- Browser verification: correct source `7udu-FBXoy8`, **29% (5/17)** progress,
  eight scene-review cards and eight reference-image identities. The review
  button opens the selected source and its existing approval controls without
  accepting it. The dashboard was left on Auto for review.
- Historical recovery report SHA256 remains
  `f17987c31c10410624210ecbe77a36e43727d129e1b589930f949e99fd5998ac`.

## Limits and live safeguards

No paid API call was used to qualify the new response schema. Offline tests
verify the request contract and strict response handling, not live model
accuracy. Structured output cannot ensure truthful scene descriptions.
Credentials may expire after preflight; unknown outcomes still require
evidence-backed reconciliation. TTS readiness checks configured key presence,
not the account's remaining live credits. Existing budget/quality gates remain.

No code in this patch automatically accepts a scene, releases an unknown
budget hold, raises a budget, reconciles unrelated historical operations,
publishes, schedules, or creates a final video. The finished-video upload rule
is not triggered by this task.
