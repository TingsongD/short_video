# PROGRESS

## Wave 0 — Foundation & Contracts ✅ DONE (2026-09-14)

- [x] M0: folder tree, git repo, .gitignore, config templates, secrets shape
- [x] Vendored ai-marketing-skills @ bc84dbc + MoneyPrinterTurbo v1.3.7 @ cf5a3ae (uv env ready)
- [x] 9 frozen JSON schemas (`schemas/`) + full fixture set (`tests/fixtures/`)
- [x] Contract tests: `tests/test_schemas.py` (valid round-trips + negative case + meta-schema check)
- [x] G0 tests: folders, config sanity, secrets shape + tracked-file key sweep
- [x] AGENTS.md ownership map, docs/gates.md (G0 signed), docs/vendor-pins.md
- [x] `make test` green; MPT `cli.py --help` smoke test OK

## Sequential build (single builder; swarm plan in AGENTS.md superseded)

- [x] M1 Niche Radar (2026-09-14): modules/radar/{client,quota,metrics,scanner,cluster,report} + CLI `python -m modules.radar`; 23 tests green; G1 unit criteria met (live scan pending)
- [x] M2 Idea Grill (2026-09-14): modules/grill/{prompts,generate,score,gate} + CLI `python -m modules.grill`; modules/common/llm.py (OpenAI-compatible, injectable); 16 tests green; G2 unit criteria met (live audit pending)
- [x] M3 Format Library (2026-09-14): modules/formats/{library,extract,match,promote} + CLI; 20 tests green; G3 unit criteria met (live seeding pending)
- [x] M4 Hook Bank (2026-09-14): modules/hooks/select.py + seeded data/hooks/bank.json + docs/hook-curation.md; 6 tests green; G4 unit criteria met (curation cadence is manual)
- [x] M5 Script Engine (2026-09-14): modules/script/{write,shots,voicetext,engine} + CLI; 15 tests green; G5 unit criteria met (script approval pending LLM)
- [x] M6 Asset Pipeline (2026-09-14): modules/assets/{queue,intake,pexels,jimeng_bridge,manifest} + jimeng_selectors.json + docs/jimeng-manual-lane.md; 17 tests green; G6 unit criteria met (Lane B real run pending)
- [x] M7 Voice (2026-09-14): modules/voice/tts.py (ElevenLabs client, injectable transport) + duration gate + docs/voice-selection.md + CLI; 5 tests green; G7 unit criteria met (real generation pending)
- [x] M8 Assembly/QC (2026-09-14): modules/assemble/{task_builder,runner,qc} + CLI; 14 tests green (ffmpeg lavfi finals rendered in-test); G8 unit criteria met (real MPT run pending)
- [x] M9 Publishing (2026-09-14): modules/publish/{metadata,record,uploader} + docs/publish-manual.md + CLI; 7 tests green; G9 unit criteria met (real publish pending)
- [x] M10 Analytics Readback (2026-09-14): modules/analytics/{pull,windows,verdict,readback} + CLI; 8 tests green; G10 unit criteria met (live pulls pending)
- [x] M11 Orchestration (2026-09-14): modules/orchestrate/{ledger,approval,pipeline,stages,schedule} + `run.sh` (produce/readback/weekly/approve/cron-line/install-cron/ledger); 18 tests green; G11 unit criteria met (live cron fire pending)
- [ ] M12 E2E — offline portion done (2026-09-14): 9 failure-drill tests green (dead LLM/TTS/YT-quota, empty Lane B, missing finals, QC fail, unapproved publish, killed idea); per-stage timing in run records; docs/e2e-report.md template. **Live run awaits keys + spend approval**

## Wave 2 — Integration ✅ DRY RUN GREEN (2026-09-14)

- [x] `tests/test_e2e_dry.py`: M1→M8 driven on fixtures only — niche_report → scored_ideas → format_library → hooks → shot_list → asset_manifest → voice.mp3 → mpt_task + batch — every contract validated against its frozen schema and asserted written in pipeline order; zero network/spend (155 tests green)
## Wave 3 — Live gates + autonomy ⬜ NOT STARTED

## Jimeng Canvas integration (2026-09-14)

- M6: official Canvas CLI adapter, model validation, quoted credit ceilings,
  private recovery journal, stable submissions, verified downloads, strict media
  intake, explicit stock fallback and doctor/prepare/generate/status/resume CLI.
- Canvas CLI 1.0.1 (83aeb67) and bundled Skill installed; dreamina preserved.
  Canvas authorization challenge expired; account/catalog and paid pilot pending.
- M6 validation: `make test` **208 passed in 15.20s**, fully offline. No contract
  changes and no generation spend. Details: `docs/jimeng-canvas-cli.md`.
- M8: ordered clips now trim videos/render stills in proportion to measured
  narration, with frame-accurate duration checks and reusable validated outputs.
  MPT runs sequentially with one output, returns actual task-file paths, and
  automatic upload is disabled in its local process. Local launcher help passed.
- M11: Canvas-first asset stage, saved quotes and review status, production
  checkpoints/resume, explicit stock substitution, assets/QC review stops, lazy
  clients and a lock against simultaneous producers. Default production stops at
  QC; `--publish` enters the existing separate publishing gate.
- Native MPT smoke passed using schema-valid local fixture inputs: eight-second
  narration, mixed video/still material, sequential 1080×1920 final with audio;
  actual task output copied into `data/production/v-mpt-local-smoke/final-1.mp4`.
  `qc_report.json` records success. Subtitles were disabled for this smoke, so
  full Whisper/subtitle rendering and a real Jimeng asset set remain unverified.
