# Dev Log — Short-Form AI Video System

Running record of coordinator work on this repo. Newest session on top.
Builder context: modules M1–M12 were implemented by the K3 builder from my
/goal prompt; everything else below (planning, Wave 0, reviews, patches,
decisions) is my direct work.

---

## 2026-09-17 — Factory repair program (S0–S8)

The independent review at `dae132a` found 43 issue groups. The earlier
F00–F34 end-to-end completion claim is superseded: component test passes
did not establish an integrated factory. Implementation and live gates are
reopened against `docs/factory-reports/REVIEW-2026-09-17.md`.

S0 begins with zero external effects. Existing dirty files, frozen contracts
and legacy financial state are preserved. Repair status/evidence is recorded
in `docs/factory-reports/REPAIRS.md`; prior entries remain historical.

---

## 2026-09-16 → 2026-09-17 — Viral Video Factory build: F00–F34 (35 commits)

**Session outcome:** the durable factory documented in
`docs/viral-video-factory-handover.md` is implemented end to end —
F00 baseline through F34 failure drills. Suite **852 passed /
0 failed**, fully offline. All commits `feat/factory` branch. The only
remaining module is F35 (funded pilot / release handoff), whose live
parts need explicit spend authorisation.

### 1. What was built (by wave)

- **F00–F08 — foundations** (`f01` QA harness, fakes, fault injection;
  domain contracts + immutable revisions + typed money; SQLite store
  WAL/UoW/outbox/backup; artifact registry with probe + dedupe;
  prices/budgets/reservations/settlement; dependency scheduler with
  global capacities, leases, fencing; executor with submission
  recovery/retry/cancellation; events, telemetry, redaction, replay).
- **F09–F14 — intelligence** (seed registry + source acquisition;
  outlier discovery with real cohort medians; Shopify product/media
  snapshots; audiovisual reference analysis → timed blueprints;
  reusable format templates; frozen experiment control/treatment
  planning with declared change regions).
- **F15–F20 — providers + media** (shared generation contract +
  routing; Jimeng Canvas adapter with argv-level persistent fake CLI;
  Google Vertex adapter with OAuth boundary, exact pilot payload,
  HTTP-200 terminal-error parsing; reference packs; TTS/fit/alignment/
  captions; music beds + shared mix).
- **F21–F26 — production** (unique-work asset graph: shared work
  generated once, variant isolation, priced DAG; deterministic
  SVML/SVS/SVRun compiler gated by real `hypit check`/`plan`; render
  builds with section cache; technical + changed-region QC bound to
  output hashes; verified Drive delivery — intent-first, remote-first
  dedupe, content reconcile; identity-safe cleanup).
- **F27–F30 — surface** (FastAPI app: idempotent mutations, revision
  CAS, SSE replay, ranged media, local security; React/Vite dashboard
  with 15 vitest cases; monitoring/compare/review/delivery/studio
  screens; operations module: doctor/start/stop/drain/backup/restore).
- **F31–F33 — publication + learning** (manual + authorised automated
  publishing — public only on confirmed `published_at`; legacy
  `upload_post` defect fixed via new multipart adapter; analytics
  readback with coverage-aware unknown-vs-zero semantics; frozen
  decision policies, reproducible revisioned decisions, independent-
  seed promotion counting, hypothesis library).
- **F34 — failure drills** (new `tests/test_factory_e2e.py`, 14
  integrated drills).

### 2. F34 drill evidence (J01/J03/J04)

- **J01** seed→4 outputs offline: 6 shared + 3 unique picture works;
  only declared slots differ.
- **J03** crash-restart: kill after provider acceptance → reconcile
  finds the same remote id, zero duplicate submissions; kill after
  upload ack-loss → one remote upload total, verified.
- **J04** both provider routes: Jimeng totals in `jimeng_credits`,
  Vertex in `usd_micros`, 9 fake interactions.
- Plus: publication lost-ack → one post; budget cap enforced; global
  capacities across workers; stage timings attributed
  (`queue_wait_s`/`dispatch_s`); render cache parity by exact frame
  count; urllib hard-blocked through the whole flow; owned cleanup
  leaves unrelated processes; legacy entry points intact.

### 3. Defects the drills caught (fixed)

- **Vertex route never ran**: `GenerationAdapter` lacked the
  executor-facing `poll` — added as an `observe` alias on the base so
  both routes share one remote-lifecycle surface.
- **`remote_unfinished` deadlock**: a still-running remote op failed
  the download job permanently, stranding the capacity-1 Vertex hold —
  now retryable (job returns to `ready`, re-polled).
- **Vertex requests missed `model`**: plan-level model was priced but
  not injected into takes — fake correctly returned `model_not_found`.

### 4. Context day: 2026-09-15 (live pilots, pre-factory)

Recorded for continuity (commit-subject level): Vertex OAuth + Lyria/
narration verified; ElevenLabs API verified; Jimeng Canvas node-identity
+ timeout fixes with approved pilot results; Shopify intake + Jimeng
product-reference pilot; Viral Outliers integration with approved
credit batch; Drive access + delivered assets. These pilots produced
the wire contracts F16/F17/F25 later encoded as fakes.

### Verification (at log time)

- `pytest tests -q` → **852 passed, 2 warnings** (~106s), no network.
- Per-module reports: `docs/factory-reports/F00…F34.md`; tracker:
  `docs/viral-video-factory-module-tracker.md`.

### Open items handed forward

| # | Item | Needs |
|---|---|---|
| F35 | Funded pilot, release scope, engineer handoff | explicit spend authorisation for live slices; offline packaging can proceed without it |
| F34-M01/M03 | Operator UI journey + browser-disconnect pressure | human review |
| F31-M04 | Live post verification | authorised real publish |
| F32-M04 | Live analytics horizons | real post + 48h/7d/28d coverage |
| Prior S3–S5/V1–V3 | Keys, cron fire, verify-at-live | unchanged from 09-14 |

