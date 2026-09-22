# Future-run hardening tracker — 2026-09-22

This is the implementation tracker for the post-`AVvVLM5b-mE` hardening
cycle. It excludes Chinese-language recognition, translation and transcription
changes. No paid request, video regeneration, publication, historical hold
release, budget increase or deployment is authorized by this document.

Baseline snapshot: `/private/tmp/factory-hardening-baseline-20260922` recorded
zero active jobs, 20 protected finals and matching final hashes. The working
tree already contained unrelated changes; they are being preserved. Frozen
schemas and fixtures are unchanged.

## Status by finding

| Finding | Class | Status | Evidence / limitation |
| --- | --- | --- | --- |
| Persistent per-run $50 USD default | Confirmed defect | **fixed offline** | New runs save an isolated `cumulative_run` policy and run-owned budget. Holds, ambiguous outcomes and settlements count. Resume cannot drop/adopt guardrails. Applicable stricter ceilings still apply. |
| Budget/accounting explanation | Existing behavior needing clearer UI | **fixed offline** | Run status shows cap/committed/remaining; run guardrails are separated from reusable funding. |
| First completed narration rewrite is unusable | Confirmed defect | **fixed offline** | Receipt is retained and a distinct second bounded attempt may run; counters survive restart, unchanged speech is reused, and unknown outcomes still pause without replay. Focused success, exhaustion, budget-refusal and unknown-outcome checks pass. |
| Truncated/malformed audiovisual analysis | Existing recovery needing generalization | **fixed offline; focused end-to-end passed** | Future runs may automatically plan the existing bounded saved-response recovery for completed capped responses. The original identity/hold remains; HTTP 500 and other unknown outcomes are not replayed. Broad unattended qualification is not yet established. |
| Dense-source provider payload and candidate limits | Confirmed preflight defect | **fixed offline; three-source preflight passed** | Future `flashcut_policy.v3` packages timestamp-bound JPEG frames, compressed audio-bearing windows and a capped overview. `flashcut_analysis_plan.v2` partitions measured candidates by window without dropping any. Legacy evidence keeps its saved policy. All-frame coverage and request limits passed on 1,869-, 635- and 423-frame retained seeds; live Gemini payload acceptance remains unqualified. |
| Unknown provider outcomes and financial holds | Operational/provider limitation | **preserved** | No old request is replayed and no hold is erased. Capacity and accounting remain separate. |
| Google credential readiness | Existing fix needing regression coverage | **already fixed** | Non-billable readiness blocks before a plan or reservation; categorized recovery messages retain resumable work. Authentication may still require the user to sign in. |
| Incomplete editorial plan | Confirmed automation gap | **fixed offline** | Strict validation runs first. A completed invalid plan may fall back only to conservative source-bound coverage and exact observed cuts with unambiguous variant ownership and clip ranges. Unsafe conflicts, invalid JSON and unknown outcomes still pause. |
| Character continuity / reference-conditioned generation | Qualification gap | **offline implementation present; live route disabled** | Per-variant anchors and reference identities require separate authorized live qualification. |
| Jev quality/cost benefit | Measurement gap | **measured; active mode remains unqualified** | Three exact-source shadow responses retained all 78 optional candidates. No selection or net-cost benefit was observed. A self-verifying nine-case gate now rejects hand-written qualification. |
| Genuine flash-cut, VFR, silence/callback fixtures | Qualification gap | **fixed offline** | The 26-test helper matrix covers two-frame events, continuity, callbacks, quiet boundaries, VFR, silence, weak/clear rhythm and AV disagreement. This does not replace multi-seed live qualification. |
| Temporal motion/lip-sync inspection | Quality limitation | **partially fixed offline** | Future v2/v3 finals check all decoded PTS, final-speech caption schedules and required brief intervals. Semantic event identity, pixel OCR and lip sync remain explicitly unverified. |
| Slow provider operation visibility | Existing fix needing clearer UI | **fixed offline** | The run shows the saved operation ID, elapsed time, last successful observation and next scheduled poll. Observing a slow request does not submit another copy. |
| Exact-frame Hypit premix and replacement-caption QC | Existing fixes needing regression coverage | **already fixed** | Native/FFmpeg paths use the frozen premix; final QC distinguishes source overlays from intended replacement captions and binds the verdict to the current artifact/revision. |
| Full backend/frontend/local-render release gate | Qualification gap | **fixed offline; deployed** | Complete backend: 1,573 passed, 7 skipped; frontend: 73 passed and production build passed; helper: 27 passed; explicit real-render gate: 16 passed with no renderer skips. One API/worker pair is healthy after the idle rollout. These checks do not establish general live-provider quality. |
| Historical archive/clearing | Safeguard, not defect | **preserved** | Protected/unresolved records are not deleted or silently settled. |
| Safe history visibility | Existing fix needing regression coverage | **already fixed** | The UI can hide eligible historical entries without deleting their records; active or newly unresolved work remains visible and obligations stay discoverable. |

