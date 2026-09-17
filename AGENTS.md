# AGENTS.md — Swarm Ownership Map & Rules

> **SCOPE BANNER (factory work, 2026-09-16):** The swarm ownership table,
> per-agent write partitions, Wave 1 fixture-only restriction and `feat/m<N>`
> branch arrangement below are **historical and superseded** for Viral Video
> Factory work. The factory assignment uses **one sequential builder** on
> `feat/factory` per `docs/viral-video-factory-handover.md` §2.3. Still in
> force: frozen `schemas/` + `tests/fixtures/` contracts, offline-only tests,
> credential protection, and the finished-video upload/cleanup rule. F-module
> acceptance (tracker) and legacy G-gates (`docs/gates.md`) are independent
> records; neither signs the other.

Wave 0 is complete. Contracts in `schemas/` + fixtures in `tests/fixtures/` are **FROZEN**.
Read `GOAL.md` (mission) and `BUILD_PLAN.md` (spec) before touching code.

## Current video completion rule

After every finished video or revised final export, follow
[`docs/google-drive-uploads.md`](docs/google-drive-uploads.md#required-completion-workflow):
upload and verify the final in the authorized Drive folder, stop the video's
preview/render services, verify its ports are free, and return the Drive link.
The user's standing authorization covers these completion steps; apply this rule
also when using the single-builder workflow instead of the legacy swarm below.

## Ownership map (Wave 1 — parallel)

| Agent | Modules | You own (write access) | Fixtures you consume |
|---|---|---|---|
| **R** | M1 Niche Radar | `modules/radar/`, `tests/test_radar*.py`, `docs/radar*.md` | `tests/fixtures/yt/*`, `contracts/niche_report.sample.json` |
| **G** | M2 Idea Grill | `modules/grill/`, `tests/test_grill*.py`, `docs/grill*.md` | `fixtures/grill/ideas.json`, `contracts/scored_ideas.*` |
| **F** | M3 Format Library + M4 Hook Bank | `modules/formats/`, `modules/hooks/`, `tests/test_format*.py`, `tests/test_hook*.py` | `contracts/format_library.sample.json`, `contracts/hooks_bank.sample.json` |
| **S** | M5 Script Engine | `modules/script/`, `tests/test_script*.py`, `docs/script*.md` | `contracts/scored_ideas.sample.json`, `contracts/shot_list.sample.json` |
| **V** | M6 Asset Pipeline | `modules/assets/`, `tests/test_asset*.py`, `docs/jimeng*.md` | `contracts/shot_list.sample.json`, `contracts/asset_manifest.sample.json`, `fixtures/media/*` |
| **T** | M7 Voice | `modules/voice/`, `tests/test_voice*.py`, `docs/voice-selection.md` | `fixtures/media/good_voice.mp3`, `short_voice.mp3` |
| **A** | M8 Assembly/QC | `modules/assemble/`, `tests/test_assemble*.py` | `contracts/mpt_task.sample.json`, `fixtures/media/*` |
| **P** | M9 Publishing + M10 Readback | `modules/publish/`, `modules/analytics/`, `tests/test_publish*.py`, `tests/test_analytics*.py` | `contracts/publish_record.sample.json`, `contracts/readback.sample.json` |

**Coordinator** (the human + lead agent): owns `schemas/`, `tests/fixtures/`, `docs/gates.md`,
`PROGRESS.md`, `Makefile`, merges, and Wave 2 integration. M11/M12 are coordinator-built in Wave 3.

## Hard rules

1. **Write only inside your owned paths.** Editing another agent's files or shared files gets reverted.
2. **Depend on schemas + fixtures, never on another agent's code.** Cross-module I/O is simulated with fixtures until Wave 2.
3. **No network, no paid APIs in unit tests.** Mock LLM/TTS/YouTube/Jimeng/Pexels. `make test` must pass offline.
4. **Branches:** `feat/m<N>-<slug>` per module. Coordinator merges to `main` only when a full `make test` run on main stays green.
5. **Contract changes are coordinator decisions**: propose in your MODULE_REPORT.md; coordinator bumps schema version and regenerates fixtures.
6. **Secrets** only in `config/secrets.toml` (gitignored). Never print, commit, or hardcode.
7. **Jimeng Lane A (browser automation)** is best-effort and never blocks your module — Lane B (manual) is the supported path.

## Definition of done per module

1. Implementation complete per `BUILD_PLAN.md` §3 for your module(s)
2. Your unit tests written and green in a full `make test` run
3. Self-check against your gate's unit-testable criteria (G1–G10 in BUILD_PLAN.md)
4. `MODULE_REPORT.md` in your module directory containing:
   - What was built (files, entry points, CLI if any)
   - Test evidence (pytest output summary)
   - Gate self-check results (pass/fail per criterion)
   - Contract deviations requested (if any)
   - Open risks / what Wave 2 integration must verify