---

## 2026-09-14 — Planning → Wave 0 → K3 build → 2 review passes → 2 patch rounds

**Session outcome:** full system built and reviewed; 4 real bugs found and
fixed; suite **194 passed / 0 failed**; zero open bugs. Remaining open items
are all key- or live-run-dependent (see bottom).

### 1. Research & build plan (morning)
- Reviewed `github.com/harry0703/MoneyPrinterTurbo` for short-form generation
  fit; conclusion: usable as the local assembly engine (vendored, pinned),
  not as the intelligence layer.
- Folded the owner's stack choices into the design: Jimeng (Seedance) for
  video/image generation, ElevenLabs as the TTS upgrade, viralhooks.org
  patterns for the hook bank, outlier.so + `ericosiu/ai-marketing-skills`
  for early niche detection.
- Incorporated the two requested extra success steps as first-class modules:
  `shortform-format-library` → M3 Format Library (hook, 3 talking prompts,
  visual payoff, CTA — structure only, never copied wording) and
  `shortform-idea-grill` → M2 Idea Grill (kill weak ideas before spend).
- Produced `BUILD_PLAN.md`: 12 modules (M0–M12), each with its own unit
  tests and a signed validation gate (G0–G12), 9 frozen JSON contracts,
  cost ledger + hard weekly cap, exactly two human approvals per video.

### 2. Wave 0 foundation (commit `5b376f5`)
- Folder tree, `config/system.toml` + secrets templates, 9 frozen contract
  schemas + fixtures, vendored skill/MPT pins, G0 test set green.

### 3. K3 handoff (commit `94579c8`)
- Wrote the `/goal` build prompt for K3 — first a parallel-swarm edition,
  then (owner's call) the regular sequential edition in `GOAL.md`, with
  per-module build → unit-test → validate instructions.
- K3 then built M1–M12 sequentially (12:03–12:37), tests green at every
  commit. Not my code — recorded here for continuity.

### 4. Review pass 1 (commit `743d822`)
- Audited the fresh build. Found:
  - **B1** — weekly shortlist crashed with KeyError on contract-shaped
    ideas (sorted by nonexistent score field).
  - **B2** — verdicts compared AVD against a phantom hard-coded 30 s length.
- Listed plan deviations and the pre-live setup list (S1–S5).

### 5. Decision D1 (commit `559272c`)
- Owner chose macOS crontab over a Kimi Work Blueprint Automation for weekly
  scheduling. Recorded the decision, amended `BUILD_PLAN.md` §M11. Cron
  fires Monday 06:37 local (off-peak), shortlist lands in `data/weekly/`.

### 6. Patch round 1 (commit `322ddb3`)
- B1: sort shortlist by real score fields; corrected the drill fixture;
  added weekly shortlist tests.
- B2: QC stage now measures real duration via ffprobe → `video_len_s`
  stored in the publish record (the one approved additive contract
  exception) → verdicts compare against reality; added verdict-length tests.
- Partially addressed S1/S2: seeded format library with 10 pattern-based
  candidates; hook bank to 5/niche (curated entries ranked above
  `original-pattern` fillers by date).

### 7. Review pass 2 (commit `78ceb54`)
- Full line-by-line audit of all 67 module files. Found:
  - **B3** — `baseline_median_views` never populated: verdict views-leg
    always passed (over-reporting "win") and `promote._mult` divided by
    zero, so **no format could ever be proven** — the M3 learning loop was
    dead.
  - **B4** — live weekly wiring passed raw `scan()` output
    (`{"clusters": …}`) to `grill.run()`, which expects the contract shape
    (`{"niches": …}`) → silently empty shortlist every week, and the
    `data/radar/<date>.json` evidence artifact never written.
- Documented 6 minor notes (M1–M6) and 3 verify-at-live items (V1–V3) in
  `docs/REMAINING_ISSUES.md`.

### 8. Patch round 2 (commit `1ca66df`)
- B3: new `AnalyticsClient.channel_median_views()` (Data API key auth:
  channels `forHandle` → uploads playlist → videos statistics → median via
  `radar.metrics.channel_median`); `readback_stages.record` computes the
  baseline once per run and stamps it before scoring; new
  `YT_CHANNEL_HANDLE` secrets key added to both secrets files (parity test
  preserved). Fail-loud on API errors; `hasattr` guard keeps legacy fakes
  green.
- B4: `_live_weekly_clients.radar_scan` now composes
  `scan → build_report → write_report(data/radar/<date>) → return report`
  — the grill gets the contract shape and the G1 artifact is written every
  run.
- New `tests/test_readback_baseline.py` (5 regression tests): median math,
  loss/win verdicts vs a real baseline, 3-win promotion reaching "proven",
  and the full scan→report→grill composition.
- Suite: 189 → **194 passed**.

### Verification (re-run at log time)
- `make test` → 194 passed, fully offline (no network, no paid calls).
- `git status` clean apart from this log; secrets values never tracked.

### Open items handed forward (none are code bugs)
| # | Item | Needs |
|---|---|---|
| S3 | `voice_id` empty in `config/system.toml` | ElevenLabs key → 3-voice audition per `docs/voice-selection.md` (gate G7) |
| S4 | API keys | `YOUTUBE_API_KEY`, `YT_CHANNEL_HANDLE`, `PEXELS_API_KEY`, `ELEVENLABS_API_KEY`, LLM key, YT Analytics OAuth |
| S5 | Live cron fire verification | run `install-cron`, observe first Monday 06:37 fire |
| V1–V3 | Verify-at-live | CTR units at first pull; Lane A bridge shape; MPT field compat at G8 |