## Completed focused checks

- Backend future-policy, budget-selection and editorial-planning checks: 33 passed.
- Narration repair success, second-attempt, budget-refusal and unknown-outcome
  checks: 4 passed.
- Dashboard future-policy checks: 6 passed.
- Complete dashboard suite: 73 passed; isolated production build passed.
- Complete isolated helper suite: 27 passed.
- Jev route and self-verifying benchmark gate: 8 passed. The retained live
  shadow evidence is unqualified: one of nine cases, 0/78 candidates removed.
- Future temporal policy/quality checks: 21 passed; one actual offline
  A/B/C/D native-Hypit path passed in 219.46s.
- Complete backend suite: **1,573 passed, 7 skipped in 38m30s**. Its real
  new-profile end-to-end cases exercised all-frame local PE analysis,
  mocked provider transport, four native Hypit finals, bound QC and mocked
  verified delivery. The separate actual local Hypit/FFmpeg renderer gate:
  **16 passed in 3m21s**, no renderer skips. The seven skipped helper modules
  require the separate Python 3.11 media environment; that complete helper
  suite passed there (27 tests), so they are not unrun required checks.
- No external or paid provider request was used by these checks; local
  renderers and test clients may use loopback IPC.
- Three isolated, unpaid full-source preflights verified the future compact
  analysis plan against the retained rapid-cut, short edited and continuous
  seeds. They require 10, 4 and 3 initial Gemini requests respectively;
  exact dated stage-one estimates and remaining live-only checks are in the
  [separate acceptance document](FLASHCUT-LIVE-ONLY-ACCEPTANCE.md). No provider
  request was submitted, and these are not A/B/C/D production quotes.

These focused counts overlap the eventual full suite and must not be added to
it as a release total.

## Rollout state

Deployed to the local checkout on 2026-09-22 after a consistent owner-only
SQLite backup at `/private/tmp/factory-hardening-rollout-20260922-release-01`.
It reported zero active jobs, 20 final bindings and matching final hashes.
Only the owned API and worker were stopped; shared `hyperframes.local` and
`media.local` programs were left running when ownership could not be proved.
The production dashboard bundle was rebuilt while the API was down.

The detached launcher reported a healthy start but its subprocesses exited
with the tool process. The API and single worker were then started in persistent
sessions using this checkout's absolute interpreter path. Verification found
`/api/health` healthy, one API and one worker, the new dashboard asset served,
three local helper programs ready, and owner-only (`0600`) API/worker logs and
PID files. Four exact test-only Hypit workers left by interrupted older tests
were stopped through their own workspace runtimes; unrelated programs were not
stopped. No paused historical run was resumed.

The post-rollout protected-state comparison matches the baseline: **all 20
final-file hashes** and all 339 artifacts, 478 attempts, 155 budgets, 252 effect
bindings, 794 jobs, 3,652 records, 3,059 reservation lines and 571 reservations
show zero modified or missing protected rows. Historical financial holds remain
unresolved. The qualification matrix is [recorded here](FLASHCUT-QUALIFICATION-MATRIX.md).
The remaining multi-seed live checks require the separate fresh quote and
authorization in [FLASHCUT-LIVE-ONLY-ACCEPTANCE.md](FLASHCUT-LIVE-ONLY-ACCEPTANCE.md).
Offline release gates do **not** establish unattended production readiness.
