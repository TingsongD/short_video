# AVvVLM5b-mE — evidence-only continuation

Current outcome and remaining-work index: [current handover](FLASHCUT-CURRENT-STATUS.md).
This report retains the detailed recovery and completion evidence below.

2026-09-22. The user authorized autonomous continuation to Compare within the
existing cumulative $50 run cap, without routine approval questions. No
publishing, extra accounts, overage or historical reconciliation is authorized.

## Findings

The failed shared clarification is still unknown, with its reservation intact.
It is not retried. Twelve missing-coverage flags refer to context outside the
individual window requests, although the successful whole-video response has
source-cited observations covering those intervals. Resolution now records the
supporting response/request hashes and observation IDs, preserving all original
provider answers instead of editing away their flags.

This recovery is opt-in and saved for this run. In-window questions, uncertainty,
uncovered intervals, changed source bindings, text-only descriptions and
semantic visual-change candidates cannot be cleared by generic scene coverage.

One semantic candidate remains: `visual:181`, at 181/30 seconds. Codex inspected
source frames 179–184, including the exact registered adjacent frames 180–182:

- The same tabby-and-white cat, patterned bed and Chinese caption persist.
- The owner's hand withdraws while the view reframes closer around 6.033 s.
- This does not introduce another cast member or setting. It is retained as a
  local observation of reframing, not treated as a human approval or a Gemini
  result. No claim of stable identity in generated footage follows from it.

Inspection grid:
`/private/tmp/factory-flashcut-acceptance.sAinMF/visual181-evidence.jpg`.
Local evidence binds the candidate, exact registered image hashes, source
binding, original frozen plan, assistant reviewer and observation text. No new
scene-review gate is introduced. Unsupported visual claims stay unresolved.

## Safeguards and checks

- Unknown operations, reservations, historical outputs and old responses remain
  unchanged. No analysis request is added by this recovery.
- Public coverage-resolution checks plus existing focused regressions:
  **105 passed**. Existing gap/server-error end-to-end checks: **2 passed**.
- Pre-deployment snapshot `before-context-reuse` reports zero active jobs and
  all 16 historical final hashes intact.
- Live continuation and final delivery results will be recorded below.

## Live continuation: narration and editing

- Context recovery advanced the current run to scripting. Local English ASR had
  mistranslated the Chinese source; its opening incorrectly made other cats
  combative and its timestamps misplaced the final joke. The saved audiovisual
  Chinese transcript preserves the correct cuddle/fight/height/bag sequence.
- The initial narration's second segment measured 6.72 seconds against a
  three-second beat. Its bounded rewrite returned unusable. That completed
  request and repair count remain recorded.
- Codex applied an explicitly assistant-authored correction in draft revision 2,
  preserving the immutable source analysis and prior script in an audit record.
  Short complete English lines restore the source's joke. Distinct B/C/D copy
  and scene-local actions were preserved. This is not a human approval.
- All 16 replacement narration segments passed fitting; one unchanged line was
  reused. The attached final speech advanced the draft to revision 3.
- The provider's editorial request returned an incomplete answer; its unknown
  accounting remains held and it was not resubmitted. Codex authored an
  independent validated editing plan over the same final-speech binding. All
  35 observations are accounted for. No cuts were observed in this continuous
  source, so four semantic scenes are retained without fabricated microcuts.
- Two earlier HTTP-200 completed responses released execution capacity through
  existing evidence-checked recovery. Their financial holds remain unchanged.
- Production plan `plan-b5bacbdfbce9dfbecb0f2b63` quotes 16 unique footage takes,
  no cross-variant sharing, estimated $8.694480. Cumulative run authority stays
  $50 plus the existing 10,000 prepaid TTS-credit ceiling; no overage changes.
- Backup `before-narration-correction` verified 16 protected final hashes with
  zero active jobs. The coverage regressions were rerun: 11 passed.

## Local assembly recovery

All 16 footage takes downloaded successfully. Assembly then exposed a real
native Hypit compiler defect: `audio:Item.trim-end="14.133333333333333s"`
exceeded Hypit's safe arithmetic. The compiler now emits exact frame endpoints
for the validated full-program native premix, leaving legacy authoring unchanged.
A mismatched native premix endpoint is rejected instead of silently adjusted.

The 31-frame public compilation regression failed with the same Hypit diagnostic
before the fix and passed afterward. Focused coverage: **36 passed**, including
actual 30/31-frame Hypit renders at 180×320 and 720×1280, microcut frame positions,
single-premix audio and FFmpeg compatibility. An initial sandboxed render attempt
failed on local `listen EPERM`; the suite was rerun with local-service access.
No hosted providers are used by these offline tests.

Snapshot `before-frame-trim` preserves all 16 historical final hashes. Its six
nonterminal jobs were only dependency-waiting downstream work; no active executor
was interrupted. Owned API/worker restarted, then the explicit local-retry action
reopened A's failed assembly. No paid generation was retried.

## Completed finals and delivery — 2026-09-22

Run `auto-2c9de6ddf2e34d5c` succeeded. All four revision-3 finals are
720×1280, 424 frames, 14.133333 seconds and load in Compare without media errors.
Full FFmpeg decoding passed; final audio/premix correlations exceed 0.99947.

B's first visual review incorrectly required the source's Chinese subtitles.
The review prompt now explicitly distinguishes reference-only source overlays
from intentional replacement captions (`replacement_captions.v1`). Its public
payload regression and related review/context/quality tests passed: 31 tests.
After an idle consistent backup (`before-qc-text-policy`, 20 matching finals),
only owned API/worker services restarted. A fresh B review passed through normal
quoted execution; no video was regenerated and no human approval was fabricated.
The original failed verdict and unresolved provider accounting remain preserved.

All four deliveries verified filename, parent, size and MD5 in the run's saved
`factory-deliveries` destination `1dDy1kKvQI8gio3k1oOjgqeIepjZnyiLM`:

- A: https://drive.google.com/file/d/1MmCyzJ9niKhk4tC9gV7Bn1mFSj03QI3D/view
- B: https://drive.google.com/file/d/1-7vK07UahK_6oQ5qOU93ajdGAu0yB5DT/view
- C: https://drive.google.com/file/d/1XLg15mV6lVESdhb9uJs6xFgoCiXLpBYk/view
- D: https://drive.google.com/file/d/1LxRgUFqB6ncMf1slQ_L48tsMRWhsxPha/view

Per-video cleanup receipts verify no survivors and freed ports 55586, 55711,
55855 and 55984. Shared dashboard/worker and unrelated services remain available.
Nothing was published or scheduled. All 16 historical final bindings/hashes and
protected records, jobs, attempts, assets, reservations and effect bindings remain
unchanged. The audit's five budget-row differences are the previously approved
ceiling changes, not this QC patch. This focused recovery did not rerun the entire
backend/frontend release suite; sampled visual review is not exhaustive motion QA.
