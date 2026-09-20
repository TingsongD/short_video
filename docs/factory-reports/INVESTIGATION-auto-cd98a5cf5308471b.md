# Last-run investigation: V3OAMVA8ULo

Investigated 2026-09-19 (America/Vancouver). Diagnosis only: no new provider
requests, production changes, queue mutations, or service restarts.

## Scope and conclusion

- Seed: `https://www.youtube.com/shorts/V3OAMVA8ULo`
- Run: `auto-cd98a5cf5308471b`
- Experiment: `exp-auto-cd98a5cf5308471b`, final revision 8
- Recorded execution: 2026-09-20 02:07–03:06 UTC, September 19 locally.
- Evidence: read-only SQLite records/events and provider receipts, local media
  probes, current code and its pre-existing working-tree changes, offline
  reproductions. No provider balance or invoice was fetched.

Four exports exist, but “succeeded” overstates the result. B has a failed
changed-region check, all four use identical copy and the same audio mix, and
the export dimensions differ. Automated final visual review was disabled.
These are reviewable drafts, not a validated footage-and-copy experiment.

The main failure chains are:

1. Invalid analysis times + unvalidated transcription → bad beat/copy allocation
   → paid speech that cannot fit → revisions/reuse and budget pressure.
2. Small source derivative used in production + output size inferred from the
   first shot → unequal export sizes → B comparison cannot execute.
3. Draft recovery and final completion do not enforce all experiment invariants
   → lost copy variations and a successful run despite a failed comparison.

## Findings against the ten reported issues

### 1. Low-confidence analysis: malformed timing was the actionable cause

The saved provider analysis covers only **0.00–0.40 seconds** of a **37.639-second**
source. Its six beats are 0–.08, .08–.14, .14–.22, .22–.33, .33–.37, and .37–.40.
The original blueprint therefore allocated only 2, 2, 3, 3, and 1 frames to its
first five beats, then almost the whole video to the sixth.

`analysis/analyzer.py:parse_analysis` checks shape, nonnegative increasing
endpoints, roles, and confidence, but not duration coverage or plausible beat
lengths. `autorun/review.py:build_sections` and `analysis/service.py:_build`
stretch the last beat to the source duration without bounding the correction.
The latter also extracts evidence frames at the original beat midpoints, so
the last evidence image comes from approximately .385s, not the long tail it
ends up representing.

The analysis prompt explicitly restricts confidence to `uncertain` or
`unresolved`; those labels alone are not proof of a model failure. The local
reviewer also requires boundary evidence and at least .4s per reviewed beat,
which these beats could not satisfy. Manual approval bypassed the pause; later
draft retiming did not repair the underlying analysis evidence.

**Status:** still reproducible. The particular reason the model emitted these
times is unknown; a unit/scale error is plausible, not established. Multiplying
all times by 100 would not be a justified repair.

### 2. LLM script failure: confirmed rejection, insufficient diagnostics

The script job failed with `malformed_analysis`. Its synchronous operation is
`sync-041b9398d2a496fcccca7a616e34c131`. The receipt remains `unknown`; there is no
saved `response.json` in that operation directory.

`analysis/vertex.py:_post` maps invalid JSON, missing candidate/content fields,
and any non-`STOP` finish reason to the same error. `_adapt_script` also uses
that error for a missing variants object. Consequently, **the evidence cannot
distinguish malformed JSON from truncation or another response-shape problem**.

`providers/synchronous.py` records an unknown receipt before the call, but only
saves the response after execution/parsing succeeds. The failure therefore
lost the detail needed to diagnose or reparse it locally.

Reservation `rsv:e89ddf2612114e95` remains ambiguous for **$0.25**, counted against
each applicable Vertex ceiling. This is one reservation constrained by multiple
ceilings, not separate charges. It needs evidence-backed reconciliation; it
must not simply be released or resubmitted on the assumption that nothing ran.

**Status:** deterministic fallback bypassed the script failure; provider outcome
and exact parser failure remain unresolved.

### 3. Poor fallback copy: defective upstream transcript and duplicate ownership

The local aligned transcript already contains **31 occurrences of “he used to
say”**. Its metadata says `language: en`; the separate video-analysis transcript
is Chinese. `bootstrap.py` constructs `ReferenceAnalysisService` without a
language override, leaving its default `en`, and `_stage_transcript` passes that
to transcription. Success is accepted from command exit/file presence without
language consistency, repetition, or semantic-quality checks.

This strongly suggests source/output-language confusion contributed, but the
exact transcription-model cause is not proven by a controlled rerun. An
aligned transcript is not necessarily an accurate transcript or translation.

`AutoRunService._transcript` prefers that local transcript. The original
overlap-based passage allocation repeated an opening passage across several
tiny beats. The pre-existing working-tree change to `scripts.beat_copy` is
incomplete: a passage starting in one beat can also be assigned to a later beat
containing its midpoint. A .5–1.5s passage is assigned to both 0–1s and 1–2s.

