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
- [ ] M11 Orchestration
- [ ] M12 E2E

## Wave 2 — Integration ✅ DRY RUN GREEN (2026-09-14)

- [x] `tests/test_e2e_dry.py`: M1→M8 driven on fixtures only — niche_report → scored_ideas → format_library → hooks → shot_list → asset_manifest → voice.mp3 → mpt_task + batch — every contract validated against its frozen schema and asserted written in pipeline order; zero network/spend (155 tests green)
## Wave 3 — Live gates + autonomy ⬜ NOT STARTED
