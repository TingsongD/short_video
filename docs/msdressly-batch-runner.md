# Sequential MsDressly production

`python -m modules.batch run` continues the active video from saved state. It
creates a separate Canvas project for each haul, obtains every visual quote,
reserves the complete video plus 200 repair credits, produces ElevenLabs v3
narration, runs up to five independent Jimeng jobs within the current video,
renders the static haul typography with FFmpeg, uploads the final to Drive, and
verifies cleanup before advancing. The editable Hypit project is also retained.

The accepted batch plan sets **13,502 Jimeng credits**, **4,000 ElevenLabs
credits per video / 60,000 total**, and **$0 for other audio/model APIs**.
Existing original music is reused. A later top-up or monthly reset cannot raise
the original cap. An unfundable complete video stays queued.

## Files and checkpoints

The immutable selection is
`data/production/next-15-video-plan-20260915/next-15-video-plan.json`.
Its SHA-256 must match the saved queue. Each video has its own folder under
`productions/haul-NN/`; durable shared state lives in `batch-plan/run-state.json`.
The frozen system schemas and fixtures are unchanged.

Before each video, the producing agent writes and inspects `brief.json` with
the ten selected product IDs in order, available variant IDs, matching Shopify
image URLs, garment descriptions, styling directions, and original spoken takes.
Takes cover exactly 5,091 frames at 30 fps; each is 4–15 seconds. Titles, prices,
claims and image colors must be reconciled against the actual product images.

The runner returns immediate agent review checkpoints after narration, ready
references/clips, and the final. `ReviewReady` is exit code 3, not a failure or
a request to wait for the next heartbeat. Other accepted remote jobs can keep
running while the agent inspects ready artifacts. The producing agent inspects the actual
artifact and records its verdict; this does **not** request another spending
approval from the user. A detached shell process alone cannot perform those
creative reviews or author the next video's original copy.

The Codex heartbeat **Produce sequential MsDressly hauls** is scheduled every
ten minutes as a recovery mechanism (automation ID
`produce-sequential-msdressly-hauls`). Once active, the producing agent stays
with the current video through generation, reviews, render, QC, delivery and
cleanup. It waits on existing background jobs and does not end its turn after
each submission or status question. Review checkpoints require agent work,
not another scheduled wake or renewed user approval. Ending turns between
clips added approximately 174 minutes of avoidable wait to haul 01; see
`docs/haul-01-delay-investigation.md`. The heartbeat respects the same controller lock and
budgets, stays quiet for unchanged progress, and reports verified deliveries or
actionable failures. It pauses when the funded batch finishes, the next complete
video cannot be funded, or unresolved provider/quality/account issues require
action. This is a finite approved production queue, not an open-ended spending
authorization.

```bash
.venv/bin/python -m modules.batch status
.venv/bin/python -m modules.batch configure --jimeng-concurrency 5 --render-backend ffmpeg
.venv/bin/python -m modules.batch review-pack
.venv/bin/python -m modules.batch dry-run
.venv/bin/python -m modules.batch balance 13502 --evidence 'Current logged-in Jimeng credit-details panel'
.venv/bin/python -m modules.batch review products --verdict passed --notes 'Specific product/image/variant checks'
.venv/bin/python -m modules.batch run
.venv/bin/python -m modules.batch review narration --verdict passed --notes 'Specific speech and timing checks'
.venv/bin/python -m modules.batch review look-01 --verdict passed --notes 'Specific garment and identity checks'
.venv/bin/python -m modules.batch review clip-01 --verdict passed --notes 'Specific motion and speech checks'
.venv/bin/python -m modules.batch review final --verdict passed --notes 'Whole-film picture, captions, speech and music checks'
.venv/bin/python -m modules.batch run
```

If independent speech timing reveals drift in an otherwise sound clip, local
picture correction can preserve the already accepted narration and avoid a paid
replacement:

```bash
.venv/bin/python -m modules.batch fit-picture clip-01 --comparison review/timing-comparison.json
```

The comparison must record `same_transcript: true` after actual inspection and
at least eight ordered word pairs with `reference_start`, `reference_end`,
`generated_start`, and `generated_end`. Never set this flag to hide an omission.
The fit requires monotonic bounded speed changes, verifies the frame count and
retains the native source. Review the edited picture before recording its gate.
Both reviews and Hypit rendering use the edit only while source, edited-file and
speech hashes match. Changing a previously rendered section's inputs blocks
stale-output reuse. A finished export requires an intentional new version.

Use the live balance visible in the user's logged-in Chrome profile; never copy
the example balance into a later observation. The CLI's current account command
does not provide reliable credit-balance data. Refresh the observation between
videos. Inspect the full `quotes.json` before the first submission; the accepted
batch limits govern routine quotes within scope.

Canvas rejects quotations that reference an outfit node with no output yet.
Initial video quotes therefore use the accepted presenter and voice sample,
with the intended product, model, duration, resolution, count and the same
two-image/one-audio reference configuration. These drafts are **never generated**
with the provisional performance. The approved outfit and exact new narration
replace those references before each run; the prompt/settings are read back and
the native quote is refreshed. An increased price stops before submission.
Accepted presenter/voice resources may be borrowed from the preceding Canvas;
Shopify image references are imported through official server-side URL fetching.

