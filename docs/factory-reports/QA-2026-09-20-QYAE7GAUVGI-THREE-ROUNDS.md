# Three-round factory QA — qyaE7GaUVGI

## Objective and completion criteria

Run exactly three fresh, sequential production runs using
<https://www.youtube.com/shorts/qyaE7GaUVGI>. Each must produce A/B/C/D
finals, playable and verified in Compare, with intended copy/footage changes,
TTS replacement, aligned captions, technical checks, inspected backend logs,
and regression-tested fixes for encountered application defects. Twelve
outputs are required; cached/shared inputs must be disclosed. No scheduling
or publishing. Final delivery/cleanup follows `docs/google-drive-uploads.md`.

Source objective: user-provided pasted-text-1.txt, read on 2026-09-20.
This report is in progress, not a completion claim.

## Authority and baseline

- New QA spending authority: user replied **“unlimited”** on 2026-09-20 to
  the request for total/per-round USD and ElevenLabs-credit ceilings. This
  authorizes quoted work for exactly these three rounds, not extra runs,
  blind ambiguous retries, credit purchases or publication. Prior approvals
  are not reused. Round-specific category budgets start at $25/5,000 credits
  as finite accounting envelopes, increased for quoted needs under this new
  approval; these are not user-imposed ceilings or a claim of actual cost.
- Production runs started: **1 of 3**. Paid usage is tracked below as work runs.
- Branch: `feat/factory`; HEAD: `24537397d2d71ec1fcaaae069b7740bd114cbcee`.
  Existing dirty worktree changes retained; no blanket resets/stashes/commits.
- Seed registered through the dashboard:
  `seed-youtube-991b37f63be3d124`. Canonical URL and native ID match the request.
  Source now imported and attached through the public app API: **media_ready**.
  Artifact `art:68ea8e9c737ff8a7`, SHA-256
  `68ea8e9c737ff8a7fc6b4fa74964b1019f945a8eda0f9ce6ea4ce4090feb811c`.
  Downloaded source: 1080×1920, 30 fps, 62.368798 seconds, AV1 video/AAC stereo,
  15,965,009 bytes. Public metadata ID matches `qyaE7GaUVGI`; title:
  “This is that greed they talk about in the Bible!😅#food #farm #animals #cute #greed”.
  Source file: `data/factory-qa/qyae7gauvgi-20260920/source/seed-qyaE7GaUVGI.mp4`.
  No browser credentials used for acquisition. At this baseline checkpoint,
  no analysis or generation had been submitted; round 1 activity follows below.
  Full FFmpeg audio/video decode completed with exit 0 and no reported errors.
  The registered media endpoint returned HTTP 206, `video/mp4`, and the exact
  requested 1,024-byte range out of 15,965,009 bytes; preview serving works.
  Browser inspection also confirmed the selected URL and decoded cattle-footage
  preview for this seed (not the prior seed). This is source verification, not
  a generated-output or narration/caption-quality verdict.
- Baseline API PID 965 on port 8100 was healthy. Exactly one checkout worker verified:
  PID 57756, with fresh heartbeat. Queue has no running/ready generation work.
- Configured readiness reports Vertex, audiovisual analysis, ElevenLabs,
  generated music and Canvas installed/authenticated/tested/qualified. This
  does not establish provider credit balances or authorize spend. Explicit
  non-billable readiness refresh succeeded; ElevenLabs reports that credential
  verification occurs at its transport boundary, not a verified credit balance.
- Existing run `auto-bbf59fdd645e4bdb` remains paused at blueprint AI review;
  its unresolved speech evidence and both recovery choices are visible. It
  is not part of this QA batch and is not resumed or overridden.
- Safe rotating API/worker logs inspected. Current API/worker sessions have
  startup records; no new QA execution/error records existed at baseline. Historical
  AI-review pause is not misattributed to the new seed.
- Full offline `make test` baseline: **1,255 passed**, two dependency
  deprecation warnings, 804.90s. Terminal session `61449` finished with exit 0;
  no duplicate test process was started.
- Entire dashboard regression baseline: **55 passed**, 11 test files, 1.60s.
- TypeScript/Vite production build: **passed**, 50 modules; current built
  dashboard bundle `index-BK3Bm8HY.js`.

## Round ledger

| Round | Run ID | Status | A/B/C/D outputs | Verdict |
| --- | --- | --- | --- | --- |
| 1 | `auto-d1430de0ec7d4452` | Paused: replacement review hit output-token limit; original timeout still unresolved | None | Blocked; not passed |
| 2 | Not created | Must follow round 1 verification | None | Not evaluated |
| 3 | Not created | Must follow round 2 verification | None | Not evaluated |