- Five-second pilot input is ready at
  `data/production/v-jimeng-cli-pilot/shot_list.json`; prepare only shot 0 after
  account/catalog verification. No pilot quote or paid generation yet.
- Operations and review instructions: `docs/production-resume.md`.
- Final offline validation: `make test` **225 passed in 24.76s**;
  `git diff --check` passed. Frozen schemas and fixtures are unchanged.

## Setup testing and HypiHub pilot preparation (2026-09-15)

- Re-ran the offline suite: **225 passed in 25.60s**. Fresh native MPT fixture
  assembly passed QC: 1080×1920, 8.07 seconds, audio present; subtitles disabled.
- Current Canvas status requires authorization. LLM/ElevenLabs keys are absent
  and the channel voice remains unset; full live production is not yet ready.
- Installed `@hypit/hypit@0.1.8` in ignored `vendor/hypit-runtime`; version/help
  run successfully. Prepared ignored `data/production/v-hypihub-pilot` with a
  HypiHub-only profile and one matching five-second 720p portrait coffee shot.
- Hypit source check passes; plan resolves one request with no unsupported
  parameters. Preflight/doctor correctly stop for missing HypiHub credentials.
  Browser authorization started; account catalog, price and generation pending.
- No paid generation, subscription purchase, local Hypit render or publishing.
  Guide: `docs/setup-test-guide.md`; evidence: `data/production/setup-test-evidence.json`.

### Authorization and live quote follow-up (2026-09-15)

- The 10:27 Canvas browser error followed the 10:19 challenge expiry; CLI reported
  `cli.login_expired`. A fresh challenge completed, and account/catalog checks
  passed in CN production. HypiHub OAuth also completed successfully.
- User selected their logged-in Chrome profile. Canvas is open there; the editor
  reports `draft_reader_too_old` after a single refresh. CLI operations work.
- Fixed live-discovered Canvas ID formatting and stderr JSON error handling.
  Added regression coverage before the fix. The rejected pilot draft was repaired
  only after native local validation proved the previous ID could not be sent;
  previous journal retained privately, no generation replayed.
- Pilot shot 0 saved/read back/quoted: `seedance_2.0_fast_vip`, five seconds,
  720p, 9:16, one output, **30 Jimeng credits** maximum. Approval pending.
- HypiHub Seedance fast pilot preflight passes; authenticated rates give an
  estimate of **142.6 HypiHub credits / US$0.713**. Doctor reports unavailable
  Grok/Mimo routes that this pilot does not request. Approval pending.
- Full offline suite **229 passed in 23.81s**. No media generated or paid charges.

### Approved single-shot tests (2026-09-15)

- User approved both quoted pilots. Submitted Jimeng once under the native
  **30-credit ceiling**, then submitted the matching HypiHub build once at the
  refreshed estimate of **142.6 credits / US$0.713**. No automatic regeneration.
- Jimeng completed: `data/production/v-jimeng-cli-pilot/assets/shot-00.jimeng.mp4`,
  H.264, 720×1280, 5.017 seconds of video, audio present. Native checksum,
  full FFmpeg decode and M6 media intake passed. Sampled frames show rising steam
  and camera push-in; the steam looks stylized. Manifest provenance is Jimeng;
  only shot 0 is covered, with shots 1–3 correctly missing.
- Recovered a native wait timeout without partial data and a download transport
  failure using the original submission/resource. Added a regression test for
  status recovery after an empty wait response: **230 tests passed in 24.40s**.
- HypiHub build `bld_20260915T180019904Z_F956C7995D` failed during submission:
  HTTP 402 `insufficient_credits`, zero outputs. Receipt retained; no top-up,
  subscription purchase or repeat build. Quality comparison awaits account funding
  and an explicitly requested fresh test. Settled charges were not verified.
- Evidence: `data/production/setup-test-evidence.json`, Jimeng `pilot_qc.json`,
  and HypiHub `submission.json`/`status.json`/`approval.json`. Full asset-set,
  narration/subtitle assembly and publishing gates remain pending.

### Jimeng subscription → Hypit local editing (2026-09-15)

- Installed the global Hypit Skill for Codex via the requested skills installer;
  read its production instructions. Jimeng generation stays in the existing
  official Canvas workflow; accepted local files become Hypit inputs.
- Added `workflows/jimeng-hypit/`: five-second portrait source, timed titles,
  original audio, local-only runtime and reuse guidance. Added `scripts/hypit.sh`
  for the separately pinned Hypit 0.1.8 installation. Guide:
  `docs/jimeng-hypit-workflow.md`. No custom generation provider is needed.
- Local runtime installed and doctor passed. Real export exposed a 0.1.8
  packaging bug: capture children omitted Hypit's distribution resolver and
  failed to import `@hypit/hyperframes`. Project-owned Node bootstrap supplies
  the native resolvers to worker/child processes without editing vendor code.
  Added an offline child-import regression; **231 tests passed in 25.48s**.
- Reused the failed local build's normalized coffee clip. Repaired build
  `bld_20260915T182740926Z_30543A5A62` completed: three local requests, zero hosted
  calls. Exported `data/production/v-jimeng-hypit-pilot/final.mp4`: H.264,
  1080×1920, 30 fps, five seconds, AAC stereo. Original media is 720p, scaled.