## Recovery and corrections

- Submission IDs, node IDs and reservations are persisted before a paid request.
  An ambiguous Canvas response stays unknown. Resume only reads the same
  submission through status/wait and downloads that existing resource.
- A download failure retries the download, never generation. An ambiguous
  reference upload remains at its saved resource ID for inspection.
- TTS persists a reservation before POST and saves its returned audio/alignment
  before fitting. An incomplete response requires reconciliation; the controller
  does not POST again. Text changes do not silently reuse a charged request.
- All quotes must cover the whole video. Native per-shot credit ceilings apply
  at submission. Failed/unknown charges remain conservatively held.
- After a confirmed visual defect, `review KEY --verdict failed --notes ...`
  followed by `repair KEY --prompt-file revised-prompt.txt` creates one intentional
  replacement. At most one per shot, two image and two video replacements per
  video, and 200 credits total. Every replacement receives a fresh quote.
- Render build IDs are saved. If the build response itself is lost, reconcile
  Hypit's build history; do not launch a duplicate blindly.
- If Drive upload loses its response, look up the exact filename and verify its
  parent, byte size and MD5. Reuse the matching upload. A missing or conflicting
  result pauses delivery rather than uploading again automatically.

## Completion and resource cleanup

Completion requires all three: inspected QC, verified Drive delivery, and
verified process cleanup. Every exit path also attempts cleanup, including
review checkpoints and upload failures. It gracefully stops the project runtime,
then signals only recorded processes whose PID, birth time and command still
match. Owned ports must be free, memory-pressure free percentage at least 15%,
and disk space at least 25 GiB before advancement. It does not purge system
caches, kill unrelated applications or delete source/final files.

The delivery receipt includes SHA-256, MD5, size, folder, filename and Drive ID.
An upload failure retains the final and pauses the queue; the next run resumes
delivery. Videos are not published to social platforms by this runner.

## Captions, audio and validation

Returned ElevenLabs character times are transformed through the exact trim and
tempo used for each take. Progressive captions use Hypit's supported named XML
entities, preserving apostrophes and ampersands. A real local render smoke test
verifies these characters against Hypit's parser and rendered pixels.

An optional isolated local speech checker is available:

```bash
uv venv --python 3.12 vendor/speech-qc/.venv
uv pip install --python vendor/speech-qc/.venv/bin/python faster-whisper==1.2.1
vendor/speech-qc/.venv/bin/python scripts/batch_speech_check.py narration.wav \
  --expected-text-file copy.txt --output local-transcript.json
```

It downloads the public `base.en` weights once, then transcribes locally without
paid analysis calls. Its transcript is supporting evidence, not proof of visual
lip synchronization. [Faster Whisper documentation](https://github.com/SYSTRAN/faster-whisper).
Use `--model small.en` for a stronger local check when the base model misses a
word; those public weights are also cached. Compare transcription of both the
generated track and the exact narration recording before concluding that the
video omitted speech.

Offline tests cover budget caps, complete quote coverage, durable spending holds,
single-controller locking, unknown submissions, download recovery, narration
limits, Drive ambiguity/checksum mismatches, cleanup on failure, PID reuse,
caption escaping and transformed word timing. `make test` never calls paid APIs.

## Five concurrent jobs and faster local work (16 September 2026)

The user explicitly authorized five parallel video clips. The scheduler has one
state writer and five remote slots shared by images and clips. Clips are eligible
only after their exact outfit reference passes review. Every loop checks all
active operations, downloads completed resources, fills free slots and hands
ready evidence to the agent. A slow earlier job cannot hide later completions.
Saved ambiguous submissions block additional spending; status and download retry
only existing IDs. Service-side execution capacity can still queue accepted jobs.

`review-pack` prepares reference comparisons, native two-frames-per-second grids
and paired local Whisper word transcripts in one process. Results are cached by
source, reference, voice, brief and tool hashes. No artifact is auto-approved.
Transcript differences remain visible and timing candidates have
`same_transcript: false` until genuine inspection. Keep the agent active and
resume immediately after recording reviews. `progress.json` reports readiness
and timestamps even while the controller holds its lock.

The native FFmpeg/libass path renders all ordered pictures, progressive captions,
product labels and the opening brand reveal in one pass with bounded CPU use.
It retains Hypit's editable project, preserves 5,091 frames, uses the existing
speech/music mix and applies full technical QC. Existing partial Hypit builds
continue through their original backend to preserve recovery. Input changes
invalidate cached render receipts. Browser text effects beyond this haul's
static design still belong in Hypit; the two renderers use slightly different
font rasterization/shadows.

An isolated replay of haul 01, using approved existing media and no paid calls,
finished the 169.7-second export and full technical checks in **36.23 seconds**,
versus **31m14s** for its original twenty captioned sections (about 52 times
faster for rendering). Sampled opening, caption and closing frames were reviewed.
This does not measure cloud-generation acceleration or certify the next film.
Evidence: `productions/haul-01/review/speed-benchmark-v2/`.