**Status:** final copy was manually made less repetitive; the upstream quality
gap and the passage-ownership defect remain. Fallback was not solely responsible
for inventing the repeated phrase—it inherited already-bad input.

### 4. TTS timing: impossible allocations, underfill, and stale repair text

Initial copy included approximately 11 words allocated to two frames. Later,
lengthening beats introduced the opposite problem: speech too short for the
allocation. For example, the saved raw b3 narration is 4.8s; the revision-2 b3
allocation was 10s. `fit_plan(4.8, 10)` rejects 5.2s padding against its 2s limit.
The same speech eventually fit a 6.5s allocation with 1.7s padding.

`audio/fit.py` permits at most 1.10× acceleration and 2s trailing padding.
Shortening every failed line is therefore not a valid general recovery.
The generated-copy word budget is not a sanity check on deterministic source
copy, and actual fit checks occur after synthesis.

`_repair_speech_fit` reverts to the cached `scripts_base` made before manual
edits. That source-derived fallback can be poor, still fail, or erase the
intended variant difference. The run notes record multiple such reversions.

**Status:** this run's speech was fitted by retiming, rewriting, and reuse. The
input checks and invariant-preserving repair behavior still need work.

### 5. TTS budget shortage: a local ceiling, aggravated by stale retries

Three pauses recorded the same quote: **844 credits required, 629 available**.
This is the factory's approved-budget accounting, not proof that the actual
ElevenLabs account had only 629 credits. Held reservations count toward it.

Budget-paused resume did not previously rebind TTS planning to the latest draft,
so edits could lead back to the same stale quote. Existing working-tree changes
extend revision reset to the budget-paused TTS path. The final batch required
557 additional credits, leaving 72 on the selected local ceiling. The stored
synthesis history has 14 distinct lines; the final experiment uses six.

**Status:** recovered for this run without increasing the ceiling during this
recovery. Reuse reduced new spend, but did not restore the missing copy tests.
Do not equate reserved amounts with reconciled provider invoices.

### 6. Video budget shortage: scope reduction, not full generation success

Revision 7's production quote was **$8.416430**, against **$6.772360 available**
on a selected Vertex ceiling. Revision 8's quote was **$2.807120** after seed
reuse. Selected ceilings each constrain the whole applicable amount; they
are not additive allowances.

The resulting plan reused the seed for A and unchanged regions, generating
three alternate regions: B's opening, C's body, D's ending. C's region was split
into two provider requests, so “three generated segments” means three logical
regions, **four billable video requests**.

**Status:** the budget gate behaved as intended. The workaround reduced the
deliverable's scope; it was not full fresh generation of every shot.

### 7. Seed resolution: a small derivative became the production source

Local probes show the downloaded original and H.264 derivative are **608×1080**;
`V3OAMVA8ULo-small.mp4` is **360×640**. The active source points to the small
derivative. Thus “the seed was only 360×640” omits the better local original.
Neither source has a 720-pixel short edge, but the small derivative unnecessarily
reduces available detail further. The reason it was selected is not established
by the media probes alone.

The requested-resolution gate correctly refused the small source; manual
acceptance did not improve its resolution. A second defect made outputs
inconsistent: `services/worker.py:render` gets the output width/height from
`pictures[0]`, rather than one frozen experiment output profile. Technical QC
then uses those same dimensions as its expectation.

**Status:** A/C/D are 360×640; B is 720×1280. Generated C/D portions were rendered
down to the smaller canvas; B's seed portions were upscaled. Therefore “seed
parts low-res, generated parts 720p” is not an accurate description of the final
encoded files.

### 8. Production-plan invalidation: required safeguard, stale resume was the bug

Changing seed reuse at revision 7→8 changes the work being purchased. The old
quote and authorization must not silently cover the changed plan. Requoting was
correct, not a fault in itself.

Previously, quote/authorization recovery could remain bound to the old revision.
An existing working-tree change now detects a newer draft, clears stale plan
references, and returns to quote. The run notes record that transition.

**Status:** fresh plan `plan-385c13769f13abfaab71f62e` completed the run. This
incident demonstrates the recovery path, not comprehensive regression coverage
for every interruption state.

### 9. One-frame render failure: container clock versus picture clock

The small source's picture stream has **1,128 frames / 37.600s**; its container
duration is **37.639s**, influenced by the audio stream. Blueprint construction
rounds that container duration to **1,129 frames at 30fps**.

The renderer already cloned a tail frame, but its earlier coverage check refused
the source before that padding could run. The pre-existing renderer patch
permits a shortage of at most one frame.

**Status:** independently verified locally: a 160-frame tail starting at 32.3s
now renders; a 161-frame tail is rejected. All finals contain 1,129 frames. This
recovery needs no paid regeneration. The upstream choice of authoritative
picture duration still deserves correction/explicit policy.

