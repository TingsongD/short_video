# Future-run safety and character continuity

Date: 2026-09-21. Implementation and offline verification report.

## Scope and protected state

New pipeline behavior is stored with future runs as workflow version 2,
`scene.v2` prompts and `visual.v2` QC. Legacy runs retain their saved policies.
Reference conditioning is separately gated and remains disabled for live use.
No paid provider request, publishing, budget increase, historical accounting
reconciliation or automatic job resumption is authorized by this patch.

The protected paused run is `auto-aae601ec5ca24ae1`, experiment revision 3.
Its four finals and the twelve earlier QA finals must remain unchanged. The
frozen `schemas/` and `tests/fixtures/` contracts have not been edited. Existing
unrelated worktree changes are preserved; this report does not claim them as
part of this change.

## Fixed in code

### Analysis, evidence and narration

- Editors are bound to seed, source hash, analysis revision and record version
  through a server-issued token. Mutations validate and write transactionally.
  Rapid selection changes clear stale editors; late replies are discarded and
  unsaved edits survive background progress refreshes, with an explicit reload
  notice when a newer revision exists.
- Future evidence is written to complete, immutable hash-bound bundles before
  publishing its database pointer. Legacy-to-future adoption is copy-on-write.
  Unavailable or corrupt recorded evidence is rejected, not replaced with a
  different revision. Worker checkpoints use the version originally loaded.
- Queued editor reruns validate the same analysis snapshot they execute. A
  checkpoint and its job-owned recovery binding commit atomically. Restarting
  may accept that job's own progress, but never intervening editor changes.
- Complete nested script responses are validated before draft/TTS creation.
  Missing variants, null/non-string copy and invalid beat bindings pause with
  an actionable error; future runs cannot silently resume with fallback copy.
  The original provider response remains diagnostic evidence.
- Valid passage text with defective word timestamps can reach the existing
  two-attempt local timing repair. Invalid transcripts/boundaries remain blocked;
  safe passage-only fallback is honestly labeled. Final captions still depend
  on replacement-speech alignment.
- Analysis recovery inspects relevant attempt history by operation identity,
  preserving unknown outcomes. Unchanged TTS is reused only after exact paid
  request validation, including future-workflow audit identity and original
  batch tag; a one-line repair does not repurchase all other lines.

### Authoritative QC

- Future visual verdicts bind the exact final artifact, composition revision,
  production revision, creative context and QC policy. One authoritative head
  references an auditable, preserved supersession chain.
- Recheck intent becomes pending before execution. Its completed pass, failure
  or uncertain result supersedes the prior result atomically. Pending checks
  block acceptance/delivery, and a superseded failure cannot defeat a valid pass.
- Compare, autorun, acceptance and delivery share the selector. QC intent uses
  the pinned revision; future QC cannot be downgraded during Resume. Explicit
  recovery from a terminal, proven-safe route failure can prepare a new QC job
  without reusing its failed cached job or replaying uncertain provider work.

### Execution, delivery and cleanup

- Future observation/download retries share one persisted bounded counter and
  backoff across restarts and endpoints. Retryable connection, throttling and
  supported server failures retain remote IDs, reservations and capacity.
  Authentication errors do not reset the counter. Submission timeouts remain
  unknown and are not automatically resubmitted.
- Split allocations use stable operation keys and exact request identities,
  not attempt sequence. Completed clips are collected in allocation order;
  ambiguous legacy mapping and unproven pre-acceptance failures pause. Prepared
  requests retain their original attempt and authorization on retry.
- Future delivery intent and queue identity persist atomically before transfer.
  Recovery uses the current receipt/job; verified results are reused only under
  the saved and configured account/destination binding. Lost acknowledgements
  and duplicate matches require reconciliation, never speculative replacement
  uploads. Delivery, QC, creative approval and cleanup remain separate.
- Failed listener inspection reports verification unavailable instead of
  declaring ports free. Actual cleanup results are retained, and unrelated
  processes are not stopped.

### Dashboard and creative context

- Deleted saved selections clear only that selection. Healthy collections and
  event updates continue when another resource fails. Publication detail derives
  from the latest record ID, so cancellation controls reflect current status.
- Analysis throttling/backoff appears as waiting with retry timing; the last
  successful refresh remains visible. Compare now calls its control **Linked
  seeking**, explicitly not synchronized play/pause.
- Versioned creative context records recurring roles, appearances, per-scene
  casting, wardrobe and allowed transitions. Scene-local prompts no longer
  require the same presenter everywhere or describe the entire video per clip.
  Source overlays are separated from physical scene instructions; incidental
  environmental text is not automatically rejected.
- Final QC receives the expected actions, roles, timestamps and allowed changes.
  Failure evidence must be timestamped and in bounds. It does not compare with
  an unseen generic control. The removed scene-approval gate is not restored.

### Gated reference conditioning

