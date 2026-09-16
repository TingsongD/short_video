# Validation Gates — Sign-off Log

Each gate per BUILD_PLAN.md §3. Status: ✅ signed / ⬜ pending / ❌ failed.
Live gates (G1, G5–G10) additionally require human key/spend approval (Wave 3).

| Gate | Module | Status | Evidence | Signed by | Date |
|---|---|---|---|---|---|
| **G0** | M0 Foundations | ✅ **SIGNED** | `make test` green (folders, config, secrets shape, schema round-trips); `uv run python cli.py --help` runs in vendor/MoneyPrinterTurbo; no key-shaped strings in tracked files; vendor pins in docs/vendor-pins.md | coordinator (Wave 0) | 2026-09-14 |
| G1 | M1 Niche Radar | ⬜ pending | unit criteria met 2026-09-14: schema-valid report from fixture scan, quota counter caps search calls + degrades to channel-only, historical breakout flag at 5x/2x/14d. 2026-09-15: Viral Outliers + strict views/followers >2 integrated; 300 offline tests pass, key verified, balance 0; live search pending (see addendum) | — | — |
| G2 | M2 Idea Grill | ⬜ pending | unit criteria met 2026-09-14: 4 hard-reject rules fire correctly, thresholds at exact boundaries, temp-0 determinism, schema-valid output, raw judge output logged. Live audit (≥30% kill, ≥8/10 agreement) pending real LLM | — | — |
| G3 | M3 Format Library | ⬜ pending | unit criteria met 2026-09-14: CRUD + stable IDs, extract validates + no-copy guard (>0.6 Jaccard rejected), match = exactly 1 default + labeled alt, promote/retire at exact thresholds. library.json seeded offline with 10 pattern entries (2026-09-14 patch); radar-extracted refresh pending G1 + LLM | — | — |
| G4 | M4 Hook Bank | ⬜ pending | unit criteria met 2026-09-14: bank.json schema-valid, selector matches niche+type w/ niche fallback, attribution preserved, LookupError on empty niche. Bank topped up to 5/niche: 12 curated + 18 labeled `original-pattern` (2026-09-14 patch); authentic viralhooks.org curation per docs/hook-curation.md still pending | — | — |
| G5 | M5 Script Engine | ⬜ pending | unit criteria met 2026-09-14: 60-110w bound enforced, hook verbatim first sentence, 4-7 shots w/ durations tracking voice est, idx0 forced video, per-shot Pexels fallback, schema-valid shot_list. Human approval of 5 scripts pending LLM | — | — |
| G6 | M6 Asset Pipeline | ⬜ pending | unit criteria met 2026-09-14: intake validates (≥720px, ≥3s, rejects bad/zero-byte), filename→shot_idx mapping + provenance tags, manifest schema-valid w/ missing_shots, Pexels fallback mocked, selector map parses. Lane B real drop + Lane A smoke pending | — | — |
| G7 | M7 Voice | ⬜ pending | unit criteria met 2026-09-14: request payload (voice_id/model/text) verified, text re-cleaned before send, 15-60s ffprobe gate (20s ok / 8s rejected). Real generation + blind listen pending keys | — | — |
| G8 | M8 Assembly | ⬜ pending | unit criteria met 2026-09-14: mpt_task maps manifest->MPT fields (local source, assets/ rel paths, word_by_word subs, 9:16), batch ≤100 validated, QC checks res/audio/duration/size + frame extract. Real MPT run + operator watch pending | — | — |
| G9 | M9 Publishing | ⬜ pending | unit criteria met 2026-09-14: metadata bounded (≤100 title, ≤15 deduped tags, CTA enforced), record schema-valid + dupes rejected, cadence blocks 3rd daily post. Real publish pending | — | — |
| G10 | M10 Readback | ⬜ pending | unit criteria met 2026-09-14: tz-safe 48h/7d/28d scheduling, win=2x median & AVD>=70%, readback schema-valid, verdict feeds M3 promote/retire, weekly summary emitter. Live pulls pending keys | — | — |
| G11 | M11 Orchestration | ⬜ pending | unit criteria met 2026-09-14: `run.sh produce/readback/weekly/approve/cron-line`; cost ledger appends + hard-stops at weekly cap before the call; approval gate blocks unapproved spend (token/env/TTY); stages run in order, first failure stops + logs run record. Live weekly cron fire pending `install-cron` | — | — |
| G12 | M12 E2E | ⬜ pending | unit criteria met 2026-09-14: `test_e2e_dry.py` M1→M8 fixtures schema-valid in order; `test_failure_drills.py` — 8 drills each fail loudly at the right gate; per-stage `duration_s` in run records; `docs/e2e-report.md` template ready. Real published video, ≤30 min human time, cost in cap, 48h readback still pending | — | — |