- Full decode and assembly resolution/audio/timeline-duration QC pass. Ten
  sampled frames plus a full-size closing frame show both titles, the label and
  source motion. Studio playback reaches the closing frame in the user's Chrome
  profile at `http://localhost:5184/#comments`. User listening/creative review
  remains pending; this pilot contains titles, not speech-aligned captions.
- No new media generation or credits used for this editing test. Existing MPT
  production remains the default; full shot coverage, real narration/captions,
  human review and publishing are separate gates. Local receipts and checks are
  retained in the pilot folder and consolidated setup evidence.

### ElevenLabs credential setup (2026-09-15)

- Stored the user-provided key in ignored `config/secrets.toml`, permissions
  0600, preserving all other settings. No credentials appear in tracked files.
- Read-only account, voices and model requests returned HTTP 200. Active Starter
  account, 30 voices and configured `eleven_v3` model discovered. Sanitized local
  evidence: `data/production/elevenlabs-setup/verification.json`.
- No synthesis or music generation submitted. Channel voice remains unset;
  voice audition, synthesis permissions and real narration QC/listening remain
  pending. Code is unchanged; the previous 231-test result remains the latest.

### Root .env and Google audio setup (2026-09-15)

- User selected a root `.env` for credentials. Added Git exclusions and a safe
  example. Shared configuration now reads it with nonempty environment > `.env`
  > private TOML precedence; empty placeholders preserve working settings.
  Values remain local to the loader, with no shell execution or interpolation.
- Pinned `python-dotenv==1.2.3` in setup. Offline tests cover precedence, quotes,
  BOM/comments, path isolation, empty placeholders, reloads and malformed-input
  errors without revealing credential contents. **239 passed in 26.22s**.
- Google primary docs confirm Lyria 3.5 through Gemini Interactions. The Cloud
  guide uses a separate project/auth route and different model examples; a key
  named `GEMINI_TTS_VERTEX_API_KEY` does not establish access to either route.
  Details and primary sources: `docs/audio-providers.md`.
- The new `.env` was zero bytes on disk; Google credentials/access are unverified.
  User was asked to save the file and identify the key's origin. Existing
  ElevenLabs configuration remains available. Google generation adapters and
  full narration/music testing remain pending; no audio generation submitted.

### Saved Vertex credentials follow-up (2026-09-15)

- `.env` now contains credentials and Cloud project/region; user confirmed Vertex
  AI. Normalized the ElevenLabs field name without changing credential values.
  ElevenLabs account check passes with the `.env` value.
- Vertex API-key token-counting checks return 200 on express and project routes,
  including `gemini-2.5-flash-tts` and `gemini-2.5-pro-tts` in `us-central1`.
  Synthesis, quota and audio quality have not been tested.
- Model catalog and project Interactions listing return 401 for API-key auth.
  Existing Cloud CLI login requires reauthentication. Browser flow opened in the
  user's Chrome; correct project account is pending confirmation. Music access,
  including Lyria 3.5 on this Vertex project, remains unverified.
- Sanitized evidence: `data/production/google-audio-setup/verification.json`.
  No generation submitted. Configuration/docs-only follow-up; the latest full
  offline suite remains 239 passing tests.

### Vertex OAuth completed (2026-09-15)

- User completed the Chrome authorization flow. Cloud CLI login completed and
  a fresh access token was obtained using native credential storage. No OAuth
  code or token was saved in project files or verification receipts.
- OAuth Model Garden listing and project Interactions listing both return 200.
  The catalog list contains Gemini 2.5 Flash/Pro TTS. Direct catalog lookups for
  `lyria-3-clip-preview` and `lyria-3-pro-preview` also return 200; these preview
  models are absent from the list response. `lyria-3.5` and `lyria-002` catalog
  lookups return 404, without establishing their other inference-route access.
- Authentication and read access are verified. Actual speech/music generation,
  quota, audio quality and automated Google provider integration remain pending.
  Zero generation calls made. Updated sanitized setup receipts and
  `docs/audio-providers.md`; no production code changed. Latest full offline
  suite remains **239 passed in 26.22s**.

### Vertex TTS and music generation pilot (2026-09-15)

- User explicitly approved both audio tests. Submitted exactly one
  `gemini-2.5-flash-tts` request (Kore, `us-central1`) and one
  `lyria-3-clip-preview` request (global Interactions); both returned HTTP 200.
  No retries. Native OAuth credentials stayed out of project artifacts.
- Outputs: 14.531-second 24 kHz mono narration WAV and 28.813-second 44.1 kHz
  stereo music MP3. Full decoding and non-silent audio checks pass. A local
  16.531-second preview mixes narration over quiet music with fades and speech
  ducking; peak -4.5 dBFS. Listening review remains pending.
- Estimated list-price spend $0.043666, recorded in the dollar ledger; actual
  billing is not verified. Evidence and previews are under
  `data/production/v-vertex-audio-pilot-20260915/`; setup receipts updated.
- Production adapters/settings and frozen contracts are unchanged. Narration
  is below the production 15-second minimum; this is a provider smoke test,
  not a G7/G8/G12 sign-off. Latest full offline suite remains 239 passing tests;
  no production code changes in this follow-up.

### Outlier discovery tool research (2026-09-15)

- Reviewed all nine supplied candidates against first-party pages, extension
  listings, source code and API documentation. Recommendation: Viral Outliers
  for an API pilot, Handler for free browser/MCP research, ClipRanker for CSV
  intake. Full comparison, pricing corrections and proposed integration:
  `docs/outlier-tools-review.md`.
