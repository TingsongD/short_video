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
