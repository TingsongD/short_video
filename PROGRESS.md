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