- Viral Outliers free trending/pricing endpoints returned HTTP 200. Sample
  exposes views/followers but lacks publication times, contains photo posts and
  repeated creators; authenticated search quality and YouTube coverage remain
  untested. Receipt: `data/production/outlier-tools-research-20260915/public-api-check.json`.
- Documented the mismatch between the user's strict views/followers > 2 rule
  and the current scanner's rounded >= 2 ratio plus >= 5 median-performance
  requirement. Proposed separate eligibility and ranking signals with a
  cross-platform intake artifact; implementation and frozen contracts unchanged.
- Research only: no purchases, installations or paid API requests. Latest full
  offline suite remains 239 passing tests; no production code changed.

### Viral Outliers discovery integration (2026-09-15)

- User selected Viral Outliers and supplied the key through the private root
  `.env`. Configured it as the radar provider for YouTube + TikTok; retained an
  explicit native YouTube route. Both use the user's strict unrounded
  views/followers >2 eligibility rule. Median performance is separate context.
- Added free doctor/preview, saved search plans, per-batch credit ceilings,
  conservative weekly dollar reservations, durable request receipts and safe
  resume. Unknown request outcomes and unexpected charges block resubmission;
  completed responses can be reprocessed without API calls. No enrichment,
  top-up purchases or implicit paid-search approval were added.
- Filtered missing/invalid counts, missing/stale dates, deleted/inactive posts,
  photos and unsupported references; deduplicated posts and kept distinct
  creators for topic confirmation. Original platform URLs and follower ratios
  now reach M2/M3. Frozen contracts/fixtures are unchanged; unavailable medians
  use zero plus explicit metadata, never the vendor's average-based score.
- Wired the shared provider service into weekly orchestration; missing radar
  credit approval stops before paid searches or the LLM stage. Operating guide:
  `docs/radar-viral-outliers.md`.
- Live free checks passed: authentication, 1-credit search price and 0 available
  credits; trending returned 12 posts, all without publication timestamps.
  Free teaser evidence stays outside production. Receipts:
  `data/radar/viral-outliers/doctor.json` and `free-preview.json`.
- Prepared `viral-pilot-20260915`: one `ai tools` query each for YouTube/TikTok,
  up to 100 records per platform; **2 credits / $0.02 nominal**. No paid calls
  submitted. User reports a subscription allowance, but available API credits
  are still zero; billing/credit allocation must be resolved before the pilot.
  Paid response mapping, niche relevance, YouTube coverage and G1 remain pending.
- Validation: **300 passed in 26.22s** in full offline `make test` (baseline 239).
  Includes recovery after receipt persistence, charge checks on restart,
  missing credentials, malformed responses, caps, provenance and weekly wiring.

### Approved Viral Outliers pilot attempt (2026-09-15)

- User explicitly approved running the prepared `viral-pilot-20260915` batch.
  Ran the discovery command with the reviewed **2-credit ceiling**.
- Preflight stopped on insufficient credits before either search was submitted.
  A fresh free account check confirms authentication succeeds, balance **0**,
  and price **1 credit per search**. **0 searches submitted; 0 credits spent.**
- Sanitized receipt: `data/radar/viral-outliers/viral-pilot-20260915/last-attempt.json`.
  The two-search approval remains valid for this unchanged batch; available
  account credits are the blocker. No purchase, top-up, retry or scope change.
- Live result mapping, candidate relevance and downstream live handoff remain
  untested. No code changed; latest full offline suite remains **300 passing**.

### Generated assets uploaded to Google Drive (2026-09-15)

- User requested all generated assets in the supplied Google Drive folder with
  descriptive filenames. Inventoried production media and MoneyPrinterTurbo
  task/storage outputs: 44 original/cached files represent 20 distinct media
  assets by SHA-256. Every distinct file was included; identical copies were
  consolidated and mapped in the uploaded catalog.
- Uploaded 20 descriptively named videos, audio files and preview images,
  plus a readme and CSV catalog: **22 files**, about **14.4 MB** of media.
  Includes Jimeng coffee footage, Hypit final/intermediates, Vertex narration,
  background music and mix, and clearly labeled synthetic assembly-test files.
- Local decoding checks passed for each media asset. Google Drive's upload
  dialog confirmed **22 uploads complete**, with all expected filenames.
  Destination: https://drive.google.com/drive/folders/1XQU20m_xk5030kAxbbIumeHYkrRPkPbs
- Used the existing signed-in Chrome account; original local files and project
  references were preserved. No new generation or changes to sharing settings.
  Local staged files and verification receipt:
  `data/production/drive-export-20260915/upload-manifest.json`.

### Google Drive CLI authorization verified (2026-09-15)

- User completed authorization for the existing `gdrive 3.9.1` connection
  (`n8nworkflow` OAuth application, account `tingsong.dai@gmail.com`).
- The pending folder-info command completed successfully. Authenticated CLI
  listing confirms all 22 expected delivered files, with no missing files or
  duplicate names; no files were re-uploaded.
- Saved remote file IDs in the existing upload manifest and changed the
  sanitized setup receipt to authenticated. Native gdrive manages credentials
  outside the project. Guide: `docs/google-drive-uploads.md`.
- Future requested uploads can use the CLI. No scheduled uploads, sharing
  changes or production code changes were made.

### Shopify product intake and direct Canvas reference test (2026-09-15)

- Verified the user's `.env` Shopify Admin credentials with a validated,
  read-only product query. The selected checkerboard tank has one 1365 × 2048
  image and a description; its complete attached-media list contains no video
  or additional angle. Store content was not changed. Guide:
  `docs/shopify-product-assets.md`.