For each round, record source/master hashes, language/voice, declared variation
regions and hypotheses, run/experiment/revision IDs, final artifact hashes and
technical probes, playback observations, caption/audio checks, Compare reload
checks, log/attempt evidence, fixes and tests, Drive verification receipts and
service cleanup. Separate reported/estimated usage from confirmed charges and
list unresolved holds without releasing them on assumptions.

## Round 1 — analysis and timeout investigation

- Source evidence and initial audiovisual analysis completed. Analysis identified
  11 scenes; AI correction review then began at 21:56:06 UTC and failed at
  21:57:12 UTC on 2026-09-20. No TTS, footage generation or finals yet.
- Provider/model: audiovisual analysis / `gemini-2.5-flash`; configured output
  language `en`, voice `cgSgspJ2msm6clMCkdW9`; music generation disabled.
- Failed review job:
  `effect-f32090a3b017bf6b86e5c712a7e3d5f08b3c06d1d6760fcfc57ce42a555efd16:0`.
  Its first attempt is `unknown`. Saved receipt
  `sync-85a2f4b04ea487ac1818de98a57774a6` contains no completed response,
  provider-response evidence or pre-request failure proof.
- Non-billable reconciliation job `cmd-9fd0fc88fba14280b8965fdb996a48a3`
  completed, attached the existing local receipt identity, and left the
  original attempt unknown. No remote Google operation ID was recovered;
  the `sync-` identity is local, not a remote job ID. No replacement submitted.
- Narrow Google Cloud Logging query for the request window returned zero
  matching entries using the app's credentials. Absence of entries does not
  prove failure, completion or no charge. The separate gcloud CLI credential
  required reauthentication; the app credential worked for the log query.
- Accounting: initial successful analysis reservation `rsv:0cc630610fed45b8`
  still holds a $0.25 estimate because the adapter supplied no actual USD cost.
  Timed-out review reservation `rsv:739adb527dd44595` is ambiguous at $0.25.
  Total encumbered against the round-specific USD budget: $0.50; **neither is
  a confirmed invoice charge**. Overlapping budget lines are not extra charges.
  No hold was released or reclassified by this investigation.

### Confirmed defects and scoped fixes

1. Transport timeout lost its useful category: raw `TimeoutError` became
   `unclassified_transport_failure`. The Vertex analysis boundary now converts
   direct and urllib-wrapped timeouts into safe `analysis_timeout` diagnostics,
   still classified ambiguous. It never records a timeout as unsent/free.
2. Scene review displayed generic Resume / content-override guidance despite an
   unresolved provider request. Recovery now derives guidance from durable
   attempts, preserves the hold, and asks for reconciliation. Historical pauses
   receive corrected read-only guidance without rewriting audit history.
3. The status bar appended “Choose Manual fix or Proceed anyways” regardless
   of the required recovery. That suffix and unusable Resume control are now
   suppressed for reconciliation-required pauses; the content override remains
   disabled and backend resume guard remains enforced.

Evidence: the offline worker → attempt → dashboard API regression reproduced
the exact original message before the fix. Both direct/wrapped timeout cases
now pass, asserting unknown status, retained hold, no second submission,
secret-safe output, and read-only historical recovery. Dashboard regression
also failed before the fix and passed afterward. Full dashboard suite:
**57 passed** on two consecutive full dashboard runs; TypeScript/Vite build
passed (`index-CsLmFfIt.js`). Backend surrounding regression suite:
**121 passed**, two dependency deprecation warnings, 346.88 seconds. Command:
`.venv/bin/python -m pytest -q -x tests/test_factory_ai_scene_review.py tests/test_factory_analysis_timing_recovery.py tests/test_factory_auth_recovery.py tests/test_factory_autorun.py tests/test_factory_run_prevention.py tests/test_factory_repairs_effects.py`.
This is post-patch targeted regression coverage, not a claim that the full
1,255-test baseline was rerun after the patch. `git diff --check` passed.

Additional test findings:
- The first broad backend invocation, under restricted process permissions,
  timed out in the owned local renderer. Its supervisor receipts remained
  prepared without process identities. The same end-to-end scene test passed
  when rerun with the required local process permissions; no renderer code
  was changed to conceal an environment failure.
- An older authentication test expected the raw timeout exception; its
  expectation now asserts `ProviderError('analysis_timeout')`, retaining
  unknown-state, reservation and no-resubmission assertions.
- One dashboard learning-loop test intermittently checked the request before
  asynchronous session/API work finished. Its assertion now waits for the
  actual request, not just invocation of the click wrapper. The same full
  suite passed after this test-only synchronization fix.

