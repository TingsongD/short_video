# Last production run audit — 2026-09-22

Audited `auto-2c9de6ddf2e34d5c` / AVvVLM5b-mE after the user requested
confirmation that its issues had been debugged and fixed. The completed run
remains successful at revision 3. This audit reads its saved evidence and
database in read-only mode; tests use disposable local data and fake external
transports. It does not repeat the paid batch.

## New defects reproduced and fixed

The seed had no language metadata, while both the saved local transcript and
the run's source-language field were `en`. The incident report records that
the Chinese source was mistranscribed and needed a manual English narration
correction. The previous hardening scope had explicitly excluded this issue;
the user's latest request includes it.

Three new regressions failed before their fixes:

1. An unlabeled source reached transcription with forced `en` instead of
   automatic detection. It also saved the requested language instead of the
   detected language. New analysis now defaults to detection, retains the
   detected language with its source-bound transcript, and feeds Chinese text
   into the existing explicit Chinese-to-English translation stage. An
   explicit `source_language` takes precedence over generic language metadata.
2. Starting another analysis could reuse a completed transcript created under
   the old forced-English setting. Changed transcription settings now create
   a new analysis revision; completed historical evidence and its files remain
   unchanged. Restarting an unchanged analysis still reuses its transcript.
3. Real Chinese alignment returned individual characters while its passage
   text had no spaces. The factory treated the complete alignment as missing
   words, attempted needless repair and could assign the line to the wrong
   scene. Timing validation and script ownership now compare Han character
   units consistently. Missing, changed or reordered characters still fail;
   Latin word boundaries are retained.

The pinned Hypit CLI accepts only explicit `en`, `zh` or `es`; passing `auto`
to it would fail. Automatic detection therefore uses the existing local
WhisperX service, which supports detection, and writes the same transcript
format. It extracts 16 kHz mono audio from the normalized analysis copy and
decodes once. Known languages retain the existing Hypit command. The local
adapter refuses remote endpoints and redirects, checks service identity, bounds
response size, preserves missing timing, cleans up staged audio and refuses
overwriting an existing transcript. Missing detection or an unavailable local
service blocks analysis; it never guesses English or falls back to a paid API.

Regression coverage: `tests/test_factory_source_language.py`, including the
actual analysis-to-translation handoff, cache/restart behavior, malformed
detection, explicit language metadata, character timing and the local transport
boundary.