- Downloaded and visually sampled the supplied Instagram reference: 169.713s,
  1080 × 1920, presenter-led clothing try-on. Prepared a proposed 25–30s
  single-product styling adaptation; audio transcription and outlier-ratio
  verification were not performed.
- User selected direct official Canvas CLI use for the first test. Imported the
  Shopify image, saved and verified its node reference/connection, quoted one
  five-second `seedance_2.0_fast_vip` `m2v` clip, and submitted it once with a
  hard 30-Jimeng-credit ceiling. The ceiling was limited to the live quote;
  final billing was not independently verified.
- Native local-file upload returned uncertain state. A read-only resource
  check found no registration; official image-URL import succeeded with the
  original resource ID. No duplicate image or generation was created.
- Generation/download completed. Checksum, byte count, full decoding and M6
  intake passed at 720 × 1280. Original runtime is about 5.09s with generated
  audio; a 5.017s silent preview preserves the video stream without re-encoding.
- Six sampled frames retain the recognizable tank design during subtle motion.
  User review remains pending. This verifies product-image conditioning through
  the direct CLI, not full outfit changes, presenter continuity, or automatic
  Shopify/M6 reference integration. No publishing or regeneration.
- Evidence: `data/production/v-product-variation-Db9SrsBsIUg/test-report.json`;
  guide: `docs/jimeng-product-reference-test.md`. No production code changes;
  latest full offline suite remains **300 passing**.

### Hypit reference adaptation prepared (2026-09-15)

- Studied the original try-on video's opening and later outfit changes. Prepared
  a 30s, three-look MsDressly adaptation with a new presenter, original dialogue,
  product references, motion conditioning and editable Hypit captions/titles.
- Imported a ten-second source-motion excerpt into official Canvas. Saved one
  presenter-image draft and two 15s Seedance 2.0 Fast VIP drafts with stable IDs.
  Image quote is 8 credits; video quotes require their upstream generated
  references and are not yet available.
- Pending separate approval for at most 350 Jimeng credits + US$0.05 ElevenLabs.
  No generation or transcription submitted for this new variation.
- Completed a **five-second layout preview**, using the earlier product-motion
  clip. Hypit build `bld_20260916T015830127Z_3EA1463EFD` completed with explicit
  normalized-media reuse; no new paid-provider requests. Export is 1080 × 1920,
  30fps, 5.0s, upscaled from 720p source. Full decoding passed; four sampled
  frames show readable typography; output audio is silent.
- Opened local Comments/Studio at http://localhost:5185/#comments. The preview
  tests the typing title and caption treatment; speaking footage, outfit
  changes, exact speech timing and full final review remain pending.
- Guide: `docs/hypit-reference-variation.md`. Evidence and editable production:
  `data/production/v-product-variation-Db9SrsBsIUg/hypit-variation-01/`.
  No production code changes; latest offline suite remains 300 passing.

### Full-length MsDressly haul prepared (2026-09-15)

- User replaced the 30-second single-product scope with the source's full
  duration, a new voice with similar delivery, ElevenLabs v3 and several
  MsDressly products including the tank. The earlier 350-credit proposal was
  not accepted and is now marked superseded in the old production state.
- Verified exact picture length: **169.700s / 5,091 frames at 30fps**; audio
  container is 169.712993s. Local OCR of 339 sampled frames and scene-cut
  candidates support a provisional thirteen-section visual map, not an audio
  transcript or verified music analysis.
- Selected eleven actual catalog products, saved their references and drafted
  522 original words. Selected Jessica on `eleven_v3` from the live voice
  catalog; read-only account/model checks succeeded. Audition remains pending.
- Created `hypit-full-length-01/` with script, Brief, analysis, treatment,
  timeline, voice settings, product evidence and an eighteen-clip / ten-outfit
  plan. A full-duration product storyboard passes Hypit check and local
  render-plan preflight (three local requests, zero paid-provider requests).
  Opened http://localhost:5186/#comments in Chrome; opening and final frames
  inspected, final caption readable and within the canvas.
- Requested a new commission ceiling of **2,000 Jimeng credits + 4,000
  ElevenLabs TTS credits + US$1 combined audio analysis/music spending** on
  existing accounts. These are planning limits, not a resolved full-film
  quote. Dependent live quotes require actual generated references; each must
  fit the remaining accepted cap before submission. No new paid calls made.
- Full narration, new outfit images/footage, lip-sync validation, soundtrack
  matching and final export remain pending. Guide updated in
  `docs/hypit-reference-variation.md`. No production code changes; latest full
  offline suite remains the prior 300 passing run, not rerun for artifacts.

### Approved full-length narration and first speaking test (2026-09-15)

- User explicitly approved 2,000 Jimeng credits, 4,000 ElevenLabs TTS credits
  and US$1 combined reference-analysis/music spending on existing accounts.
  Approval is persisted in `hypit-full-length-01/budget-approval.json`.
- Source Scribe transcription returned 699 words. Thirteen Jessica / ElevenLabs
  v3 takes generated successfully (3,823 submitted characters). Removed v3's
  unsupported context fields after one validation rejection. Edited optional
  sentences and pauses locally, preserving all raw takes; final copy is 566
  words over exact 169.700s. Final automated audio review reports natural,
  intelligible delivery. Most tempo adjustments are 1.00–1.16, intro 1.28.
- Rendered the full narrated product storyboard in Hypit: build
  `bld_20260916T025522799Z_0692BF6AA1`, 1080 × 1920 / 30fps target. Export:
  `MsDressly_Full_Haul_Narrated_Storyboard_2m49s.mp4`. It remains visibly labeled
  as a voice preview with try-on footage pending, not the final commissioned film.