Deployment verification: owned idle worker/API restarted to PIDs 44640/44527
(API port 8100). Before/after snapshots of jobs, attempts, reservations,
reservation lines and runs were identical. Browser reload verified the exact
seed/run and corrected reconciliation-required message in the live status bar;
no new request was submitted. Logs show the safe restart and no new QA work.
Services remain available for recovery and the remaining rounds, rather than
being cleaned up as though final-video delivery had completed.

The actual provider-side reason for the original timeout remains unproven. Its
HTTP transport had a 60-second timeout and the job lasted about 66 seconds,
which cannot distinguish provider latency from a network interruption.

### Explicitly approved replacement — 2026-09-20

The user answered **“yes”** to exactly one replacement review, accepting
possible duplicate cost while retaining the original $0.25 hold. A scoped
Resume action now binds this exception to the exact paused run, blueprint,
attempt and latest reconciliation event. It requires explicit duplicate-cost
consent, reviewer and evidence, permits only one replacement per run, records
the prior plan/auth/job identities, and leaves the old attempt and reservation
unchanged. A replacement receives a fresh normal quote and budget check.
No generic Resume or stale consent can authorize a further replacement.

Offline tests: **20 scene-review tests passed** (71.06s), including both a
successful replacement through local finals and a second failure that must
stay paused. **60 analysis/auth/effect tests passed** (1.02s). The audiovisual
HTTP response wait is now 180 seconds, still bounded with no retry; unrelated
HTTP routes remain at 60 seconds. This improves response headroom, not proof
of the first timeout's cause. Owned API/worker restarted to PIDs 86941/87002,
preserving execution/accounting snapshots exactly.

Live approval recorded once; replacement job:
`effect-e2ff92a9c67751cd0451a9b76011fbeb2de739fa96ef92a711f924b3b2e33e8f:0`.
It started at 22:23:28 UTC, returned HTTP 200 at 22:24:11, and paused with
`analysis_incomplete`, `finishReason=MAX_TOKENS` (event **6007**). This is a
returned, unusable response, distinct from the original missing response.
Its JSON is truncated midway through transcript entry 3 and cannot be safely
reconstructed. No partial scene verdicts were adopted.

Provider-reported token usage: **19,547 input**, **3,581 candidate output**,
**4,597 thinking**, **27,725 total**. This is usage metadata, not confirmed
USD charges. Response SHA-256:
`6a22e521bda179345f7e55c130eb98278bcf70ea2ba6358a430d61fa56de3c9d`.
Replacement hold `rsv:cb39471f2b464560` remains ambiguous at $0.25 pending
evidence-backed accounting. Original hold `rsv:739adb527dd44595` remains
ambiguous and unchanged; initial successful-analysis hold remains $0.25.
Total round encumbrance is now **$0.75**, not three confirmed charges.

Preventive fix following the returned response: review output previously
included word alignment despite the prompt and `maxItems: 0`. The provider
review schema now omits word-level fields entirely, and only absent alignment
is represented locally as an empty array. Unexpected nonempty word stamps
still fail validation. Review output allowance increases from 8,192 to 16,384
tokens; other analysis tasks retain their existing allowance. All scene,
speech, timestamp, verification and content checks remain mandatory.
The output-limit diagnosis is now explicit in the status message. New offline
schema/headroom and incomplete-response regressions failed before these fixes
and pass afterward. Final scene suite: **21 passed** (71.04s). Targeted
analysis/auth/effect plus incomplete-message suite: **62 passed** (2.41s;
one case also belongs to the scene suite). `git diff --check` passed.

No third review request was sent. This one-time exception is consumed; neither
the original hold nor the replacement's incomplete-response evidence was
deleted, refunded, marked uncharged or hidden.
The tested response-format/status fix was deployed with owned API/worker
PIDs 5592/5653. Before/after execution/accounting snapshots matched. Browser
reload at 22:30 UTC verified the correct seed/run, 29% paused progress,
explicit incomplete-response explanation and disabled content override.

## Issues and limitations

The recovery defects above are reproduced and patched; the paid request outcome
remains unknown. Round 1 is paused, not completed. All
12 generated outputs, per-round playback/variation checks and final
delivery/cleanup remain unverified. Run-specific logs and current holds were
inspected as recorded above; actual provider charges remain unconfirmed.

The explicit one-replacement decision above has been consumed. The run is
paused again on a different, evidenced output-limit failure. No further paid
replacement is assumed from that one-use consent.

**Historical funding blocker resolved:** the user's “unlimited” approval
provided new authority for the three-round task. Existing global headroom was not
itself new QA authorization,
and overlapping aggregate budgets must not be summed as independent funds.
Continue the full three-round objective under that approval; do not count these
baseline checks as a production round or as goal completion.