- The existing Google adapter supports an independently qualified `image_ref`
  route using `reference_to_video` and inline registered image bytes. Hash,
  supported image format and local size limits are validated; no public upload
  or new storage bucket is introduced.
  The payload follows Google's [reference-video documentation](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/video/generate-videos-from-references)
  and [Interactions API](https://docs.cloud.google.com/gemini-enterprise-agent-platform/reference/models/interactions-api).
  The 20 MiB image cap is a local guard, not a claimed provider limit.
- The first planned clip establishes each variant/role's reference and remains
  part of the final. Extracted frames require visual validation. Later scenes
  use those exact anchors; new-role introductions depend only on earlier roles.
  Anchors are never shared across variants.
- References, policy versions and clip provenance enter requests, quotes,
  identities and dependency invalidation. Mode-specific allocations and image
  input/validation estimates are quoted before execution; authority is checked
  when dependent work becomes runnable. Overlay checks precede anchor adoption.
- Missing/unreliable anchors, invalid references and uncertain operations pause.
  There is no silent text-only fallback or unbounded regeneration. Saved zero,
  one or two overlay repair limits are respected. Unresolved reference work
  blocks revision adoption; completed clips survive harmless edits only after
  exact paid-request checks, retaining original receipts.

## Verification

Test-first regressions exercise the agreed application/API, worker, provider,
delivery, cleanup and dashboard boundaries with offline provider transports.
Additional failures found during the full pass were fixed and rechecked,
including narration reuse identity and interruption-safe analysis checkpoints.

- Final complete offline backend suite: **1,419 passed in 1,085.30s**.
  The two actual-renderer tests were run separately, so total backend/local
  renderer coverage is **1,421 passed**, with no skipped renderer qualification.
- Frontend: final repeat **69 tests passed** across 14 files in 2.79s.
- Production TypeScript/Vite build: final repeat passed.
- Actual local renderers: **2 passed in 36.78s**, including a real Hypit build
  and FFmpeg final. Both exported 720×1280, 30-frame fixtures. Extracted frames
  were visually inspected for readable two-line captions and safe margins.
- Reference fixture journey generated twelve distinct clips, assembled four
  finals, then adopted a harmless revision without purchasing more fixture
  clips. Zero/one repair limits and unknown outcomes have explicit regressions.
- Mocked browser walkthrough completed: rapid seed switching, late responses,
  unsaved edits/newer-analysis notice, deleted selection, independently failed
  collection, waiting labels, linked seeking and refreshed cancellation controls.
  Fixture API/event traffic terminates in memory; it cannot submit live jobs.
- `git diff --check` passed. Frozen-schema/fixture diff is empty.

## Backup and rollout

A consistent SQLite online backup with integrity verification is preserved at
`data/factory-rollout-backups/future-safety-final-20260921/` (an earlier safety
snapshot is also retained). The directory is 0700;
database and sanitized fingerprint manifest are 0600 and ignored by Git.
The backup contained zero active jobs and sixteen verified final files.

The latest pre-rollout audit still matches the baseline for all eight protected
tables, final bindings and final bytes: 3,135 records, 645 jobs, 236 artifacts,
119 budgets, 505 reservations, 2,676 reservation lines, 408 attempts and 182
effect bindings. Record digest:
`30be157ec6fde2475040567ea92910f9f516aeb2aad6e52c91bf53f637cc3409`.
Final-binding digest:
`f9dfc43e939de1915450f5ef46cb1fb61f57a217ccd0237160f81ef4dbaa3bb6`.

**Fixed and rolled out locally after all offline checks passed.** Dispatch was
drained with zero active jobs. Only the verified API and worker were gracefully
stopped and restarted: API PID 14216 on port 8100, worker PID 14217. Health reports
API/storage OK and the new worker's current heartbeat. Process inspection shows
exactly one API and one worker in this checkout. All four application logs are
0600. Shared helpers were not stopped; the isolated QA preview on 8111 was
closed and the port checked free.

Post-rollout fingerprints match the backup exactly for all eight protected
tables, final bindings, job counts and all sixteen final file hashes. The
current run remains `paused / final_qc / final_qc_flagged`. Dispatch was restored
to its original undrained state only after a second zero-active-job check;
no paused or historical job was resumed. No rollback or database restore was
needed. Never restore an old database over newer activity.

The final read-only browser smoke check shows **Mode: live · Worker: running**,
the preserved four experiments, current run **Paused — Final quality check**,
and a current last-refresh timestamp. Its historical QC message remains visible
by design; this future-run patch does not rewrite or recheck that verdict.

## Deferred or unverified

- **Unverified, disabled:** live Google reference-mode payload acceptance,
  recovery, actual costs and character continuity. Offline fixtures do not
  qualify a provider route; a fresh, explicit live authorization is required.
  Reference corruption concurrent with provider submission remains a
  conservative unresolved outcome, not evidence of a free/no-effect request.
- **Deferred by scope:** synchronized playback and the minor Hypit/Node
  compatibility warning. The warning is not suppressed.
- **Unchanged by design:** current paused run, historical delivery statuses,
  historical holds/do-not-retry decisions, spending ceilings and publishing.
- No claim is made that prompts or automated visual checks eliminate all
  character drift or AI-quality failures.