The original audio was also checked with the real local WhisperX engine in
offline mode. It detected `zh` with reported confidence **0.99**, but first
exposed a missing Chinese alignment dependency. Restored the standard
WhisperX [Chinese alignment model](https://huggingface.co/jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn)
in the existing cache: revision `99ccb2737be22b8bb50dcfcc39ad4d567fb90cfd`,
1,276,296,151-byte weights plus four metadata files. This was a public model
download with credentials disabled; no source audio was sent externally.

Repeating the inference with network access disabled succeeded: model `small`,
CPU/int8, WhisperX 3.8.6, **72 aligned speech units**. Replaying that real local
response through the new adapter, transcript validation and timing review
against the completed run's actual scene boundaries also passed with **zero
timing repairs**. Staged audio was cleaned up. This verifies this source's local
recognition/alignment path; it does not establish general transcription or
translation quality across other sources or a new paid end-to-end batch.

## Every saved incident and its disposition

| Last-run issue | Current disposition | Regression evidence |
| --- | --- | --- |
| Truncated analysis response | Bounded recovery from completed responses; unknown outcomes are not replayed | `test_factory_flashcut_response_recovery.py` |
| Overlapping cited windows rejected | Continuous coverage is accepted; actual gaps remain failures | `test_factory_context_coverage.py` |
| HTTP 400 provider schema rejection | Compact request schema with strict local response validation | `test_factory_flashcut_response_recovery.py` |
| Completed responses holding execution capacity | Release requires completion evidence and leaves financial holds intact | `test_factory_flashcut_response_recovery.py` |
| Unclear recovery state | Durable clarification/recovery identities and typed status messages | `test_factory_flashcut_response_recovery.py`, `test_factory_analysis_timing_recovery.py` |
| Context already present elsewhere | Reuse only source-bound, continuously covered evidence; semantic uncertainty still requires evidence | `test_factory_context_coverage.py` |
| Wrong source-language transcription | Default detection, detected-language provenance and revision-safe reuse fixed in this audit | `test_factory_source_language.py` |
| Chinese speech timing rejected | Character spacing normalized consistently without weakening speech/timestamp validation; missing local alignment model restored | `test_factory_source_language.py`, original-audio offline replay |
| Narration too long; first rewrite unusable | A distinct second bounded attempt, restart-safe counters, unchanged speech reuse; exhaustion still pauses | `test_factory_future_workflow.py` |
| Incomplete editorial plan | Strict validation and conservative source-bound fallback only for eligible completed responses | `test_factory_editorial_planning.py` |
| Generic footage direction | Scene-specific actions/cast/setting reach each variant's prompt | `test_factory_creative_context.py` |
| Fractional audio endpoint rejected by renderer | Exact frame-based premix endpoint | `test_factory_native_hypit.py`, including actual local render checks |
| QC demanded original Chinese captions | Explicit replacement-caption policy tied to final speech | `test_factory_final_review_media.py` |
| Sequential generation | Four default Vertex operations, fair polling/collection/dispatch, retained budget and unknown-operation limits | `test_factory_parallel_generation.py`, worker-death regression |
| Credential expiry and HTTP 500/unknown results | Readiness and safe pauses are implemented; renewed credentials or provider reconciliation remain external actions | Readiness/recovery tests; no promise that provider errors cannot recur |
| Local services stopped after task closure | Durable Terminal startup is documented; a running dashboard still requires the API/worker to be started | Operator guide; no production service was started by this audit |

The manual semantic correction in the completed run is historical evidence,
not proof of general unattended visual understanding. New provider payloads,
reference-conditioned generation, general recognition quality and actual four-way
provider throughput still require their scoped live qualification. Financial
unknowns retain their holds. Automatic partial paid-batch recovery remains
retired at the user's request.

## Verification

- Initial focused incident audit: **93 passed in 9.57 seconds**.
- Initial source-language regression: failed twice on forced `en` before the
  fix. Cache regression also failed before its fix.
- Final source-language, source-timing, scene-assignment, analysis-gate and
  historical-evidence regressions: **73 passed in 35.81 seconds**, including
  all **20 new language cases**.
  Existing offline transcription doubles now return detected `en` when asked
  to detect English fixture speech, matching the real service contract.
- Read-only verification of the completed A/B/C/D files: all four SHA-256
  values match their saved artifact records; each is **720×1280, 30 fps,
  424 frames**. No export or upload was repeated.
- Final full offline suite: **1,642 passed, 7 skipped in 2,400.05 seconds
  (40:00)**, using `PYTEST_ADDOPTS='-x --durations=15' make test`. This includes
  the parallel-generation safeguards, all five complete four-variant recovery
  scenarios, actual native exports and worker-death recovery. The seven
  separate-environment helper skips are unchanged from the prior baseline.
- All **542 captured source/test hashes** remained unchanged during the full
  run. `git diff --check` passed; frozen schemas and fixtures have no diff.
  Process inspection found **no remaining test render/preview processes**,
  including those from the earlier interrupted audit runs.
- Intermediate full runs were deliberately interrupted after reproducing the
  cache and Chinese timing defects. Neither is used as a release result.

No frozen contracts, installed vendor packages, production records, saved
financial holds or finished-video files were edited. No new paid provider request,
deployment or live qualification is claimed.

The code changes remain in the local working tree. Restart the API and the
single worker to activate them; this audit does not start production work.
