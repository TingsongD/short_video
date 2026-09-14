# Validation Gates — Sign-off Log

Each gate per BUILD_PLAN.md §3. Status: ✅ signed / ⬜ pending / ❌ failed.
Live gates (G1, G5–G10) additionally require human key/spend approval (Wave 3).

| Gate | Module | Status | Evidence | Signed by | Date |
|---|---|---|---|---|---|
| **G0** | M0 Foundations | ✅ **SIGNED** | `make test` green (folders, config, secrets shape, schema round-trips); `uv run python cli.py --help` runs in vendor/MoneyPrinterTurbo; no key-shaped strings in tracked files; vendor pins in docs/vendor-pins.md | coordinator (Wave 0) | 2026-09-14 |
| G1 | M1 Niche Radar | ⬜ pending | unit criteria met 2026-09-14: schema-valid report from fixture scan, quota counter caps search calls + degrades to channel-only, breakout flag at 5x/2x/14d. Live scan still needed | — | — |
| G2 | M2 Idea Grill | ⬜ pending | unit criteria met 2026-09-14: 4 hard-reject rules fire correctly, thresholds at exact boundaries, temp-0 determinism, schema-valid output, raw judge output logged. Live audit (≥30% kill, ≥8/10 agreement) pending real LLM | — | — |
| G3 | M3 Format Library | ⬜ pending | unit criteria met 2026-09-14: CRUD + stable IDs, extract validates + no-copy guard (>0.6 Jaccard rejected), match = exactly 1 default + labeled alt, promote/retire at exact thresholds. Live seeding (≥10 entries) pending LLM | — | — |
| G4 | M4 Hook Bank | ⬜ pending | unit criteria met 2026-09-14: bank.json schema-valid, selector matches niche+type w/ niche fallback, attribution preserved, LookupError on empty niche. ≥5 hooks/niche needs weekly curation (docs/hook-curation.md) | — | — |
| G5 | M5 Script Engine | ⬜ pending | unit criteria met 2026-09-14: 60-110w bound enforced, hook verbatim first sentence, 4-7 shots w/ durations tracking voice est, idx0 forced video, per-shot Pexels fallback, schema-valid shot_list. Human approval of 5 scripts pending LLM | — | — |
| G6 | M6 Asset Pipeline | ⬜ pending | Lane B complete asset set passes ffprobe; Lane A smoke test (non-blocking) | — | — |
| G7 | M7 Voice | ⬜ pending | real generation, blind-listen win vs Edge TTS, duration in bounds | — | — |
| G8 | M8 Assembly | ⬜ pending | full assembly QC green; operator watch: subs synced, hook first | — | — |
| G9 | M9 Publishing | ⬜ pending | real video on test channel, publish_record complete, playable | — | — |
| G10 | M10 Readback | ⬜ pending | readbacks at all windows, ≥ 1 format status decision | — | — |
| G11 | M11 Orchestration | ⬜ pending | weekly cron fires, cost ledger caps, approval gate blocks unapproved spend | — | — |
| G12 | M12 E2E | ⬜ pending | real published video, ≤ 30 min human time, cost in cap, 48h readback | — | — |

## G0 evidence detail (2026-09-14)

- Folder tree per plan: `data/{radar,grill,formats,hooks,production,published,analytics,costs}`, `modules/`, `schemas/`, `tests/fixtures/`, `vendor/`, `config/`, `logs/`, `docs/`
- Vendored: ai-marketing-skills @ `bc84dbc`, MoneyPrinterTurbo v1.3.7 @ `cf5a3ae` (uv sync --frozen, Python 3.11)
- Contracts frozen: 9 schemas × 9 valid fixtures + 1 negative fixture, all round-trip via jsonschema
- Media fixtures generated with ffmpeg (312 KB total): good/bad/zero-byte video, image, 20s/8s voice
- CLI smoke test: `cli.py --help` OK (sources: pexels/pixabay/coverr/volcengine_seedance/ofox/metaso_minimax/openai_image/local confirmed)