- Official Canvas generated one consistent presenter/tank/jeans image (eight
  credit quote) and one ten-second speaking clip (114-credit quote). The clip
  failed visual QC: original performer retained in its opening, misspelled
  title/garbled captions, unrelated source brand text. Remaining jobs paused.
- Prepared a clean replacement using the new presenter, product and ElevenLabs
  audio without source-video conditioning. Live quote **60 credits**, within
  the existing cap. Requested replacement approval under the accepted rule
  against automatic regeneration; no replacement submitted yet.
- Nine remaining outfit images are prepared and quote at eight credits each,
  72 total, not submitted. Current Jimeng reservation is 122 credits; TTS
  conservative reservation is 3,979 including the rejected request; audio API
  reservations are US$0.53. Settled billing has not been independently verified.
- Lyria 3 Pro music request returned `content_blocked` with an unspecified
  policy reason; no music output and no automatic retry. Narration/visual
  preparation continued independently. No publishing or production-code changes.

### Automated continuation approved — 2026-09-15

The user approved the 60-credit corrected opening and then automated video generation within the existing commission ceilings. The replacement completed under the same saved submission ID and passed sampled visual inspection plus automated audiovisual review; no copied presenter or text was seen. Its review remains automated rather than a human listening signoff. Nine remaining outfit images are generating sequentially at their recorded eight-credit quotes. A fresh concise instrumental brief on Lyria 3 Clip returned 27.742 seconds of original stereo music; the earlier Pro rejection remains recorded. Final music fitting, remaining footage and the completed film are still in progress.

All ten outfit references have now passed visual inspection; the red-pullover reference required one eight-credit correction from an incorrect open cardigan. Native quotes for the remaining 17 speaking clips total 1,008 credits; with 262 already reserved, the planned total is 1,270 of the approved 2,000. Sequential generation has started. Opening review v2 is locally rendered and inspected, with larger typography; build `bld_20260916T032440396Z_8D72922EED`, 275 frames at 30fps. Original music is fitted beneath the preserved ElevenLabs narration. Full film is still in progress.

### Full-length MsDressly haul completed for review (2026-09-15)

- Delivered `data/production/v-product-variation-Db9SrsBsIUg/hypit-full-length-01/MsDressly_Full_Haul_2m49s.mp4`: **169.700 seconds, 5,091 frames at 30fps, 1080 × 1920**, H.264 / stereo AAC, 47,466,376 bytes.
- Eighteen edited clips cover eleven real catalog products. Official Canvas used Seedance 2.0 Fast VIP at 720p and Seedream 5.0 Pro for outfit references. Rejected opening, red cardigan image and duplicated/wrong-sleeve denim take remain excluded and preserved.
- Final soundtrack is the original 566-word Jessica / ElevenLabs v3 recording plus newly generated Lyria instrumental, fitted to the full duration. Raw generated-video audio is excluded.
- Separate word-time analysis found drift missed by broad model checks. Fitted sixteen picture clips locally; used product close-ups for missing native words and wardrobe drift. Full voice track and duration are unchanged.
- Hypit renders exact frame intervals with only relevant media/typography layers. A 115-frame comparison against the unpruned composition yielded SSIM 1.0. FFmpeg joins the verified picture sections without another picture encode and adds continuous audio.
- Full-file checks pass: exact frame count, runtime, dimensions, complete decode, no black intervals, peak −1.6 dBFS. Sampled final frames and captions inspected. A first whole-film model response was truncated; a separate concise review completed and reported no significant issues. Human review remains pending.
- Final reservations: **1,348 / 2,000 Jimeng credits**, **3,979 / 4,000 TTS credits** (3,823 successfully submitted characters), **US$1.00 / US$1.00** other audio/review APIs. These are conservative reservations, not verified settled billing; no further dollar-spend calls remain covered.
- Finished film opened in the user's Chrome profile at http://localhost:5188/#comments; editable full timeline remains at port 5187. `DELIVERY.md`, `production-report.json`, `final-qc/`, source selections, section build receipts and native job IDs preserve handoff and recovery evidence.
- No publishing or core production-module changes. Latest offline suite remains the prior 300 passing run; not rerun for media and documentation. This verifies the local Hypit commission, not MoneyPrinterTurbo or the entire G6/G8/G12 publication loop.

### Caption escaping repaired (2026-09-15)

- Owner screenshot exposed literal `&#x27;` in contractions. The author used HTML numeric escaping, but Hypit 0.1.8 only decodes named XML entities. Added a shared named-entity serializer and wired the production author to it.
- A real-parser regression failed before the fix and now passes; full `make test`: **301 passed**. All 568 production caption strings round-trip exactly.
- Re-exported eleven affected sections and replaced the final MP4. Local OCR found zero entity strings across 80 affected caption states; visually checked all 19 OCR discrepancies. The earlier broad model review had missed this bug.
- Corrected final remains 169.700s / 5,091 frames at 30fps, 1080×1920. Encoded audio packets match the original. Full technical QC passes. New final: **47,366,136 bytes**, SHA-256 `314b53f2c3d9e279584ec8ebd291afc9666b2e5501530cbe7c097bb56c41aaa0`.
- Review Run refreshed at port 5188; original delivery and section receipts retained in `caption-fix-archive/`. See production `CAPTION-FIX.md`. No paid calls, regeneration or publishing.

### Corrected video delivered to Drive; services stopped (2026-09-15)