## G0 evidence detail (2026-09-14)

### Canvas integration addendum (2026-09-14)

G6 offline coverage now includes the official Canvas subprocess protocol,
preflight model/parameter checks, quote ceilings, ambiguous submission recovery,
download retries, media-kind matching and explicit stock fallback. Full suite:
208 passed in 15.20s. Canvas CLI 1.0.1 installed; separate authorization expired.
Account/catalog checks, quoted pilot and full live asset set remain pending.
No credits spent; G6 remains unsigned. See `docs/jimeng-canvas-cli.md`.

G8 addendum: actual FFmpeg tests verify ordered video/still preparation, narration
timing, insufficient footage and cache reuse. MPT subprocess tests verify result
JSON, task failures and copying the returned vendor output instead of accepting
stale finals. The local MPT launcher disables auto-upload and selects Whisper for
custom-audio subtitles. Its `--help` smoke test passed. Full rendered MPT workflow
and operator review remain pending; G8 remains unsigned.

Native MPT follow-up: a schema-valid batch with local fixture media rendered
successfully. The returned file under `storage/tasks/6c3b445e-10a6-4f16-8523-d274609e550c/`
was copied into `data/production/v-mpt-local-smoke/final-1.mp4`; QC passed for
1080×1920, audio and eight-second narration timing. Evidence is in that production
folder's `assembly_result.json` and `qc_report.json`. Subtitles were disabled;
this does not sign off the full subtitle or Jimeng workflow.

G11 integration: quoted Canvas batches now pause before spending, resume reuses
saved script/narration/finals, credit reservations remain separate from USD,
manual replacement does not replay rejected generation, and production defaults
to a QC review stop. Offline integration tests cover these paths and verify
returned final retrieval. No publishing or paid generation has occurred.
Full offline suite: **225 passed in 24.76s**. Frozen schemas/fixtures unchanged.
G6/G8/G12 remain pending their live account, generation, subtitle and review steps.

2026-09-15 recheck: 225 tests passed in 25.60s. Fresh local MPT fixture assembly
passed resolution/audio/duration QC (1080×1920, 8.07 seconds); subtitles disabled.
Canvas login remains pending. Isolated Hypit 0.1.8 installation and one-shot
HypiHub source check passed; its plan/doctor identify missing credentials.
No paid generation occurred. These checks do not sign G6/G7/G8/G12. See
`docs/setup-test-guide.md` and `data/production/setup-test-evidence.json`.

Authorization follow-up: both OAuth flows completed. Canvas account/catalog
checks and one saved five-second Seedance fast quote passed (30 Jimeng credits).
Node ID and native stderr protocol regressions fixed; **229 tests passed in
23.81s**. HypiHub's requested Seedance fast capability passes preflight and its
authenticated rates estimate 142.6 credits / US$0.713 for the matching shot.
Both spends remain unapproved. The user's Chrome canvas editor reports
`draft_reader_too_old`; CLI save/read/quote succeed. G6/G8/G12 remain unsigned.

Approved pilot follow-up (2026-09-15): the user approved both single-shot tests.
Jimeng generated and downloaded one five-second 720×1280 video under a native
30-credit ceiling. Checksum, full FFmpeg decode and M6 intake passed; sampled
frames show steam and camera motion. The manifest records Jimeng provenance and
correctly retains missing shots 1–3. Wait timeout and download failure recovered
using the original submission, without regeneration. New timeout regression
coverage passes; full offline suite **230 passed in 24.40s**.

HypiHub's one matching build failed with HTTP 402 `insufficient_credits` during
submission, with zero outputs. Its receipt is retained; no top-up or repeat
generation occurred. The quoted estimate remains separate from Jimeng credits;
settled charges were not independently verified. Evidence is in
`data/production/setup-test-evidence.json` and the two pilot directories.
G6/G8/G12 remain unsigned pending full asset coverage, real narration/subtitles,
assembly and human review. No publishing took place.

