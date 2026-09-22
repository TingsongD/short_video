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
| Truncated/malformed audiovisual analysis | Existing recovery needing generalization | **implementation complete; end-to-end check running** | Future runs may automatically plan the existing bounded saved-response recovery for completed capped responses. The original identity/hold remains; HTTP 500 and other unknown outcomes are not replayed. Broad unattended qualification is not yet established. |
| Unknown provider outcomes and financial holds | Operational/provider limitation | **preserved** | No old request is replayed and no hold is erased. Capacity and accounting remain separate. |
| Incomplete editorial plan | Confirmed automation gap | **fixed offline** | Strict validation runs first. A completed invalid plan may fall back only to conservative source-bound coverage and exact observed cuts with unambiguous variant ownership and clip ranges. Unsafe conflicts, invalid JSON and unknown outcomes still pause. |
| Character continuity / reference-conditioned generation | Qualification gap | **offline implementation present; live route disabled** | Per-variant anchors and reference identities require separate authorized live qualification. |
| Jev quality/cost benefit | Measurement gap | **open** | Shadow results do not prove benefit. Labeled benchmark and enable/disable criteria remain required. |
| Genuine flash-cut, VFR, silence/callback fixtures | Qualification gap | **partially covered; audit pending** | Existing synthetic tests and benchmark code require consolidated evidence. |
| Temporal motion/lip-sync inspection | Quality limitation | **open** | Sampled visual review is not exhaustive temporal validation. No lip-sync feature is promised. |
| Full backend/frontend/local-render release gate | Qualification gap | **running** | Frontend: 72 tests and production build pass. A clean complete backend result and the current real PE/native-Hypit end-to-end check are still pending; failures seen in an overlapping long run are not a release result. |
| Historical archive/clearing | Safeguard, not defect | **preserved** | Protected/unresolved records are not deleted or silently settled. |

## Completed focused checks

- Backend future-policy, budget-selection and editorial-planning checks: 33 passed.
- Narration repair success, second-attempt, budget-refusal and unknown-outcome
  checks: 4 passed.
- Dashboard future-policy checks: 6 passed.
- Complete dashboard suite: 72 passed; production build passed.
- No network or paid provider was used by these checks.

These focused counts overlap the eventual full suite and must not be added to
it as a release total.

## Rollout state

Not deployed. No API or worker restart has occurred in this hardening cycle.
The next gates are the current real PE/native-Hypit integration result, a clean
complete backend suite, actual local Hypit/FFmpeg render evidence for the final
code state, protected-state comparison, qualification matrix and a separately
quoted live-only acceptance checklist. Tests alone do not establish unattended
production readiness.
