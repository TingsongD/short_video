# Restarted three-round QA — qyaE7GaUVGI

User authorized unlimited spending for exactly three fresh sequential QA rounds after a backed-up reset. No scheduling or publishing. Historical requests are closed/do-not-retry and excluded from these rounds; their accounting remains unchanged. See `QA-RESET-ACCOUNTING-2026-09-20.md` for reset and provider validation evidence.

## Requirements

Each round must produce playable A/B/C/D finals in Compare, verify close-mimic A and declared B/C/D copy and footage differences, TTS replacement, caption and narration timing, technical properties, persistent UI state, backend logs, and final Drive delivery. **Final verdict: PASS with the documented generated-media limitations.** Exactly three runs and twelve verified finals completed; final offline suite and frontend checks passed. Chronological pending/blocked entries below describe past checkpoints, not current status.

| Round | Run | Status | Outputs | Verdict |
| --- | --- | --- | --- | --- |
| 1 | `auto-8608da8a08644aa8` | Complete, revision 5; audit and verified CLI delivery complete | A/B/C/D, links below | Pass with documented generated-media limitations |
| 2 | `auto-8182bae593894e93` | Complete, revision 2; audit and verified CLI delivery complete | A/B/C/D, links below | Pass with documented generated-media limitations |
| 3 | `auto-5b10280f1fc84a64` | Complete, revision 3; playback, reload, delivery and cleanup verified | A/B/C/D, links below | Pass with documented generated-media limitations |

## Round 1

- Created through the dashboard Auto controls at 2026-09-20 23:05 UTC.
- Exact seed: `https://www.youtube.com/shorts/qyaE7GaUVGI`; source ID `seed-youtube-991b37f63be3d124`.
- Explicitly reused only the verified original source MP4, not old analysis or generated outputs. Imported through the public API with SHA-256 `68ea8e9c737ff8a7fc6b4fa74964b1019f945a8eda0f9ce6ea4ce4090feb811c`, artifact `art:68ea8e9c737ff8a7`.
- Dashboard Latest run region verified correct source URL, new run ID, running evidence stage, 1/17 (6%), and automatic five-second refresh.
- Voice `cgSgspJ2msm6clMCkdW9`, English; AI scene review and final visual QC enabled. Generated music disabled.
- New accounting envelopes `qa-restarted-20260920-r1-usd` ($25) and `qa-restarted-20260920-r1-tts` (10,000 credits), adjustable against quotes under the user's unlimited three-round authority. These are ceilings, not actual charges. Existing aggregate constraints and historical holds remain enforced.
- Provider readiness checks passed before starting. ElevenLabs subscription readback showed 44,805 credits remaining; no claim this covers all three rounds before quotes.
- Existing dirty source changes preserved. Previous QA reports remain historical and do not count as restarted-round completion.

### Analysis and review outcome

Initial analysis and both AI scene-review requests succeeded. At 23:07:37 UTC, the run paused with `ai_scene_review_unresolved`: verification rejected scene 8's claim of a horse "accidentally biting her head" as overstated. Its supported observation is that the horse's mouth approaches the laughing woman's head while reaching for an apple; actual biting is unclear. This is content disagreement, not a transport/authentication failure. No automatic override or additional paid retry was submitted.

The dashboard correctly shows the same run/seed, 29% (5/17 stages), the specific disagreement, and both Manual fix and Proceed anyways. No TTS, footage generation or finals yet. Later rounds remain unstarted.

Three new reservations are held at USD 0.25 each, USD 0.75 estimated total, not confirmed invoices: `rsv:06c97395ce8d4e11`, `rsv:1ff9d8bb76574976`, `rsv:8838b68869d54898`.

Offline verification during this run: selected AI review/unknown/incomplete-response safeguards **15 passed**; authentication, analysis timing recovery, run prevention and history protection **91 passed**. Two dependency deprecation warnings only. These tests do not establish finished-video quality. No new code defect was established by the model disagreement.

## QA continuation — 23:40 UTC onward

The active goal reuses this cycle and its existing Round 1, not three extra runs.
The preceding prompt-writing turn did not execute QA; this continuation makes
live progress. API PID 69479 and the sole worker PID 69538 were verified healthy
through `/api/health` and process inspection. The dashboard verified the exact
seed and run before normal Resume at 23:40:49 UTC. Blueprint preparation passed
without another scene-review request. Script adaptation completed in LLM mode,
then TTS synthesis and local fitting ran. At 23:41:49 UTC the run paused on
`speech_fit_failed`: source-derived A:b1 could not fit at the selected voice's
pace. Nothing has been scheduled or published. No finals yet.

### Initial issue register (historical; current dispositions below)

