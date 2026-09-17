> **SCOPE BANNER (factory work, 2026-09-16):** This file's M1→M12 restart
> sequence is the completed historical build. Current work is the Viral Video
> Factory per `docs/viral-video-factory-handover.md` — do not restart M1.
> Still in force: frozen contracts, offline tests, secrets discipline,
> paid-call approval, and the video completion rule.

/goal — REGULAR BUILD (single builder, sequential)

Build the short-form AI video system in this repo, one module at a time:

  /Users/tingsongdai/Kimi-cursor/Short Form AI YouTube

STEP 0 — ORIENT (before writing any code)
Read in this order: BUILD_PLAN.md (the spec — your source of truth),
docs/gates.md (G0 already signed), PROGRESS.md, schemas/ and
tests/fixtures/ (frozen contracts). AGENTS.md's legacy swarm topology is NOT
in use; work as a single builder sequentially and follow its current video
completion rule. Then run `make test` — it MUST be green (25 tests). If red,
stop and report; never build on a red base.

STEP 1 — BUILD in this exact order, one module at a time:
  M1 Niche Radar → M2 Idea Grill → M3 Format Library → M4 Hook Bank →
  M5 Script Engine → M6 Asset Pipeline → M7 Voice → M8 Assembly/QC →
  M9 Publishing → M10 Analytics Readback → M11 Orchestration → M12 E2E

For EVERY module, in this order:
  1. Implement its build tasks per BUILD_PLAN.md §3
  2. Write its pytest unit tests — ALL externals mocked (LLM, TTS, YouTube,
     Jimeng, Pexels); `make test` must stay green and run fully offline
  3. Validate against its gate's unit-testable criteria (G1–G12)
  4. Record results in docs/gates.md and PROGRESS.md
  5. Commit with a clear message (e.g. "feat: m1 niche radar — tests green")
Do NOT start the next module until the current one's tests pass.

Contract discipline: schemas/ + tests/fixtures/ are frozen interfaces.
Code against them. If a contract genuinely needs changing, stop and ask
the user first — never edit contracts unilaterally.

STEP 2 — INTEGRATION (after M10): write tests/test_e2e_dry.py driving
M1→M8 entirely on fixtures — every contract file must appear schema-valid,
in pipeline order. Green before continuing.

STEP 3 — LIVE GATES (only with explicit user approval, one at a time):
- When you reach the first live gate, ask ONCE for the full key list:
  YOUTUBE_API_KEY, PEXELS_API_KEY, ELEVENLABS_API_KEY, LLM key,
  YT Analytics OAuth — batched, never piecemeal.
- Run live gates G1, G5–G10 in plan order; the user approves each spend.
- M11 orchestration: weekly cron + cost ledger + hard caps.
- M12 real E2E: exactly ONE video through the full loop, then stop for
  user review before any batch production.

HARD RULES (override everything else):
- Secrets only in config/secrets.toml (gitignored); never print or commit.
- No paid/external API call without explicit in-session approval, except the
  standing Drive-delivery authorization in `docs/google-drive-uploads.md`.
- Jimeng: build Lane B (manual drop folder) first; Lane A (WebBridge
  automation) is best-effort and never blocks progress.
- Zero-spend work (M1–M5 implementation + tests) runs autonomously without
  pausing; pause only for keys, spend approvals, or contract changes.
- Keep PROGRESS.md current; commit after every module.

DEFINITION OF DONE: docs/gates.md signed G0–G12, `make test` green on
main in a single run, BUILD_PLAN.md §8 criteria met.

FIRST ACTION: reply with an orientation summary (repo state, test result,
M1 implementation plan) in ≤ 15 lines, then start M1.