Hypit local editing follow-up (2026-09-15): the global Hypit Skill and local
runtime are installed. The existing Jimeng coffee clip rendered successfully
with two timed titles and original audio: five seconds, 1080×1920, 30 fps, AAC.
Full decode and existing assembly QC pass using the authored five-second timeline
as the duration reference; this is not real narration verification. Encoded frame
review shows both titles and motion; the user's Chrome Studio plays to the final
frame. Listening and creative acceptance remain for the user.

The initial local render failed on Hypit 0.1.8's missing capture-child package
resolution. A version-checked project bootstrap now loads the native resolvers;
an offline child-process import regression passes. The repaired render reused
the existing normalized clip and planned three local requests, zero hosted calls.
No additional generation spend. Full suite: **231 passed in 25.48s**. Evidence:
`data/production/v-jimeng-hypit-pilot/pilot_qc.json`, local build receipts,
`data/production/setup-test-evidence.json`; instructions in
`docs/jimeng-hypit-workflow.md`. G6/G8/G12 remain unsigned for full asset coverage,
narration, speech-aligned captions and operator acceptance.

G7 setup follow-up (2026-09-15): ElevenLabs credential saved privately. Account,
voice list and model discovery return HTTP 200; 30 voices and `eleven_v3` are
listed. No audio generation performed. Voice choice, actual synthesis permissions,
duration validation and blind listening remain pending; G7 stays unsigned.
Sanitized evidence: `data/production/elevenlabs-setup/verification.json`.

Credential-loader follow-up (2026-09-15): root `.env` support and Git exclusions
added following the user's selected credential location. Regression coverage
verifies source precedence, working TOML fallback, path isolation, literal values
and errors that omit credential contents. Full suite **239 passed in 26.22s**.
The new `.env` was empty on disk; Google route/auth/model access and TTS/music
generation remain unverified. Existing ElevenLabs credentials still load.
G7/G8/G12 remain unsigned. See `docs/audio-providers.md`.

Saved-credential follow-up: the new `.env` is now populated. ElevenLabs account
verification passes using it. Vertex key checks for token counting pass for
Gemini 2.5 Flash/Pro TTS in `us-central1`. These are not synthesis tests.
Project Interactions listing rejects key authentication. Cloud reauthorization
has since completed: both OAuth catalog and project Interactions listing return
200. Direct catalog lookups verify Lyria 3 Clip/Pro preview model records;
Lyria 3.5 lookup returns 404 on this route. Actual speech/music generation,
quota and audio quality remain unverified; no audio generation submitted.
Receipts: `data/production/google-audio-setup/verification.json`.
G7/G8/G12 remain unsigned.

Authorized Vertex audio pilot (2026-09-15): one Gemini 2.5 Flash TTS request
(Kore) and one Lyria 3 Clip preview request both return HTTP 200. Narration is
14.531 seconds at 24 kHz mono; music is 28.813 seconds at 44.1 kHz stereo. Both
fully decode and contain audio. Local mixed preview passes decoding with peak
-4.5 dBFS. Two generation calls total, no retries; estimated $0.043666 recorded,
settled billing unverified. Evidence: `data/production/v-vertex-audio-pilot-20260915/test-report.json`.
This verifies those Vertex generation routes; G7/G8/G12 remain unsigned because
the short narration is below the production minimum, listening/voice comparison
is pending and no full production video was assembled in this test.

- Folder tree per plan: `data/{radar,grill,formats,hooks,production,published,analytics,costs}`, `modules/`, `schemas/`, `tests/fixtures/`, `vendor/`, `config/`, `logs/`, `docs/`
- Vendored: ai-marketing-skills @ `bc84dbc`, MoneyPrinterTurbo v1.3.7 @ `cf5a3ae` (uv sync --frozen, Python 3.11)
- Contracts frozen: 9 schemas × 9 valid fixtures + 1 negative fixture, all round-trip via jsonschema
- Media fixtures generated with ffmpeg (312 KB total): good/bad/zero-byte video, image, 20s/8s voice
- CLI smoke test: `cli.py --help` OK (sources: pexels/pixabay/coverr/volcengine_seedance/ofox/metaso_minimax/openai_image/local confirmed)