| ID | Evidence / cause | Repair and verification | Status |
| --- | --- | --- | --- |
| QA-R1-01 | C:b6 was cut from 16 to 11 words and ended `as butter is spread in`. `_merge_llm_scripts` sliced words, and the script request did not include its numeric word limits. | Added numeric per-beat limits, whole-sentence retention or valid source-derived treatment, and one durable separately quoted rewrite when neither fits. Three exact regression tests failed before the patch; five focused tests now pass including bounded rewrite success/failure through the application. Broader tests and live verification pending. | Fix under validation |
| QA-R1-02 | Measured speech fit failed for A:b1 and b9; source-derived fallback still failed. Existing recovery reused nine unchanged narration lines rather than charging them again. | Inspecting source timing, voice duration, and concise source-grounded copy. Do not loosen rate or duration checks. | Open |
| QA-R1-03 | Local aligned transcript assigns `Excuse me, sir.` 7.714–10.376 seconds across the 8-second cut; `Are you fucking serious?` spans 48.875–58.016, with `you` alone at 49.035–56.656. Whole-passage start ownership puts these in the preceding scenes. | Preserve complete timed words and assign whole sentences by a unique word-count majority; ties/incomplete evidence retain legacy ownership. Long-word anomalies remain explicit warnings, not repaired alignment claims. Real transcript replay puts both lines in the intended scenes without dropping text. | Offline verified; deploy after live generation is idle |
| QA-R1-04 | Operator guide still contains retired `Accept source timing` directions and AI scene-correction claims outside its updated removal section. | Reconciled obsolete instructions and copy-provenance wording with current behavior. | Fixed |
| QA-R1-05 | Production authority used run account `sentientweb1` (Canvas) for Vertex, whose configured OAuth account is different. Live Vertex correctly rejected the binding before HTTP submission. | Added production authorization account validation. Resume can select only the configured generation account, requiring a new draft before replacing existing production authority. | Offline checks pass; live recovery pending |
| QA-R1-06 | `_stage_footage` reopened `authority_required` / `reservation_identity_conflict` picture failures on every tick, despite its "once" comment; `_jobs` mislabeled them budget exhaustion. | Removed automatic paid-job reopening; these failures now pause with account/authorization recovery guidance, not a top-up message. Regressions exercise repeated ticks. | Offline checks pass; live recovery pending |
| QA-R1-07 | Draft recovery cleared the old plan but retained `run_job`; its pending-work guard inspected `production_jobs`, while actual production DAG jobs were not necessarily stored in that list. | Invalidate old dispatch job and inspect the old plan's durable job IDs before rebinding. | Focused regression passes |

The five new tests are offline with mocked providers. They do not establish
finished-video quality or completion of any round. All issue closure gates,
12-final verification, Drive delivery, cleanup, and later rounds remain open.

Focused validation expanded to **6 passed, 27 deselected** (23.59s), including
the existing measured-fit/TTS-reuse scenario. A sandboxed render-test attempt
waited in the owned-process supervisor without a child renderer; interrupted
only that test PID and reran outside the sandbox with mocked providers. The
live API and worker were not interrupted. A broader offline suite is running.

Saved draft **revision 3** through the dashboard Plan editor: shorter A:b1,
shorter truck narration b9, the source's AirPod reaction restored to b11, and
a complete nine-word C:b6 sentence. Unchanged branch copy follows A, while
B:b1 and D:b11 treatments remain intact. Scene durations and voice are unchanged.
The run remains paused pending test completion/deployment and Resume; this is
an actual draft repair, not a claim that fresh narration or finals passed.

Broader verification: **59 passed** (322.64s), covering Auto, the new copy
quality tests, run prevention and scene-review removal; **21 passed** on the
final focused copy/prevention rerun; dashboard progress/recovery/removal tests
**7 passed**. `git diff --check` and Python compilation passed. The known two
dependency deprecation warnings remain. QA-R1-04's obsolete instructions were
corrected, including the guide's LLM-versus-deterministic copy description.
Reloading idle owned services only after these checks; live verification of
QA-R1-01/02 still pending.

At 23:53:45 UTC, idle API/worker reload completed (PIDs 35519/35578);
jobs, attempts, run records, reservations and reservation lines hashed
identically before/after reload. Health confirmed one live worker. Normal
dashboard Resume adopted draft revision 3. The run reused **7 unchanged
narration lines**, bought only changed lines, passed measured fitting, and
attached **33 spoken segment occurrences / 11 unique current lines**. By
23:54:40 UTC it advanced through quote and authorization to production
dispatch. QA-R1-02's live blocker is repaired; QA-R1-01's complete C line
also passed fitting. Final playback and the upstream alignment prevention
issue remain unverified. No extra QA run or scene-review request was created.

### Footage authority failure and containment

Plan `plan-7e73bd9b33b73a875ef03402` encountered account-binding failures.
The automatic reopen defect produced **238 failed local attempts across 14
picture jobs** before containment. Their 238 `submit_failed` events all report
`authority_required`; all are terminal failed and their reservations are
released. The live Vertex guard raises that error before submission-state
creation or the HTTP request. This is code-path evidence of local rejection,
not a claim about a provider invoice. Historical closed requests are untouched.

Drained dispatch at 23:55:47 UTC; stopped only the owned worker at 23:58:43 UTC
to prevent further old-code retries. The API remains accessible. The plan's
14 picture jobs are failed, 26 descendants blocked. No successful remote video
operation or final exists. A new worker is being started with dispatch still
drained so the fixed code can surface an honest pause. No old failed request
has been manually requeued.

New authority/loop tests reproduced all three failure assertions before fixes.
After repair, authority + production + effect + run-prevention selection:
**43 passed**. Additional account-resume and dispatch-invalidation coverage
plus prevention: **21 passed**. Release regression suite is running outside
the sandbox; its sandboxed attempt was interrupted after local-process failures.

Release suite outside the sandbox: **22 passed** (107.59s). Deployed API PID
58907 and sole worker PID 58969 at 00:03:33 UTC (September 21), with durable
jobs/attempts/runs/accounting unchanged across reload. Confirmed all old plan
jobs were failed/blocked before clearing drain. The fixed worker then paused
the run with actionable account/authority guidance, not a budget top-up prompt.

Saved **revision 5** through the dashboard, preserving all fitted speech and
captions from revision 4. Also replaced b8's unsupported biting claim in each
variant's footage prompt with the earlier source-supported apple-reaching
description. No new scene-review gate or request was introduced. Resumed via
the public API with the configured Vertex account (rather than the Canvas
account); the audited account update returned `running / quote`. The old
238 failed attempts remain terminal and unchanged. Final verification pending.

At 00:05:21 UTC, plan `plan-b7b37e461fdb2d7b9c46e3e9` has one confirmed
remote Vertex operation in `running`, with its durable download/poll job active
and 13 remaining picture jobs queued under one-operation concurrency. The
dashboard shows Footage generation, 13/17 stages (76%). This is a verified
live wait, not an assumption based on a lock file. No render/final yet. Next:
poll this same plan/operation, do not resubmit; continue the round and its
mandatory after-run fix/audit gate before creating Round 2.

