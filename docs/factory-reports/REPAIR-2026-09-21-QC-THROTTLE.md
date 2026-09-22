# QC throttling recovery and run spending cap

Run: `auto-aae601ec5ca24ae1` · seed `89iXPZsKn9M`.

## Diagnosis

The clip review for C:b4 received an explicit analysis HTTP 429
`RESOURCE_EXHAUSTED`. This was not a failed video-generation request or an
authentication failure. Twenty generated clips were already downloaded.

The executor recorded a pre-acceptance rejection and released that request's
reservation, but the synchronous provider receipt remained `unknown`. The
worker treated the rejection as terminal. Plain Resume reused that failed job.
Assembly requires all four variants' pre-caption reviews, so pending C/D checks
also prevented A/B assembly. This dependency gate remains intact.

An offline real-adapter/executor reproduction initially failed because the
receipt was `unknown` after HTTP 429. Worker-level reproductions also failed
because the run stopped instead of deferring the review.

## Changes

- Persist identity-bound explicit 429 rejection receipts. Reconciliation can
  recover a crash after receipt persistence without another provider submission.
  Existing durable 429 failure events are not downgraded by old unknown receipts.
  Recording the rejection and releasing its reservation now commit atomically;
  exact saved receipts also recover a failed-with-held crash state.
- Analysis effects allow two additional attempts, with 30/90-second backoff.
  Attempt ordinals and rejection timestamps persist across restarts. Each new
  attempt uses a distinct receipt and reservation and revalidates existing
  quote, authority, revision, fencing and applicable ceilings.
- Never replay a timeout, unknown outcome, HTTP 500, or failed QC verdict through
  this path. Exhaustion gives a specific recovery message; Resume cannot reset
  the counter. No clips are regenerated merely because their reviewer was busy.
- Recover a previously terminal 429 job only when its failed attempt and released
  reservation match the durable explicit rejection evidence.
- Show analysis throttling as a wait in the run status bar.
- Add an explicit audited budget-tightening action, separate from top-ups:
  `POST /api/budgets/{id}/tighten`, with `ceiling`, `expected_ceiling`, `reviewer`
  and `evidence`. It preserves reservations/history, serializes with reservations,
  rejects stale updates and limits below committed amounts, and refuses internal
  authorization budgets.

Google's recommended response to capacity-related 429s includes bounded backoff:
[official guidance](https://cloud.google.com/vertex-ai/generative-ai/docs/provisioned-throughput/error-code-429).
This implementation deliberately does not extend retries to ambiguous outcomes.

## Applied spending authority

The user's latest request supersedes the prior unlimited allocation for this run.
`seed-89ixpzskn9m-20260921-usd` was reduced from $100 to **$50 cumulative** through
the audited service. At that point $17.660430 was held in estimates/reservations,
leaving $32.339570 available. These are not provider-confirmed charges.

The cap includes existing USD-priced analysis, generation, QC and repairs. It is
not a fresh $50 allowance for each operation. ElevenLabs' native-credit budget
is separate and unchanged. No new-run default or unrelated shared budget was
changed by this reduction. Publishing remains outside this authorization.

## Verification and rollout

- Focused offline safety/recovery set: 62 passed, including both crash windows.
- Final retry/overlay workflow set: 26 passed; original isolated reproduction
  passes. Read-only independent safety review found no remaining blocking issue.
- Frontend: 65 passed; TypeScript/Vite production build passed.
- Full offline backend suite: 1,368 passed across three file-disjoint shards
  (400 + 484 + 484; mocked providers and temporary data). The additional
  failed-with-held regression was added after collection and passes in the
  final 62-test safety and 26-test workflow runs (1,369 tests now collected).
- A sandbox-only run was stopped after local process supervision could not
  inspect its own process. The isolated process-recovery test passed with that
  permission enabled; no production behavior was weakened to satisfy the test.
- Before rollout, all twelve historical final files match their saved hashes.
  Historical final-binding digest:
  `cb280131b190232cb04f6c1a037c75dbd7a4311832b3319d59ec046ef433bce5`.

The idle queue was drained; only the owned factory API and single worker were
restarted. API/storage/worker health passed, log permissions remain 0600, and
the original undrained state was restored. All eight audit-table fingerprints,
all twelve final files and their bindings were identical across service reload.
No shared speech/preview service was stopped.

The run resumed with the $50 cumulative budget (and an additional $50 per-plan
ceiling). Its previously rejected C:b4 review succeeded on attempt 2 using the
same clip. D:b1 subsequently received another explicit 429, deferred for its
30-second backoff, and succeeded on attempt 2 automatically. Both original
failed attempts remain intact. All 20 current clips passed pre-caption QC;
the earlier rejected C:b1 clip's failure remains recorded separately.

The earlier overlay repair and its review consumed $0.635030 beyond the base
plan's shared QC allowance. Under the existing explicit shared-ceiling approval
and this run's current $50 cap, the four overlapping shared ceilings each
received that exact headroom adjustment (not four separate charges):

| Shared ceiling | New ceiling, USD micros |
| --- | ---: |
| `syp34-vertex-approved-4590780` | 92,373,040 |
| `syp34-vertex-approved-6886170` | 87,782,260 |
| `nffa1-live-test-20260920-usd` | 70,971,330 |
| `7udu-approved-20260920-usd` | 62,336,690 |

All four revision-3 videos were then assembled and are visible in Compare for
`exp-auto-aae601ec5ca24ae1`. Final visual QC completed: D passed; A/B/C failed
character continuity. The run is now **paused at `final_qc_flagged`**, not at
the original provider-throttling failure. No creative approval, QC bypass,
additional final-QC recheck, or Drive upload was performed to clear this pause.

## Remaining creative-quality finding

There are two distinct issues; the failed reviews cannot safely be blanket-cleared:

- The saved source blueprint intentionally has a woman against a space
  background in b1 (0–3 seconds), followed by a man in a workshop in b2–b5.
  The generation style nevertheless asks for one consistent presenter, and
  full-video directions ask for global character/setting consistency.
  Final QC likewise asks for global coherence but receives only narration,
  factor and hypothesis, without the intended cast, scene transitions or timing.
  B's review objects to a transition already present in the source blueprint.
- Local frame strips from all four actual exports show presenter appearance
  changes between some workshop shots. A/C also start with a workshop presenter
  rather than the source's woman/space hook. Thus there is actual visual drift
  as well as insufficient review context. D's automated pass is not a guarantee
  of perfect continuity. Frame sampling is diagnostic, not an exhaustive review.

The next repair should make continuity role- and scene-aware, include the saved
visual intent and timing in QC, and preserve recurring-character references in
generation. It must retain the recorded verdicts and exact artifact bindings;
neither rerunning an unchanged review until it passes nor labeling AI acceptance
as human approval is an appropriate fix. This broader creative-continuity repair
is not implemented by the throttling patch.

At the final check, the run has $20.410430 in held estimates/reservations and
$29.589570 remaining below its $50 cap. The two rejected analysis reservations
totaling $0.50 are released; no provider-confirmed spending is inferred from
these estimates. ElevenLabs' separate credit budget is unchanged.

Post-recovery verification: SQLite integrity check passes; all 16 current final
bindings match their local bytes; the 12 historical final-file hashes are
unchanged from the pre-rollout snapshot. Application logs retain owner-only
permissions. Shared dashboard/worker services remain available. Delivery and
video-owned completion cleanup remain pending final QC; publishing is disabled.

No paid request was made during diagnosis or offline tests. Live recovery uses
the user's current spending authority. No historical hold was erased, and no
human creative approval was fabricated.