## Viral Outliers discovery addendum (2026-09-15)

- **G1 unit criteria:** configured provider is Viral Outliers for YouTube/TikTok;
  strict unrounded views/followers >2 replaces the previous combined median
  gate for current runs. Evidence normalization, missing-date/media rejection,
  duplicate removal, creator confirmation and frozen report validation pass.
- **G2/G3 handoff:** follower ratios and unavailable-median metadata reach idea
  prompts; TikTok references remain TikTok links in extracted formats.
- **G11 unit criteria:** CLI and weekly workflow share provider selection.
  Explicit batch ceilings and existing weekly dollar caps precede submission.
  Durable receipts stop uncertain retries, preserve partial responses, and
  recheck unexpected charges after a restart. Scheduled runs receive no new
  implicit paid-search approval.
- Full offline suite: **300 passed in 26.22s**. Schemas and frozen fixtures
  unchanged. New tests do not contact any service or use real credentials.
- Free live checks: key authenticated, available balance **0**, search price
  **1 credit**. Teaser feed returned 12 posts with no publication timestamps;
  these are browsing evidence, not accepted fresh candidates.
- Prepared two-platform `ai tools` pilot: **2 credits** nominally **$0.02**.
  No paid search or billing action performed. Account credit allocation,
  approved paid pilot, actual search response mapping, relevance and YouTube
  coverage remain pending. **G1/G2/G3/G11 are not signed off by this addendum.**
- Guide: `docs/radar-viral-outliers.md`; private checks and the plan are in
  `data/radar/viral-outliers/`.

### Approved pilot attempt — 2026-09-15, 21:37 UTC

User approved the prepared two-search Viral Outliers pilot. Execution with a
2-credit ceiling stopped at preflight: authenticated account balance remains
0. Neither search was submitted; no credits were spent. Approval is retained
for this batch, but credit availability blocks the live test. Receipt:
`data/radar/viral-outliers/viral-pilot-20260915/last-attempt.json`. G1 remains
pending; latest full offline suite is still 300 passing (no code changes).

### Direct product-reference pilot — 2026-09-15

Read-only Shopify Admin access verified for the user's selected checkerboard
tank. Its one product image was imported into official Jimeng Canvas CLI 1.0.1;
readback confirmed image-node reference, upstream connection and prompt binding.
One five-second Seedance 2.0 Fast VIP `m2v` generation succeeded under a 30-credit
ceiling. Native checksum/size checks, M6 intake and full media decoding passed
at 720 × 1280. Six sampled frames show recognizable front garment details with
subtle movement; user visual review is pending. A silent preview retains the
original video stream and runs 5.017s. Evidence:
`data/production/v-product-variation-Db9SrsBsIUg/test-report.json`.

This supports the image-reference route for G6 but does not sign off a complete
shot set or G6/G8/G12. The original reference video was not used as a model
input, and no full outfit-change edit, lip sync, automatic Shopify/M6 importer,
new narration/music or publishing was tested. Latest offline suite remains
300 passing; no production code or frozen contracts changed.

### Hypit adaptation layout preview — 2026-09-15

Prepared a 30s product try-on adaptation and saved the official Canvas image /
video drafts. Its paid generation and transcription are pending a separate
budget decision. A five-second Hypit layout preview completed locally using
the previously generated product-motion footage. Export decoding and sampled
typography checks passed at 1080 × 1920, 30fps, 5.0s; the source is 720p and the
preview is silent. This verifies local composition and export, not the planned
speaking performance or outfit changes. Full-production validation stops at
missing future footage. G6/G8/G12 remain pending; no production code changed.
Guide: `docs/hypit-reference-variation.md`.

### Full-length multi-product preparation — 2026-09-15

The user superseded the 30-second adaptation with an exact 169.700-second /
5,091-frame multi-product haul, original copy and ElevenLabs v3. Eleven actual
MsDressly product references and a full-duration storyboard are prepared.
Hypit check and render-plan preflight pass with no paid-provider requests;
Studio opening/final frames were inspected. Selected Jessica from the live
catalog, without generation. A new commission ceiling is pending approval;
no dependent full-film quote, new narration, footage or music is complete.
This is preparation evidence, not G6/G7/G8/G12 sign-off. Frozen contracts and
production code are unchanged. See `docs/hypit-reference-variation.md`.

