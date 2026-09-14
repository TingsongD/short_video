/goal

Build the short-form AI video system specified in
/Users/tingsongdai/Kimi-cursor/Short Form AI YouTube/BUILD_PLAN.md
using a parallel agent swarm: all modules M1–M10 built, unit-tested, and
self-validated CONCURRENTLY, then integrated and gate-validated in waves.
Parallelize the build — never the quality bar. Every requirement, data
contract, test, and gate in BUILD_PLAN.md still applies unchanged.

CONTEXT
- Workspace (ALL work inside it): /Users/tingsongdai/Kimi-cursor/Short Form AI YouTube
- BUILD_PLAN.md is the single source of truth. Read fully first. Deviations
  require updating the plan in the same commit + flagging in the report.
- Locked stack (do not re-litigate): radar = vendored yt-competitive-analysis
  (github.com/ericosiu/ai-marketing-skills) + YouTube Data API v3; grill =
  vendored shortform-idea-grill (batch mode); formats = vendored
  shortform-format-library (structure only, never copy wording); hooks =
  curated viralhooks.org bank; visuals = Jimeng (manual Lane B supported,
  WebBridge Lane A best-effort) + Pexels fallback; voice = ElevenLabs;
  assembly = MoneyPrinterTurbo CLI, video_source="local", 9:16 1080x1920;
  publish = YouTube Shorts first; learning = 48h/7d/28d YT readback.

SWARM TOPOLOGY — 4 WAVES

WAVE 0 — FOUNDATION & CONTRACTS (coordinator only, blocks everything): ✅ DONE
  Completed in this repo: M0 (folder tree, vendored skills at pinned commits,
  MoneyPrinterTurbo installed via uv, config templates, .gitignore), all JSON
  schemas in schemas/, all fixtures in tests/fixtures/, AGENTS.md ownership
  map, G0 signed in docs/gates.md. Contracts are FROZEN — do not regenerate.

WAVE 1 — PARALLEL MODULE BUILD (one agent per workstream, ALL concurrent):
  Agent R → M1 Niche Radar        Agent T → M7 Voice
  Agent G → M2 Idea Grill         Agent A → M8 Assembly/QC
  Agent F → M3 Format Library     Agent P → M9 Publishing + M10 Readback
          + M4 Hook Bank
  Agent S → M5 Script Engine
  Agent V → M6 Asset Pipeline (Lane B first; Lane A best-effort, non-blocking)
  Each agent MUST: implement the module per plan → write its pytest unit
  tests (all externals mocked — LLM, TTS, YT API, Jimeng, Pexels) → run green
  → self-validate against its gate's unit-testable criteria → write
  MODULE_REPORT.md (what was built, test evidence, gate self-check, risks).
  HARD RULE: depend only on frozen schemas + fixtures. Never import or call
  another agent's unfinished module. Simulate cross-module I/O with fixtures.

WAVE 2 — INTEGRATION (coordinator leads, module agents on call):
  1. Wire modules on the real data flow; run dry E2E (M12 test_e2e_dry) on
     fixtures — every contract file appears schema-valid, in order.
  2. Integration breaks are fixed by the owning agent; schema changes need
     coordinator approval + version bump + all affected fixtures regenerated.
  3. Send ONE batched request for all missing keys (YOUTUBE_API_KEY,
     ELEVENLABS_API_KEY, LLM key, PEXELS_API_KEY, YT Analytics OAuth) —
     never piecemeal.

WAVE 3 — LIVE GATES + AUTONOMY (sequential, human-gated):
  1. Live gates G1, G5–G10 in plan order; spend approvals preserved
     (idea approval, spend approval — never auto-approve).
  2. M11 orchestration: weekly cron + cost ledger + hard caps.
  3. M12 real E2E: one video, full loop, sign G12.

PARALLEL SAFETY RULES
- Ownership: each agent writes ONLY modules/<own>/, tests/test_<own>*.py,
  own docs. Shared files (gates.md, PROGRESS.md, schemas/, fixtures/) are
  coordinator-only. Violations get reverted.
- Commits: per-agent branches feat/m<N>-*, merged to main by coordinator
  only after that module's tests pass in a full `make test` run on main.
- Contracts frozen after Wave 0 — a needed change is a coordinator decision,
  never an agent's unilateral edit.
- Secrets only in config/secrets.toml (gitignored); never print or commit.
- No paid/external API calls anywhere before Wave 3, and then only with
  explicit approval. Unit tests must pass with zero network access.
- Jimeng Lane A never blocks a gate or the swarm — Lane B is the fallback.

DEFINITION OF DONE
Plan §8 unchanged, plus swarm evidence: one MODULE_REPORT.md per agent,
all branches merged, `make test` green on main in a single run, gates.md
signed G0–G12.

FIRST ACTION FOR THE SWARM
Wave 0 is complete — verify by running `make test` (must be green), read
AGENTS.md for ownership, then launch all Wave 1 agents in parallel.