## Continued verification — September 21

QA-R1-03 reproduced with two failing ownership tests before the patch. The
new assignment uses complete matching word text and valid finite in-passage
bounds only. Each word votes once, so a seven-second alignment interval cannot
dominate by duration. Sentence text is not split, dropped or duplicated.
Four focused tests pass, including the actual Auto transcript-loading boundary;
the earlier combined copy/prevention selection passed 24 tests. Replay of the
real saved transcript assigns the deer line to b2 and the AirPod reaction to
b11, preserving all text and reporting the long-word anomaly explicitly.
The patched script stage has not been hot-reloaded into active generation.

Generation continues on the same plan and operation identities. Preliminary
inspection of the first downloaded eight-second clip's frame grid confirms
moving generated farm footage: a presenter followed by the black calf lying
in a pellet trough. No overlay text or black/frozen frames visible in the
sampled grid; this is not final-video QC. A full offline `make test` run is
also in progress while the provider completes footage.

### QA-R1-08 — final visual-QC input exceeds inline limit

Continuation inspected live durable state: Round 1 is paused at `final_qc`
with `analysis_media_too_large`. All 14 footage attempts are downloaded;
the plan has four `done` work items. These are not yet proof of four
visually verified finals. The worker recorded the pause at
2026-09-21T00:15:41.517580Z.

The failure occurs during `VertexAnalyzer.price`, before a final-review
request is submitted. Its default inline media limit is 20 MiB. Auto passes
the final artifact directly; the adapter also enforces the size limit at
execution. Do not bypass final QC, simply raise the limit, or regenerate
paid footage to address this. Next: reproduce the oversized-final path
offline and implement a bounded analysis derivative with explicit binding
to the unchanged original final, then regression-test and resume this run.
Root-cause/fix verification remains open. Full offline test session 92708
was polled successfully and had passed 56% with no reported failures at
the latest observation; no final test result is claimed.

QA-R1-08 fix: the quote boundary now prepares a bounded local review copy
for oversized finals. Two-pass encoding preserves full duration, dimensions,
frame rate and audio; size/timeline/stream checks reject invalid derivatives.
The original final SHA remains the request binding. A verified cache and
review receipt retain both original and submitted-copy SHA and disclose the
compression limitation. Original finals and mandatory technical QC are not
replaced. No extra footage request was needed.

The regression initially failed with the exact `analysis_media_too_large`
error; focused coverage now has **6 passed**, including actual local encoding,
cache reuse, original immutability and rejected mismatches. Combined analysis,
review-media and scene-assignment coverage: **41 passed**. Full offline suite
started before this patch completed **1264 passed, 2 deprecation warnings**
(781.09s); this is not a full-suite result for the later proxy patch.

Verified against real final D: original 31,936,482 bytes, review copy
17,385,161 bytes, 720×1280 and 62.366667 seconds; original remains untouched.
Deployed idle API PID 17819 and sole worker PID 17881 at 00:22:25 UTC.
Reload verified jobs/attempts/run records/accounting unchanged. Clicked the
existing run's normal dashboard Resume after deployment. Live QC result
and final playback are still pending.

Additional issue QA-R1-09 identified in dashboard inspection: a caught
ContractError exposes a Python traceback plus generic recovery text in the
status bar. Durable diagnostics are useful, but expected failure recovery
needs a concise specific user-facing message. Fix/coverage remains open;
do not advance to Round 2 before closing the post-round issues.

The first Resume click after service reload was rejected by the expected
expired-session CSRF check; no work was submitted. Reloaded the dashboard,
opened Auto, and resumed successfully. Durable state confirmed
`running / final_qc`, and worker PID 17881 subsequently completed visual-QC
analysis jobs successfully. No duplicate requests were made.

Compare browser metadata confirms the reference is 1080×1920/62.368798s
and all four revision-5 finals are 720×1280/62.366667s with readyState 4
and null media errors. Artifact IDs: A `art:06c518254a9ec030`, B
`art:55cf56bd7b85cb53`, C `art:65bcd4181d4fc769`, D
`art:9c4310844c43179f`. Actual A playback was started through its native
control and observed advancing; remaining playback/quality audits are open.

QA-R1-09 regression: four expected copy-preparation errors reproduced the
generic `stage_error` behavior. The handler now retains a specific typed
code, uses concise recovery text, and logs the code/run/stage separately
without embedding a Python traceback in an expected-validation pause.
Four tests are green; combined recovery/proxy/authority/prevention selection
**31 passed**. This later recovery-message patch is not yet deployed; do not
reload while the current visual-QC provider request is in flight.

Round 1 now reports `succeeded / done`; all four current final SHAs have
durable automated visual verdict `pass`. This closes the live size-limit
blocker, not the full round's post-run gate. A completed native playback
reached 62.366667s with `ended=true` and no media error. B/C/D playback was
also started through native controls and observed advancing beyond 47s
without media errors. Full visual/audio, delivery and accounting audits remain.

QA-R1-10: provider review `notes` can be a string; the adapter iterated it as
characters and retained only the first ten. Reproduced the exact problem
offline, then normalized a string to one complete note and rejected malformed
non-text note collections. Regression is green; combined proxy/recovery/
analysis timing selection **42 passed**. Original provider response evidence
is retained, so any missing explanatory text can be read without another
paid call. Prior verdicts remain passes; do not fabricate replacement notes.
This parsing fix and QA-R1-09 recovery-message fix still need idle deployment.

## Round 1 checkpoint — 2026-09-21 00:34 UTC