- Uploaded `MsDressly_Full-Haul_Corrected-Captions_1080x1920_2m49s.mp4` to the previously authorized Drive folder. File ID `1zUxjyRIILGZ4UedvxS_u_e7rNcNZgAGZ`; remote size **47,366,136 bytes** and MD5 `d3f65067ded01419cdbe3a4e0b6f31dc` match the corrected local export.
- Stopped five project Hypit Studio servers, four runtime workers and their child process: **10 processes**, graceful termination. Verified ports **5184–5188** are free. No project rendering or generation remains active.
- Production receipts: `drive-delivery/upload-receipt.json`, `service-shutdown.json`. Preview URLs are offline; do not restart without a new request.

### Standing video delivery and cleanup rule (2026-09-15)

The user requires Drive delivery and service shutdown after every finished video.
Recorded the required sequence and standing authorization in
`docs/google-drive-uploads.md`, with entry points in `AGENTS.md`, `GOAL.md` and
the Jimeng/Hypit workflow. Final revisions follow the same rule. Completion
requires verified remote size/MD5, saved receipts, stopped video services and
verified free ports. Upload failures retain the final locally and still clean
up idle video services. This is the agent's production completion procedure;
no background scheduler or new generation was started. The current video already
meets it. Documentation-only change; the last code test run remains 301 passing.

### Next 15 video products selected (2026-09-15)

- Selected fifteen unique, currently available MsDressly products, one featured product per next video, excluding the completed haul's products and gift cards.
- Ranked live Shopify analytics by 90-day net units sold, using 30-day and 365-day sales as tie-breakers. Validated the read-only GraphQL queries, checked current catalog identities, storefront purchase availability, prices and product images. Counts are store-relative and modest; this is not evidence of viral performance.
- Plan, product URLs, suggested video angles, CSV/JSON, reference-image board and sales evidence: `data/production/next-15-video-plan-20260915/`. Start with `NEXT-15-VIDEOS.md`.
- Verified 15 unique product IDs, zero prior-haul overlaps, positive recent net sales and available variants for every selection. No product changes, media generation, paid generation calls or preview servers.

### Next 15 videos revised to multi-product hauls (2026-09-15)

- User clarified that every video must contain many products like the completed haul. Superseded the single-product proposal with **15 themed hauls, 10 products each, 150 unique Shopify product IDs**, excluding all eleven previous-haul products. The old proposal is retained under `superseded-single-product-plan/`.
- Expanded current catalog checks to 843 products with positive annual sales history; 776 passed catalog eligibility, including 106 with positive 90-day net units. Curated the final batch for sales evidence, thematic coherence and visual variety: **97 recent sellers and 53 historical-only sellers**. Counts are modest and do not establish viral demand.
- All 150 selected products have live storefront availability, available variants and reference images. Visually reviewed fifteen ten-product boards, replaced several near-duplicate looks, and recorded title/image discrepancies for variant preparation. Exact color/size choices and scripts remain production preparation.
- Replaced `data/production/next-15-video-plan-20260915/NEXT-15-VIDEOS.md` and its JSON/CSV with the complete haul assignments, linked products, prices, 90/365-day unit counts and reference notes. `PRODUCT-BOARDS.md` links all fifteen boards; `selection-validation.json` records 150 unique IDs/URLs, zero previous-haul overlaps and 150 available products.
- The previous 169.7-second presenter-led haul is the working format template. No new generation, paid generation calls or preview/render services were started. No application-code changes; the prior 301-passing test run remains the latest code validation.

### Sequential haul batch planned against live balances (2026-09-15)

- Saved `docs/msdressly-15-video-production-plan.md` and a fifteen-item queue under the product plan's `batch-plan/`. One video and one Jimeng job at a time; each video must pass QC, verified Drive upload and verified process/port cleanup before the next starts. The queue is a planning artifact, not a running worker.
- Logged-in Chrome credit details show **13,502 Jimeng subscription credits**. The diagnostic CLI returned zeros with an empty account identity and was rejected as balance evidence. Canvas 1.0.1 account/model checks succeed; fresh example quotes remain eight credits per 2K outfit image and sixty per ten-second Fast VIP 720p clip.
- Equivalent-haul estimate: 1,148 base credits plus a 200-credit correction allowance. Current balance likely covers **10–11 full 169.7-second hauls**; remaining items stay queued when another complete video cannot be funded. No top-ups or silent quality/length reductions are planned.
- ElevenLabs reports **84,504 included credits remaining**. Proposed new narration allowance is 4,000 per video / 60,000 total; reuse accepted original music locally for zero additional music/analysis API spend. Prior commission ceilings are not reused as batch authorization.
- Confirmed Drive folder access, 64 GiB machine RAM, approximately 188 GiB disk available and no listeners on ports 5184–5188. Cleanup will terminate only owned video processes and verify normal memory pressure; it does not promise an exact global free-RAM number.
- Plan specifies the reusable controller work, durable recovery, budget enforcement and offline acceptance checks still needed before batch execution. No generation submitted and no application code changed; prior test baseline remains 301 passing.

### Sequential batch controller implemented; live rollout (2026-09-16)