### Approved narration and failed first speaking clip — 2026-09-15

ElevenLabs v3 / Jessica generated thirteen original speech sections, edited to
169.700s. Scribe supplied actual final word times; automated audio review
reports natural delivery. Hypit rendered the complete narrated catalog-still
storyboard, build `bld_20260916T025522799Z_0692BF6AA1`. This provides M7/M8
production evidence but does not complete the requested try-on film.

A new Canvas presenter still was inspected. The first ten-second speaking clip
failed visual QC because source identity and text leaked into the output.
Remaining paid jobs are paused; a corrected 60-credit replacement is prepared
for approval within the already accepted 2,000-credit cap. Vertex music was
rejected without an output. G6/G8/G12 remain unsigned for this production.

### Automated continuation approved — 2026-09-15

The user approved the 60-credit corrected opening and then automated video generation within the existing commission ceilings. The replacement completed under the same saved submission ID and passed sampled visual inspection plus automated audiovisual review; no copied presenter or text was seen. Its review remains automated rather than a human listening signoff. Nine remaining outfit images are generating sequentially at their recorded eight-credit quotes. A fresh concise instrumental brief on Lyria 3 Clip returned 27.742 seconds of original stereo music; the earlier Pro rejection remains recorded. Final music fitting, remaining footage and the completed film are still in progress.

All ten outfit references have now passed visual inspection; the red-pullover reference required one eight-credit correction from an incorrect open cardigan. Native quotes for the remaining 17 speaking clips total 1,008 credits; with 262 already reserved, the planned total is 1,270 of the approved 2,000. Sequential generation has started. Opening review v2 is locally rendered and inspected, with larger typography; build `bld_20260916T032440396Z_8D72922EED`, 275 frames at 30fps. Original music is fitted beneath the preserved ElevenLabs narration. Full film is still in progress.

### Scoped evidence: approved full-length Hypit commission (2026-09-15)

The user approved the full commission, corrected opening and automated generation.
The local film is complete for owner review; this addendum does not sign the
MoneyPrinterTurbo, human-approval or publishing requirements of G6/G8/G12.

- **Artifact:** `data/production/v-product-variation-Db9SrsBsIUg/hypit-full-length-01/MsDressly_Full_Haul_2m49s.mp4`.
- **Technical pass:** 169.700s picture/audio target, 5,091 frames at 30fps, 1080 × 1920, full decode, no black intervals, audio peak −1.6 dBFS. SHA-256 `c43c105ebb1a8039a213b54626f151726ee0121d8e1cee29a8d94420c0ac6e65`.
- **Asset evidence:** eighteen selected edited clips, ten selected outfit references, eleven catalog products. Generated picture is 720p before upscale; tight local crops reduce effective detail further. Rejected attempts are retained and explicitly excluded.
- **Timing:** exact source picture duration preserved. Independent ASR found drift missed by earlier broad model checks; sixteen clips were fitted to actual word times, with product close-ups where native generated speech omitted or repeated words. ASR alignment is approximate, not proof of perfect mouth timing.
- **Assembly evidence:** eighteen completed local Hypit section builds; out-of-range pruning matched a full-source 115-frame comparison exactly (SSIM 1.0). Full soundtrack is mixed continuously during the final stream-copy picture join. `rendered-sections/`, `render-equivalence.json` and `delivery-manifest.json` record provenance.
- **Review evidence:** final sampled opening/outfit/transition/CTA frames inspected; completed concise automated whole-film review reports no significant issues. The earlier truncated whole-film response is preserved as incomplete. Human viewing/listening signoff remains pending.
- **Spending:** 1,348 Jimeng credits; 3,979 conservative TTS credits including one validation rejection; US$1.00 conservative other-API reservations. All remain within the accepted ceilings; settled billing unverified. The dollar allocation is exhausted.
- **Handoff:** actual delivered film visible in Chrome's Hypit review at http://localhost:5188/#comments; full editable timeline at port 5187. Frozen contracts untouched; no core module changes; latest prior offline suite 300 passing.
- **Still outside this evidence:** publishing, performance/virality outcomes, human acceptance and MoneyPrinterTurbo execution. No posting occurred.