### 10. Duplicate workers: mixed process versions, not proven duplicate payment

The preceding recovery observed an older absolute-path worker and a newer
relative-path worker and stopped the older process. A stale process can continue
executing its already-imported code after a file patch.

The structural issue remains: direct `cli worker` startup has no singleton
guard, and `scripts/factory-up.sh` checks an absolute command-line pattern that
can miss a relative-path launch. The dashboard stores one shared
`worker_heartbeat`, which cannot expose every active worker/version.

**Status:** operationally recovered in the preceding run. Durable job history
does not prove two workers executed the same paid job concurrently; queue leases
exist. The evidence supports competing workers and stale-code retries, not an
assertion of duplicate billing.

## Two additional failures omitted from the earlier completion report

### Copy variation disappeared

Stored variant revisions show:

| Revision | B differs from A | C differs from A | D differs from A |
|---|---|---|---|
| 1 | No | No | No |
| 2 | b1 | b4 | b6 |
| 3 | No | No | b6 |
| 4 | b1 | b4 | No |
| 5–8 | No | No | No |

All finals share audio mix `art:ca0d4abaf738c9c6` and the same narration/caption
copy. Footage differences remain, but the requested wording test does not.
There is no effective final invariant requiring the declared copy change to
survive repairs and manual draft revisions.

### A failed required comparison did not prevent “succeeded”

| Variant | Artifact | Dimensions | Technical check | Unchanged-region check |
|---|---|---|---|---|
| A | `art:46b5fc9e3e4e76f9` | 360×640 | Pass | Control |
| B | `art:361523a638bab1b7` | 720×1280 | Pass | **Fail: missing evidence** |
| C | `art:75afa88f7d5bfbf7` | 360×640 | Pass | Pass |
| D | `art:ea3deff130fc422c` | 360×640 | Pass | Pass |

B's review `regions-build-3582a794433bc5c95ff929e7` expected 1,039 unchanged
frames and compared zero. Replaying even one unchanged frame returns FFmpeg's
“Width and height of input videos must be same.” This is a check that could not
run, **not proof that all of B's unchanged content actually changed**.

`worker.render` persists review results but returns `rendered` regardless of
their verdict. `_stage_final_qc`, when `visual_reviews=false`, calls `_finish`
without checking those technical/region verdicts. Disabling optional AI visual
review should not disable existing mandatory checks. The current method also
shortcuts on `qc_human_accepted`; a safe implementation must define which checks
an explicit human exception may override.

The run notes also say delivery is pending. No verified Drive delivery should
be inferred from `done`, and plan/footage acceptance is not final creative
signoff. Investigation did not alter delivery, publishing, or scheduling.

## Verification and evidence limits

Offline diagnostic probe:

```sh
.venv/bin/python docs/factory-reports/reproduce-last-run-issues.py
```

It intentionally exits 1 while these five defects remain: timing coverage,
single passage ownership, copy variation, consistent resolution, and failed
check blocking completion. All five failed reproducibly against this checkout
and the incident records. Its database connection is read-only.

Existing focused suite:

```sh
.venv/bin/python -m pytest -q tests/test_factory_rendering.py tests/test_factory_speech.py
```

**23 passed in 5.90s.** These are useful component checks, not evidence that the
five cross-stage defects are covered. A local one-frame/two-frame renderer
boundary check and a real A/B dimension-mismatch comparison were also replayed,
using temporary local outputs only.

Not established: exact provider finish reason/raw rejected script response,
actual provider charges/balances, the model's reason for bad timestamps, an
independent semantic validation of the Chinese-to-English copy, or duplicate
execution of the same paid operation. No extra paid calls were made to resolve
those uncertainties.

## Recommended implementation order

1. **Block false success:** require current-artifact technical/region verdicts
   independently of optional AI review; distinguish exports-ready, validated,
   accepted, and delivered states. Require declared copy differences.
2. **Validate before spending:** media-duration coverage, credible beat lengths,
   source-language detection versus output translation, transcript repetition,
   exactly-one passage ownership, and per-beat speech feasibility.
3. **Protect experiment intent during recovery:** rebind every paid stage to the
   latest draft; never silently revert repaired copy or remove a declared test.
   Reuse only genuinely identical text/voice inputs; preserve distinct changes.
4. **Separate analysis proxy from production master** and freeze the same output
   dimensions for all variants. Technical checks must target that independent
   specification. Do not merely hide the size mismatch inside the comparator.
5. **Improve operational diagnostics:** sanitized parser failure details and
   finish reasons, evidence-backed budget reconciliation, worker singleton or
   explicitly supported multi-worker/version tracking, and durable regression
   tests for the one-frame boundary and interruption/revision paths.

No production implementation was performed during this investigation. Existing
working-tree changes were preserved; this report and the offline reproducer are
the only new files from the investigation.