All four finals completed native browser playback to `ended=true` at
62.366667 seconds with no media errors. Reload confirmed the exact seed/run
and the same four revision-5 hashes in Compare. Full local decode passed for
every video: 720×1280, 30fps, 1,871 frames, AAC mono 48kHz, matching timeline.
Mixes are unclipped with peak -1.47dBFS; measured RMS ranges -22.35 to -21.92.
Original provider audiovisual review responses were recovered read-only;
all four pass and describe matching script/audio/scene content. No new paid
review was needed to recover D's complete note.

Reviewed 16-frame grids per final. B visibly changes the first 8 seconds,
C the 31.8–35.8s chicken/pan scene, D the 55.8–62.3667s pony ending. Shared
regions intentionally reuse the same generated clips. Generated native
overlays and small single-word subtitles remain style limitations; sampled
review is not a claim of flawless lip synchronization or proven view uplift.
Full raw evidence: `data/factory-qa/qyae7gauvgi-20260920/round-1-audit/audit.json`.

QA-R1-11: real gdrive 3.9.1 tab listings expand into aligned columns, breaking
the app's literal-tab parser. Reproduced offline with actual-format output;
changed the CLI delimiter to `|` and preserve embedded pipes in names by
parsing the fixed trailing columns. Delivery suite **10 passed**; actual
remote duplicate checks and uploads succeeded. No upload occurred on the
initial parser failure. Final deployed API/worker PIDs 48375/48434 at
00:33:43 UTC include QA-R1-09/10/11 and the earlier assignment repair.
Reload snapshots preserved all jobs, attempts, runs and accounting.

Frontend **50 tests passed**, production build passed. Round-one log sweep
shows the already investigated speech-fit, authority, retired scene-review,
and size-limit failures; `remote_unfinished` represents normal polling.
No new preview or API exceptions appeared in the current diagnostic logs.

All 39 completed Round 1 reservations settled at their full reserved amounts
as **usage estimates**, not invoices or provider-reported charges:
**$13.72542 estimated USD + 1,158 ElevenLabs credits**. No Round 1 holds remain.
The 238 pre-request authorization failures remain released, not counted as
spend. Historical closed/do-not-retry accounting was not changed.

Verified Drive delivery used the repository's standing CLI workflow; the
application's separate human creative-approval/Delivery records were not
fabricated. Parent, descriptive name, byte count and remote MD5 match for all:

- [A](https://drive.google.com/file/d/1skItR41ipNxtmwE49Nbp59cifBQXLJ_z/view)
- [B](https://drive.google.com/file/d/1CtW72JDDX2sAQihKSoggXgwt4ixW1xZB/view)
- [C](https://drive.google.com/file/d/1dxGdmv2-ZQmtLBACBfPU_n4ueObkh7RF/view)
- [D](https://drive.google.com/file/d/1nbEHut8oTuQutSEPOXMzEkAdEIFHfAcj/view)

Upload, settlement and cleanup receipts are alongside `audit.json`.
Cleanup verified 72 registered video-process identities per variant, no
surviving owned processes and no video-specific port listeners. No dedicated
preview port was created; shared API 8100 and the single worker remain for
Rounds 2/3. Other projects' services were untouched. Nothing was published.

Checkpoint disposition: QA-R1-01–11 have scoped fixes and offline evidence;
the same run recovered to valid finals, and new-run behavior will be exercised
in Round 2. No unresolved in-scope blocker remains for starting that round.

## Round 2 started

Created through the normal dashboard Auto controls after Round 1's checkpoint.
Run ID **`auto-8182bae593894e93`**; same exact source seed
`seed-youtube-991b37f63be3d124` and URL qyaE7GaUVGI verified in Latest run.
Voice `cgSgspJ2msm6clMCkdW9`, English, configured Google generation account,
final visual QC enabled, generated music disabled. Only Round 2's new budget
envelopes selected: USD25 and 10,000 ElevenLabs credits (adjustable under the
three-round authorization). No extra top-level run exists; Round 3 unstarted.
Initial durable state is `running / evidence`.

The patched application Drive adapter was also tested against the real folder:
47 files parsed successfully with no mutation. Round 1 upload verification
added exactly four finals to the previously observed 43 entries.

### QA-R2-01 — repeat-seed analysis binding

At 00:36:36 UTC Round 2 paused at draft with `analysis_stale`: current
reference analysis is revision 2, but the reused accepted blueprint remained
bound to revision 1. Fresh analysis and LLM script both succeeded; no Round 2
TTS or footage was submitted. The scene-review feature remained removed.

An offline regression reproduced the stale r1 binding after a second run
with identical observations. The accepted-blueprint fast path skipped
current structural preparation. It now revalidates and refreshes the derived
analysis link without changing scene content/hash. A paused draft rewinds
to guarded blueprint preparation, preserving its existing paid analysis and
script. Incomplete evidence still blocks. No stale-data gate was disabled.
Repeat-seed + analysis-gate selection **22 passed**; expanded recovery test
also exercises preservation of saved script data and incomplete evidence.
Live recovery pending. Full offline test session 19863 is still running;
it began before this latest patch and is not proof of the patch's live result.

Deployed the repeat-seed fix at 00:39:51 UTC (API 66445, sole worker 66537),
with durable job/attempt/run/accounting snapshots unchanged. Dashboard Resume
advanced the same Round 2 from draft through blueprint preparation back to
draft and **narration**, preserving the already completed analysis and script.
Experiment `exp-auto-8182bae593894e93`, revision 1. Live fix verified; no
duplicate analysis/script request was submitted. The new script places the
deer line in b2 and AirPod reaction in b11, confirming the earlier transcript
ownership fix in a fresh run. Actual measured narration fitting remains open.

At 00:40:51 UTC, Round 2 passed narration fitting without manual copy edits,
saved experiment revision 2 and quoted plan `plan-8bff96eb5e64328feabf8e45`.
It paused at authorization: footage needs 11,725,420 USD micros, exceeding
available shared aggregate budget. This is an expected safeguard, not a
provider error; no Round 2 footage operation has been submitted.

An attempted exact-required aggregate-ceiling adjustment was rejected by the
tool safety reviewer because the limits are shared with historical/unrelated
jobs. **No ceiling changed.** Explicit user approval was requested for these
three increases (including four final-QC estimates):

| Shared ceiling | Current USD | Requested USD |
| --- | ---: | ---: |
| 7udu-approved-20260920-usd | 25 | 28.700840 |
| syp34-vertex-approved-4590780 | 55.366950 | 58.737190 |
| syp34-vertex-approved-6886170 | 50.776170 | 54.146410 |

The nffa1 aggregate has sufficient room and needs no change. The UI-created
Round 2-specific budget also has sufficient room; every applicable aggregate
still independently constrains it. Do not bypass these limits or rerun the
rejected script without resolving the shared-scope authorization concern.
Full offline regression session 19863 remains live and has no reported
failure at the last poll. Round 3 is unstarted.

### Authorization-wait verification

On the next continuation, reread the objective and confirmed the same
`budget_exhausted / authorize` pause. There are exactly two autoruns and
**zero attempts** for Round 2 plan `plan-8bff96eb5e64328feabf8e45`.
No shared-ceiling approval has arrived and no rejected mutation was retried.
`git diff --check` passes. Full offline session **19863** was repeatedly
confirmed live, progressed beyond **62%**, and has not reported failures;
the final result is still pending. Preserve this test session, do not restart
it merely because observation yields. This is a verified wait plus safe
read-only verification, not completion of the three-round goal.

### Blocked audit — 2026-09-21 00:49 UTC

Full offline session 19863 completed: **1,276 passed, 2 dependency
deprecation warnings, 774.05 seconds**. The repeat-seed patch landed after
this process started; its separate 22-test analysis-gate selection and expanded
recovery regression passed and its live recovery to narration was verified.
Frontend 50 tests and build already passed. A final full-suite run remains
required after all three QA rounds and their final repairs.

The same shared-ceiling authorization blocker has now persisted through
three consecutive goal turns. No approval arrived. Verified unchanged caps,
Round 2 still paused at authorize, zero Round 2 footage attempts, Round 3
unstarted. Safe pending tests are complete; there is no further in-scope action
that can advance generation without resolving the safety review's scope
concern. Goal is **blocked, not complete**. Resume requires explicit approval
for the three exact shared-ceiling increases listed above. Do not create
replacement runs or bypass aggregate accounting. All completed assets,
receipts, analysis and scripts are preserved.

### Explicit shared-ceiling approval applied

The user explicitly named and approved all three shared ceilings and acknowledged
the possibility of permitting unrelated work. Applied through the normal budget
API and independently verified persisted values: `7udu-approved-20260920-usd`
28,700,840 USD micros; `syp34-vertex-approved-4590780` 58,737,190;
`syp34-vertex-approved-6886170` 54,146,410. No other ceilings or historical
holds were changed. Receipt: `data/factory-qa/qyae7gauvgi-20260920/round-2-budget-adjustments.json`.
Round 2 remains paused at authorize; this budget update itself did not submit
generation or resume the run. The shared-ceiling approval blocker is resolved.

### Round 2 resumed after approved ceiling changes

Resumed the existing run through its dashboard Resume button. Verified API PID
66445 and sole worker PID 66537. Run `auto-8182bae593894e93` advanced from
authorize to running/footage on its existing plan `plan-8bff96eb5e64328feabf8e45`.
Current worker log at 2026-09-21T03:09Z shows collection polling with
`remote_unfinished`, an expected pending provider operation, not a new failure.
No replacement run or historical retry was created. Round 2 finals and its
post-run checkpoint remain outstanding; Round 3 has not started.

### Round 2 four final files rendered; audit underway

All four Round 2 final records now exist and the run advanced to `final_qc`.
Read-only audit `/tmp/factory_r2_audit.py` verified artifact SHA bindings and
full error-free decoding for A/B/C/D: each 720×1280, 30 fps, 1871 frames,
62.366667 seconds, H.264 video with 48 kHz AAC audio and unclipped mix.
Evidence saved to `data/factory-qa/qyae7gauvgi-20260920/round-2-audit/audit.json`.
Provider final-QC responses were not yet available at this checkpoint. Actual
Compare playback, audiovisual inspection, final-QC completion, delivery,
accounting and cleanup are still pending. This is not a round completion claim.

Round 2 subsequently reached `succeeded/done`. Refreshed audit contains four
provider final-QC `pass` responses bound to the final hashes. A and B completed
actual Compare playback (`ended=true`, 62.366667 s, no media error). C and D
played partially without media errors but were paused before their ends; their
full playback checks remain outstanding. A concurrent audit read initially
preceded creation of a pending provider response; repeating it after workflow
completion succeeded without resubmitting any provider request. Delivery and
the complete post-round checkpoint remain pending; do not start Round 3 yet.

All four Round 2 Compare players have now reached their ends without media
errors. C/D were replayed from zero using the visible native play controls,
then independently observed `ended=true` at 62.366667 s. Sampled 4×4 frame
grids for A/B/C/D are saved beside the audit and inspected: B changes the
opening, C the chicken/pan scene, D the pony/AirPod ending; remaining scenes
are shared. Small single-word captions and generated in-scene text remain
visible stylistic limitations, not claims of perfect lip sync or proven view
uplift. Reload retained the exact seed, Round 2 experiment/revision, and
17/17 complete status. Upload, accounting, cleanup and full checkpoint remain.

### Round 2 delivery, accounting and resource receipts

Verified Drive parent/name/bytes/MD5 for each final; descriptive revision-2
delivery copies and receipts are in `round-2-audit/`:

- A: https://drive.google.com/file/d/1wkK_TuyWxT0il7cHxDr9YjEtsC5-MXyT/view
- B: https://drive.google.com/file/d/18jMhWaTsrIDD_viKQMnYgg4UlbbvNEIt/view
- C: https://drive.google.com/file/d/1rDCosBMujfkWPVjL6K02TI8pqKnRwqAd/view
- D: https://drive.google.com/file/d/1I4lLYHKg92BZPlaHZGopmZTgPOuCgokR/view

Settled 34 completed reservations through the public API as `usage_estimate`:
20 USD reservations total 13,225,420 micros ($13.225420), 14 speech reservations
total 891 credits. These are conservative estimates, not invoice-confirmed
charges. No historical holds changed. Verified 72 registered process identities
per variant, no survivors and no dedicated video ports; shared API/worker and
port 8100 intentionally retained. Receipt files: `upload-receipts.json`,
`settlement-receipts.json`, `cleanup-receipts.json`. The remaining Round 2
checkpoint is the consolidated logs/regression/provenance audit before Round 3.

### Round 2 post-run checks; Round 3 spending preflight

Focused regression run: 19 passed, two known dependency deprecation warnings
(repeat-seed, scene assignment, recovery, delivery). `git diff --check` passed.
Current API/worker JSON logs from Round 2 start contain only the previously
documented `draft_failed` and `budget_exhausted` pauses after excluding normal
`remote_unfinished` polling. Durable generation/collection/render/review jobs
all succeeded; delivery jobs retain the app's separate `awaiting_review` state,
with actual authorized CLI delivery independently proven by receipts.

Round 3 remains unstarted. Preflight shows zero available headroom in three
shared aggregate ceilings; `nffa1-live-test-20260920-usd` has 2,664,520 micros.
The prior explicit approval was for exact Round 2 caps only. Request a new
explicit shared-cap approval before paid Round 3 work: provide $25 of new
headroom above current committed usage in each applicable aggregate ceiling:
7udu 53,700,840; syp34-4590780 83,737,190; syp34-6886170 79,146,410;
nffa1 62,335,480 USD micros. No change has been applied. These are administrative
ceilings, not a provider quote or an authorization for a fourth QA round.

Follow-up checkpoint: all 50 dashboard tests across 11 files passed; TypeScript
and production build passed. Revalidated exactly two autoruns, both succeeded,
and all four aggregate caps unchanged. No new approval has arrived for Round 3.
This is the second consecutive turn encountering the same shared-budget
authorization dependency. No paid jobs or ceiling changes were submitted.

Third consecutive shared-budget blocker check: caps and committed amounts
remain unchanged, three shared ceilings have zero headroom, exactly two runs
exist and both succeeded. Explicit approval for the four proposed new caps
has not arrived. Safe pending dashboard checks are complete. Mark the goal
blocked, not complete, awaiting that approval; preserve all outputs and records.

The user subsequently confirmed the explicit four-cap request. Applied through
the public budget API and independently verified saved ceilings: 7udu 53,700,840;
syp34-4590780 83,737,190; syp34-6886170 79,146,410; nffa1 62,335,480 USD micros.
Receipt: `data/factory-qa/qyae7gauvgi-20260920/round-3-budget-adjustments.json`.
No other limits or historical holds changed. Shared-budget approval blocker
resolved; Round 3 is still unstarted at this checkpoint.

### Round 3 started — final authorized round

Created through the normal dashboard workflow: `auto-5b10280f1fc84a64`.
Exactly three autoruns now exist in this cycle; do not create another.
Same source `seed-youtube-991b37f63be3d124` (qyaE7GaUVGI), same replacement voice
`cgSgspJ2msm6clMCkdW9`, English, configured provider account
`david.dai@robanka.com`. Only Round 3 category envelopes selected (25,000,000 USD
micros, 10,000 speech credits); final visual QC enabled, music disabled.
API PID 66445 and sole worker PID 66537 verified before start. First durable
state running/evidence; prior two runs remain succeeded/done. Publishing and
scheduling remain out of scope.

### Round 3 narration-fit pause

Fresh analysis, automatic blueprint and scripting completed; repeat-seed draft
staleness did not recur. Run paused at TTS with `speech_fit_failed` for A/b1:
source-derived narration does not fit the selected voice's pace. Draft revision
1 assigns 24 words to 8 seconds in b1, and 18 words to 5 seconds in b9.
Worker also recorded `copy_revision_required` for a b9 speech-fit command.
Classification and measured-duration investigation remain underway; no copy
edit, duplicate speech submission, or new run was made at this checkpoint.

Measured speech records confirm b1 9.6s for 8s and b9 6s for 5s; this is a
valid timing safeguard, not evidence of a broken fit check. Repaired through
public draft API to revision 2: b1 shortened to 'Atlas climbed into the feed
trough and he’s still eating. Look at him. Big, lazy baby.' for A/C/D; b9 to
'My donkey is eating my truck. Get out of here!' across all variants. B's
distinct opening and C/D distinct test regions preserved, all timings unchanged.
Receipt `round-3-copy-repair.json` captures exact payload. Resumed existing run
with its checked Round 3 budgets; fitting/reuse verification is pending.

Live follow-up: narration completed and autorun advanced through quote and
authorization to `running/footage`, current revision 3, plan
`plan-a47d6a497b0c4b04821a0a64`. First footage request submitted with normal
`remote_unfinished` collection polling; 13 remaining generation jobs ready.
Prior failed fit records remain historical. No ceiling increase was needed.

### Round 3 finals and final regression gate underway

All fourteen footage operations completed; run succeeded/done at revision 3.
Four final provider-QC passes and full error-free decode/hash checks recorded
in `round-3-audit/audit.json`: 720×1280,30fps,1871frames,62.366667s,AAC audio.
All four actual Compare players observed ended=true at 62.366667s with no media
errors. Sampled grids inspected for beginning/body/ending and B/C/D footage
differences; shared scenes and native generated overlays remain documented
limitations. Full offline pytest gate running in session 16091. Round 3 verified
Drive upload is running in session 7209; neither process is complete yet.

### Round 3 delivery and accounting verified

Upload session 7209 completed successfully, with parent/name/bytes/MD5 verified:

- A: https://drive.google.com/file/d/1cD9Actd3hhuEaA3GL-dt78fFA2x4_FNv/view
- B: https://drive.google.com/file/d/1wOkM4DiHZ6onr-i-Ap-Acb70aLFT8Oh4/view
- C: https://drive.google.com/file/d/1YjYY9662dedHDsJyUsow5tMw9QkngxPm/view
- D: https://drive.google.com/file/d/1vTZIcacUJIGUx5JxHpDOAm6ym9pZoAlR/view

36 completed reservations settled as conservative usage estimates: $13.225420
(20 reservations) and 1,023 speech credits (16 reservations). No historical holds
changed. Cleanup verified 72 process identities per variant, no survivors, no
dedicated video ports. Shared dashboard/API and worker retained. Current-round
logs show only 14 historical copy-fit failures and the one repaired narration
pause, excluding normal provider polling. No new error category surfaced.
Final full offline suite session 16091 is still running; do not restart it.

### Final persistence and frontend checkpoint

After reloading the dashboard, Round 3 remained selected at revision 3 with the
exact qyaE7GaUVGI seed and run ID. Status showed 17/17 stages, 100%, Run complete.
All four final media elements loaded with readyState 4, 62.366667s duration and
no media errors; artifact IDs matched the audited finals: d53f2f76505eb54a,
fa14b8605c7cace3, 822a17065bee8b98 and 0c5ccffdc255e063. Reference remained the
separately identified original source. B/C/D test regions persisted correctly.
Final frontend gate: 50 tests across 11 files passed; TypeScript and production
build passed. `git diff --check` passed. Full offline backend suite remains live
in session 16091; completion is not yet claimed.

### Final cross-round integrity and accounting checkpoint

Read-only reconciliation of all twelve current final records against delivery
receipts and actual local export bytes passed: SHA-256, MD5, size, and verified
receipt status match for every variant in every round. Exactly three autoruns
exist. Shared API PID 66445 and worker PID 66537 remain live.

All reservations charged to this cycle's six category envelopes are settled or
released, with no held or ambiguous reservation in those envelopes. Conservative
estimated usage totals $40.176260 and 3,072 speech credits (not invoices or
provider-confirmed charges). Global historical records still contain 42 held
and three ambiguous reservations, all created before this restarted cycle;
none were erased, replayed, or reclassified by this checkpoint. Those global
counts are not new unresolved operations in the three completed runs.

Latest worker log ends in successful Round 3 final QC and autorun completion;
no subsequent failure is present. The prior goal turn made progress by proving
reload persistence and recording the frontend gate; this turn additionally
verified all twelve delivered file identities and current category accounting.
The full-suite session 16091 remains live and is being polled without restarting.

### Consolidated issue dispositions after Round 3

| Issue | Classification / affected rounds | Current disposition and verification |
| --- | --- | --- |
| QA-R1-01 | Application: truncated script / R1 | Fixed whole-sentence handling, numeric limits and bounded rewrite. Offline regressions passed; repaired complete copy reached the rendered final. |
| QA-R1-02 | Expected speech-fit safeguard / R1, R3 | Repaired overlong copy within the same runs; valid existing narration reused. Both runs passed fitting and final QC without disabling timing checks. R3 measurements and exact repair receipt are above. |
| QA-R1-03 | Application: scene ownership / R1 | Fixed unique word-majority assignment with conservative fallback. Reproduced before patch; focused tests and real transcript replay passed. R2/R3 exercise the corrected assignment. Alignment anomalies remain warnings. |
| QA-R1-04 | Documentation / R1 | Removed obsolete scene-review directions. Historical notes in this ledger are preserved, not active workflow instructions. |
| QA-R1-05–07 | Application: account binding, repeated failed dispatch, stale DAG recovery / R1 | Scoped regression coverage passed. Same-run recovery with the configured account succeeded; R2/R3 use that account without recurrence. Failed prerequest attempts remain terminal and released. |
| QA-R1-08 | Application: oversized final-QC input / R1 | Bounded local full-timeline review proxy fixed the provider limit; offline tests and all twelve live final-QC passes verify recovery. Final-resolution exports are unchanged by the proxy. |
| QA-R1-09 | Application: recovery messaging / R1 | Expected preparation errors now produce structured, redacted recovery messages; four error regressions and frontend checks passed. No new occurrence required live error injection. |
| QA-R1-10 | Application: string review notes / R1 | Normalized string notes rather than splitting into characters; parser coverage passed and later reviews preserve complete notes. |
| QA-R1-11 | Application: Drive listing parsing / R1 | Explicit delimiter and trailing-column parser; ten delivery tests, live folder listing and verified uploads succeeded. |
| QA-R2-01 | Application: repeat-seed blueprint binding / R2 | Current analysis binding refreshed through guarded preparation. Offline regression passed; same-run recovery preserved paid work. R3 fresh analysis reached scripting without recurrence. |
| Shared ceilings | Expected spending safeguard / R2, R3 | Exact shared cap changes explicitly approved and applied through normal API; receipts preserved. No accounting bypass. |
| Generated-media styling | Output-quality limitation / all | Shared generated regions are intentional; B/C/D each alter their documented test region. Native overlays and small single-word captions remain visible. No claim of perfect lip synchronization or measured view uplift. |

No newly identified reproducible application defect remains awaiting a patch at
this checkpoint. This is not final sign-off: the post-Round-3 complete offline
suite must still finish successfully, or any failures must be investigated.

### Final suite failure under investigation

Session 16091 finished: **1 failed, 1276 passed, 2 dependency warnings in
766.34s**. Failure: `test_legacy_current_blueprint_approval_is_not_discarded`
in `tests/test_factory_run_prevention.py`, raising `unknown_blueprint` when
automatic preparation loads the mocked blueprint from the real repository.
Isolated reproduction of that exact test also fails (0.35s), establishing a
fast deterministic feedback loop. Classification is not yet concluded: inspect
legacy approval preservation versus the test's partially mocked persistence
before changing implementation or test expectations. All twelve finals remain
unchanged. Final gate failed; goal remains active pending repair and re-test.

Diagnosis: the legacy test mocked `analysis.get` with an in-memory blueprint
but left `blueprints.prepare_automatically` attached to the real empty store.
The repeat-seed fix correctly revalidates accepted blueprints, exposing that
inconsistent test boundary. Updated the test's preparation boundary to match
its analysis double and explicitly assert exactly one call with the existing
ID/hash plus preservation of the blueprint ID; import still fails the test.
All 16 run-prevention tests passed in 0.59s. No production code or media changed.
Real persisted preparation/revision rebinding is covered by
`test_factory_repeat_seed.py`, including unchanged content hash and refusal of
incomplete evidence; that and scene-removal/analysis-gate tests are running in
session 12932. A new full-suite pass remains required after this test repair.

Related persisted-blueprint, removed-scene-review and analysis-gate tests all
passed: **32 passed, two known dependency warnings, 35.83s** (session 12932).
Together with the 16 run-prevention tests, these verify the corrected double
without weakening real persistence, stale-source, or incomplete-evidence gates.
Started the required fresh complete offline `.venv/bin/pytest -q` run in
session **59305**. Previous session 16091 is terminal; do not poll or restart it.
Only the test and ledger changed after the failed suite; deployed application,
frontend build, and twelve verified final exports remain unchanged.

### Completion audit matrix (sign-off pending full-suite result)

| Requirement | Evidence and disposition |
| --- | --- |
| Exactly three sequential runs, exact seed | Three durable autoruns listed at the top, each succeeded/done; dashboard seed/run checks recorded at each start. No fourth run. |
| Normal end-to-end workflow, no fabricated success | Per-round stage/log records and plan-bound finals; recovery used dashboard or public application APIs. Separate CLI delivery is explicitly distinguished from the app's human creative-approval state. |
| Four final variants per run | Twelve current final records match verified export SHA/MD5/size; all twelve completed actual Compare playback. Per-round audit files record full decoding and media properties. |
| Copy, footage and replacement narration | Per-round script/provenance checks and sampled output grids; B opening, C body and D ending test regions documented. Shared generated footage is explicitly disclosed. Voice and timing repairs recorded; final audiovisual QC passed for each export. |
| Persistent Compare state and correct assets | Reload checkpoints for all rounds; R3 confirms four current artifact URLs, readiness and duration, distinct from source. |
| Progress, errors, recovery and logs | Stage/status snapshots and per-round log sweeps; specific recovery-message regressions; final logs show completed QC and autorun. |
| Removed scene review, retained safeguards | Removal tests cover absent controls and refused dispatch actions; analysis/source/timing/incomplete-evidence tests passed. Early pre-removal history is preserved, not replayed. |
| Repair checkpoints | Consolidated issue table and per-round chronology above; repeat-seed live recovery and subsequent R3 progression verify that fix. Latest failure was a test-double inconsistency, not a deployed media change. |
| Offline tests and frontend checks | Frontend 50 tests and production build passed; related backend 32 plus 16 passed. Complete post-repair suite 59305 still running: this requirement is not yet proven. |
| Delivery and video-resource cleanup | Twelve remote upload receipts verify folder/name/bytes/MD5; per-round cleanup receipts show no surviving registered video processes or dedicated listeners. Shared dashboard/API and one worker retained for access. |
| Spending and historical integrity | Cycle reservations settled/released, estimates separated from invoices; earlier global holds preserved. Exact shared-cap approvals and receipts retained. No historical retry, credit purchase, publishing or scheduling performed. |
| Durable handoff | This ledger contains run IDs, issue dispositions, tests, costs, limitations and all twelve Drive links. Final overall verdict awaits the complete suite. |

The preceding goal turn made concrete progress by obtaining 32 passing
safeguard tests and starting the post-repair full suite. Current continuation
is a verified wait on that live session; no restart or paid request was made.

## Final sign-off

Post-repair complete offline suite session 59305 finished successfully:
**1,277 passed, two dependency deprecation warnings, 745.05s**, exit 0.
Warnings concern Starlette/httpx and the anyio BlockingPortal alias, not failed
checks. Frontend final gate remains **50 passed**, TypeScript and production
build passed. Final `git diff --check` passed. The corrected test double did not
change deployed behavior or invalidate any video, upload, or playback evidence.

The completion matrix above is now satisfied, including its previously pending
full-suite requirement. All three durable autoruns remain succeeded/done;
current worker log ends with successful final QC and Round 3 completion. Twelve
current final records, local bytes and verified remote delivery receipts match.
Per-round audits cover playback, reload persistence, provenance, technical and
final audiovisual QC, issue recovery, logs, accounting and video-owned cleanup.
No fourth run, publishing, scheduling, historical replay, or destructive reset
was performed. Shared dashboard/API and one worker remain available so the user
can review Compare; dedicated video-owned resources were cleaned up.

Final conservative estimated usage: **$40.176260 plus 3,072 speech credits**.
These are not invoice-confirmed charges. Historical holds remain preserved and
separate. Generated native overlays, small word-by-word captions, and reused
generated regions are disclosed limitations; this QA does not certify perfect
lip synchronization or increased views. All reproduced in-scope application
bugs have the fixes and verification recorded above. Three-round QA complete.