- User accepted the saved plan with “implement.” Added `modules/batch/`: one active video/job, exclusive process lock, atomic private state, complete-video credit reservations, immutable selection checks, native Canvas quote/confirm/run with saved IDs, read-only recovery, ElevenLabs v3 audio/alignment fitting, Hypit section rendering and continuous final audio assembly.
- Accepted limits: 13,502 Jimeng credits; 4,000 narration credits per video / 60,000 total; no other paid model/audio APIs. Retakes require a recorded defect, a fresh quote and the 200-credit correction allowance. No top-ups or automatic budget expansion.
- Added verified Drive upload/recovery and owned-process cleanup in every exit path. A video cannot finish until QC, remote name/parent/size/MD5 and cleanup all pass. New tests cover budget/lock/recovery/delivery/process identity, caption escaping, reference replacement and exact time mapping through pause removal.
- Zero-generation dry run verified the already-delivered final without uploading it again. A real local Hypit render, build `bld_20260916T065718508Z_12CB065DEB`, visibly renders “I'd try” and “Checks & denim” correctly; its runtime was shut down and cleanup verified. The check used existing footage, not new paid generation.
- Installed Faster Whisper 1.2.1 in isolated `vendor/speech-qc/.venv` (Python 3.12) and validated the public `base.en` model on existing speech. New `scripts/batch_speech_check.py` provides local ASR evidence without API charges; it does not auto-certify lip synchronization.
- Video 01 has original 554-word / 3,170-character copy for all ten selected products, exactly 5,091 frames. Created Canvas `9d5c02d1-6c94-4feb-a40d-1f88c6094b9d`. Thirty drafts quote **1,160 credits** plus **200 repair reserve**. Narration is being generated and fitted; final delivery is not yet complete.
- Native Canvas rejects quoting clips whose reference image has no output. The controller quotes equivalent settings with existing presenter/audio references, then swaps in the accepted outfit and exact new speech before generation, checks saved settings and enforces the original ceiling against a fresh quote. No provisional-reference clips are generated.
- One local presenter upload returned unknown and remains recorded unresolved. Reused the already accepted Canvas presenter resource instead; product images use official server-side Shopify URL imports. A separate local audio upload succeeded, confirming the narration-reference route. No ambiguous paid submission has been repeated.
- Usage and recovery: `docs/msdressly-batch-runner.md`. Frozen contracts unchanged. Prior unrelated files/deletion preserved. Live QC, delivery and batch completion remain pending; no social publishing.
- Validation after implementation: **321 tests passed** in the full offline suite. All 20 narration takes are now complete within **3,170 reserved TTS credits**; local full-length ASR similarity is 97.28%. Accepted speech is fitted proportionally across the fixed 5,091-frame timeline, with caption times transformed through the same pause removal and tempo edits. Refreshed native visual quotes total **1,166 credits + 200 correction reserve**. The first eight-credit outfit reference is accepted and generating; no completed new final yet.
- First outfit reference downloaded and visually passed against the Shopify skort and accepted fictional presenter. First nine-second speaking clip submitted for 54 credits with the exact fitted narration and approved outfit; current conservative visual holds **62 credits**. Created the current-task heartbeat **Produce sequential MsDressly hauls** (`produce-sequential-msdressly-hauls`) to continue every ten minutes through agent review checkpoints, verified delivery and cleanup. It stops/pauses at completion, credit insufficiency or an actionable unresolved failure; it does not expand spending limits or publish socially.
- First clip downloaded successfully under its original submission ID. Eighteen sampled frames show consistent presenter, garment and room without source text; independent native-audio ASR is 94.55% similar and omits “skort.” Its speech-timing review remains pending; no blind QC pass or regeneration. Notes are in `productions/haul-01/review/clip-01-inspection-notes.json`. Current video services/owned ports are cleaned; the heartbeat continues from this checkpoint.
- Continuation resolved the first clip's transcription discrepancy with local `small.en`: both the exact narration and generated track transcribe to the same complete utterance. Measured native speech drift reached 0.29 seconds. Added bounded local picture timing, preserving the original audio/source; the selected edit has 265 frames and maximum ASR-anchor residual 0.074 seconds. All 18 sampled edited frames inspected and the clip gate passed with the ASR limitation recorded. Clip 02 is now generating within its original 54-credit ceiling. No regeneration or paid analysis was used for the timing correction.
- Local picture correction and stale-render-input safeguards validated in a full offline run: **324 tests passed**. Conservative active-video Jimeng holds are **116 credits** after clip 02 acceptance; the complete-video reservation remains 1,366. See `modules/batch/MODULE_REPORT.md` for implementation and remaining live gates.
- Clip 02 is downloaded and reviewed. Both local ASR models hear “chalks” where the accepted narration says “checks”; identical speech was not asserted. A local edit preserves the correct ElevenLabs track, retimes picture using ten shared-word anchors, and shows the actual garment in a face-free detail cutaway during the disputed phrase. Inspected the edited clip and fourteen detail frames; 249 frames decode correctly. No regeneration or paid analysis was used.
- Outfit reference 02 (sky-blue polka-dot jeans) downloaded and passed comparison with its Shopify photograph and accepted fictional presenter. The runner has continued to clip 03 under its existing quote. Per-clip evidence and selected-edit hashes remain in the production folder; full-film QC, Drive delivery and batch completion remain pending. No application-code changes; the 324-passing offline run remains current.
- Clips 03 and 04 are downloaded and reviewed. Independent local transcription matches their accepted utterances; bounded local picture retiming preserves their original narration and exact 249/223-frame allocations. Maximum retained-anchor residuals are 0.050/0.034 seconds, with the ASR limitations recorded. Inspected both native and edited frames for garment, presenter, hands, framing and text. The first two products now have approved footage; no paid replacements have been used. Outfit reference 03 is generating under its eight-credit quote; conservative visual holds are 234 credits, within the existing 1,366-credit video reservation.
