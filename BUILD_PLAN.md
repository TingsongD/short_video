# Short-Form AI Video System — Build Plan

**Workspace:** `/Users/tingsongdai/Kimi-cursor/Short Form AI YouTube`
**Goal:** A semi-automated pipeline that detects emerging viral niches early, filters weak ideas, reuses proven formats, and produces/publishes short-form videos (TikTok / Reels / YouTube Shorts) at near-zero marginal cost — with a measured feedback loop.
**Created:** 2026-09-14

---

## 1. System overview

10 pipeline stages, grouped into 12 buildable modules (M0–M12):

```
INTELLIGENCE                     PRODUCTION                       DISTRIBUTION & LEARNING
┌─────────────────────┐   ┌──────────────────────────────┐   ┌──────────────────────────┐
│ M1 Niche Radar      │   │ M5 Script Engine (LLM)       │   │ M9  Publishing           │
│   (YT outlier scan) │──▶│ M6 Asset Pipeline (Jimeng)   │──▶│ M10 Analytics Readback   │
│ M2 Idea Grill       │   │ M7 Voice (ElevenLabs)        │   │ M11 Orchestration/cron   │
│   (score & kill)    │   │ M8 Assembly (MoneyPrinter-   │   └──────────┬───────────────┘
│ M3 Format Library   │   │     Turbo, local materials)  │              │
│ M4 Hook Bank        │   └──────────────────────────────┘              ▼
└─────────▲───────────┘                                    feeds results back to M1–M3
          └──────────────────────────────────────────────────────────────┘
M0 Foundations (folders, config, vendored skills, MPT install) underpins everything.
M12 End-to-end validation gates the first real production spend.
```

**Success metrics (first 60 days):**
- Radar: ≥ 3 validated niche clusters found per weekly scan
- Grill: rejects ≥ 30% of candidates (proof the gate works)
- Production: ≤ 15 min human time per finished video; ≤ $0.30 variable cost per video during testing
- Learning: every published video has 24–48h / 7d / 28d readback records; ≥ 1 format promoted from "candidate" → "proven" by day 45

---

## 2. Data contracts (interfaces between modules)

All inter-module data is JSON on disk under `data/`. No module calls another module's internals.

| Contract | Producer → Consumer | Path | Key fields |
|---|---|---|---|
| `niche_report` | M1 → M2 | `data/radar/YYYY-MM-DD.json` | `niche, cluster_size, breakout_videos[{video_id, channel_id, views, channel_avg, multiplier, subs_ratio, published_at, title, format_guess}], scan_meta` |
| `scored_ideas` | M2 → M3/M5 | `data/grill/YYYY-MM-DD.json` | `idea_id, niche, topic, hook_overlay, virality_score, hook_score, payoff, three_bullets[], cta, status(pass/kill), kill_reason` |
| `format_entry` | M3 → M5 | `data/formats/library.json` | `format_id, name, hook_type(spoken/caption/onscreen), beats[3], visual_payoff, cta_pattern, watch_reference, status(candidate/proven/retired), our_stats{}` |
| `shot_list` | M5 → M6 | `data/production/<video_id>/shot_list.json` | `script_text, hook_line, shots[{idx, duration_s, prompt_jimeng, asset_type(video/image), pexels_fallback_term}], voice_text, subtitle_lang` |
| `asset_manifest` | M6 → M8 | `data/production/<video_id>/assets/manifest.json` | `assets[{shot_idx, file, kind, source(jimeng/manual/stock)}]` |
| `mpt_task` | M8 → M8(MPT CLI) | `data/production/<video_id>/mpt_task.json` | MPT `VideoParams` fields: `video_subject, video_script, video_source="local", video_materials[], voice_name, subtitle_*, video_aspect="9:16"` |
| `publish_record` | M9 → M10 | `data/published/<video_id>.json` | `video_id, platform_video_ids{youtube, tiktok, instagram}, title, caption, hashtags[], published_at, format_id, idea_id, niche` |
| `readback` | M10 → M1/M3 | `data/analytics/<video_id>.json` | `windows{"48h":{views, avg_view_duration, ctr, retention_points}, "7d":{...}, "28d":{...}}, verdict, format_promotion` |

**Validation rule:** every contract file must validate against a JSON Schema in `schemas/`. Schema tests live in `tests/test_schemas.py`.

---

## 3. Module breakdown

### M0 — Foundations
**Purpose:** reproducible workspace, secrets, and third-party code in place.

**Build tasks:**
1. Create folder tree: `data/{radar,grill,formats,production,published,analytics}`, `modules/`, `schemas/`, `tests/`, `tests/fixtures/`, `vendor/`, `config/`, `logs/`
2. Vendor skills (pinned commit): `vendor/ai-marketing-skills/{yt-competitive-analysis, shortform-idea-grill, shortform-format-library}` from `github.com/ericosiu/ai-marketing-skills`
3. Clone `vendor/MoneyPrinterTurbo` (pinned release tag, e.g. v1.3.7); install with `uv sync --frozen` (Python 3.11)
4. `config/secrets.toml` (gitignored): `YOUTUBE_API_KEY`, `ELEVENLABS_API_KEY`, optional `LLM_API_KEY/base_url/model`
5. `config/system.toml`: niches seed list, scoring thresholds, readback windows, cost caps
6. Root `Makefile` / `run.sh`: `make test`, `make radar`, `make produce`, `make e2e`

**Unit tests:**
- `test_folders.py` — all required directories exist
- `test_config.py` — `system.toml` parses; required keys present; thresholds within sane ranges
- `test_secrets_shape.py` — secrets file exists and has required keys (never prints values; skips value checks in CI)

**Validation gate G0:** `make test` green; `python vendor/MoneyPrinterTurbo/cli.py --help` runs; no secret appears in any tracked file (`grep` sweep).

---

### M1 — Niche Radar (DETECT)
**Purpose:** weekly scan of candidate niches; find early breakout clusters.
**Source base:** vendored `yt-competitive-analysis/analyze.py`, extended.

**Build tasks:**
1. `modules/radar/scanner.py` — wrap/extend vendored script:
   - Input: niche → competitor-channel seed list (`config/niches.toml`) + niche keyword list
   - YouTube Data API: `search.list` (keyword, publishedAfter=14d) + `channels.list` + `playlistItems`/`videos.list` for stats
   - Compute per video: `multiplier = views / channel_median_views`, `subs_ratio = views / subscribers`
   - Breakout flag: `multiplier ≥ 5 AND subs_ratio ≥ 2 AND age ≤ 14 days` (tunable)
2. `modules/radar/cluster.py` — group breakouts by normalized topic/format keywords; cluster confirmed when ≥ 2 distinct channels spike on same topic
3. `modules/radar/report.py` — emit `niche_report` JSON + human-readable Markdown summary
4. Quota manager: daily unit budget counter (search.list = 100 units); degrade gracefully to channel-only scans when exhausted
5. Optional cross-check tab: manual Outlier.so free-tier checklist printed in report

**Unit tests (fixtures in `tests/fixtures/yt/`, no live API):**
- `test_multiplier.py` — median & multiplier math on fixture channel (incl. zero-view edge)
- `test_breakout_flag.py` — seeded video with multiplier 6.2/subs_ratio 3.1 flagged; video at multiplier 4.9 not flagged; video older than 14d excluded
- `test_cluster.py` — 2 channels spiking same topic → cluster confirmed; same channel twice → not confirmed
- `test_report_schema.py` — output validates against `schemas/niche_report.schema.json`
- `test_quota.py` — budget counter stops search calls at cap

**Validation gate G1:** one live scan over ≥ 5 seed niches costs < 5,000 quota units, completes < 10 min, emits schema-valid report; manually spot-check 3 flagged videos on YouTube — all 3 must be genuinely view-anomalous for their channel.

---

### M2 — Idea Grill (FILTER)
**Purpose:** kill weak ideas before any spend; score survivors.
**Source base:** vendored `shortform-idea-grill` (rubric + `score_ideas.py`), run in batch mode (radar JSON replaces the human interview).

**Build tasks:**
1. `modules/grill/generate.py` — expand each radar cluster into 5–10 candidate ideas (LLM call, prompt template in `modules/grill/prompts.py`); each idea = topic + 5-second overlay hook + payoff + 3 bullets
2. `modules/grill/score.py` — port rubric: independent `virality_score` and `hook_score` (1.0–10.0); hard-reject rules: no specific viewer / no repayable hook / no filmable payoff / unsupported numeric claim
3. `modules/grill/gate.py` — pass threshold: `hook_score ≥ 7 AND virality_score ≥ 6` (config); emits `scored_ideas` with `status` and `kill_reason`
4. LLM-as-judge with rubric in system prompt; deterministic re-scoring (temperature 0); log raw judge output

**Unit tests:**
- `test_hard_reject.py` — fixture ideas missing viewer/payoff/hook are killed with correct `kill_reason`
- `test_threshold.py` — score 6.9 hook → killed; 7.0 → passes
- `test_three_bullets.py` — every passing idea has exactly 3 bullets
- `test_schema.py` — output validates against `schemas/scored_ideas.schema.json`
- `test_determinism.py` — same input scored twice (mocked LLM) → identical scores

**Validation gate G2:** feed G1's live report; grill must (a) kill ≥ 30% of candidates, (b) leave ≥ 5 passing ideas, (c) every kill has a human-legible reason; operator reviews 10 random judgments and agrees with ≥ 8.

---

### M3 — Format Library (STRUCTURE)
**Purpose:** turn proven outliers into reusable structures; compound what works.

**Build tasks:**
1. `modules/formats/library.py` — CRUD over `data/formats/library.json`; statuses `candidate → proven → retired`
2. `modules/formats/extract.py` — from each breakout video (M1) + passing idea (M2), draft a `format_entry`: hook type split (spoken/caption/on-screen), 3 beats, visual payoff, CTA pattern, watch reference URL (structure only — never copies wording; LLM prompt enforces)
3. `modules/formats/match.py` — assign each passing idea exactly 1 default format (+ optional alt, labeled)
4. `modules/formats/promote.py` — readback-driven: format with ≥ 3 our-channel videos at ≥ 1.5× our channel median → `proven`; 3 consecutive underperformers → `retired`

**Unit tests:**
- `test_crud.py` — add/update/retire entries; IDs stable
- `test_extract_schema.py` — extraction output validates; `watch_reference` is a real video URL shape
- `test_match.py` — every idea gets exactly one default format
- `test_promote.py` — fixture stats trigger promote/retire at exact thresholds
- `test_no_copy.py` — similarity check: entry hook text vs reference title ≤ 0.6 token overlap (guards plagiarism)

**Validation gate G3:** library seeded with ≥ 10 entries from first radar run; every M2-passing idea matched; library.json schema-valid.

---

### M4 — Hook Bank (HOOK)
**Purpose:** fast opening-line selection, consistent with format entry.
**Source:** viralhooks.org (manual/curated — no public API).

**Build tasks:**
1. `data/hooks/bank.json` — curated per-niche hooks from viralhooks.org (respect site terms; store hook text + niche + hook_type + source URL + date added)
2. `modules/hooks/select.py` — pick hook by (niche, hook_type from M3 entry); returns hook + attribution
3. Refresh cadence: weekly manual curation task (15 min) — checklist in `docs/hook-curation.md`

**Unit tests:**
- `test_bank_schema.py` — every entry has niche/type/source/date
- `test_select.py` — selector returns hook matching niche+type; raises on empty niche
- `test_attribution.py` — every selected hook carries source URL

**Validation gate G4:** ≥ 5 hooks per seed niche in bank; selector integrates with M5 (hook line present in every generated script).

---

### M5 — Script Engine (SCRIPT + SHOT LIST)
**Purpose:** produce voiceover script + Jimeng shot list from (idea, format, hook).

**Build tasks:**
1. `modules/script/write.py` — LLM writes 60–110 word script (≈ 20–40s at 1.0 voice rate): hook verbatim as first line → 3 beats from format entry → loop/CTA ending; enforce "hook must be repaid" rule in prompt
2. `modules/script/shots.py` — split script into 4–7 shots; per shot: Jimeng prompt (visual, camera, style), duration, asset_type (video for hook shot + hero beats; image allowed for filler), plus Pexels fallback search term
3. `modules/script/voicetext.py` — clean TTS text (numbers spelled out, no markdown)
4. Emit `shot_list.json`

**Unit tests:**
- `test_length.py` — script within word bounds; hook is first sentence
- `test_beats.py` — 4–7 shots; durations sum ≈ estimated voice duration ±20%
- `test_hook_first.py` — hook shot flagged `asset_type=video`, `shot_idx=0`
- `test_fallback.py` — every shot has non-empty Pexels fallback term
- `test_schema.py` — validates `schemas/shot_list.schema.json`

**Validation gate G5:** generate 5 scripts from real M2 output; operator rates hook strength/payoff; ≥ 4/5 approved without edits.

---

### M6 — Asset Pipeline (VISUALS — Jimeng)
**Purpose:** turn shot list into local media files. **Two lanes; Lane B always available as fallback.**

**Build tasks:**
1. `modules/assets/queue.py` — render shot list → per-shot prompt cards (copy-paste ready) + target folder `data/production/<video_id>/assets/`
2. **Lane B (manual):** checklist `docs/jimeng-manual-lane.md`; `modules/assets/intake.py` watches folder, validates downloads (codec/resolution/duration via ffprobe), maps files → `shot_idx` by filename convention `shot-01.mp4`
3. **Lane A (automated):** `modules/assets/jimeng_bridge.py` — Kimi WebBridge drives `jimeng.jianying.com` in the user's logged-in browser: submit prompt → poll render → download → same intake validation. Selector map isolated in `modules/assets/jimeng_selectors.json` for cheap UI-change repairs
4. Pexels fallback: if a shot fails both lanes, fetch via Pexels API using fallback term (needs free `PEXELS_API_KEY`)
5. Emit `asset_manifest.json`

**Unit tests:**
- `test_intake.py` — accepts valid fixture mp4/png; rejects corrupt/zero-byte; correct shot mapping from filenames
- `test_manifest.py` — schema-valid; every shot covered or marked fallback
- `test_selectors_file.py` — selector JSON parses; required keys present
- `test_pexels_fallback.py` — mocked API returns clip; manifest marks `source=stock`

**Validation gate G6:** Lane B produces a complete asset set for one real shot list (all files pass ffprobe checks: ≥ 720p, mp4/png, video ≥ 3s). Lane A smoke test: login state detected + one prompt submitted + file downloaded (manual confirmation of browser state; selectors versioned).
**Known risk:** Lane A is inherently brittle (SPA, login, UI drift). It is never a release blocker — Lane B is the supported path.

---

### M7 — Voice (ElevenLabs)
**Purpose:** natural English voiceover, consistent channel voice.

**Build tasks:**
1. `modules/voice/tts.py` — ElevenLabs TTS for `voice_text` (model `eleven_v3` or current default); voice ID pinned in `config/system.toml`; output `voice.mp3`
2. Duration check: ffprobe duration must be 15–60s (typical short) — feeds MPT as `custom_audio_file` path or as TTS inside MPT (decision: generate here for reuse/QA, pass file to MPT)
3. Voice audition doc: `docs/voice-selection.md` (3 candidates → pick 1)

**Unit tests:**
- `test_tts_mock.py` — mocked API: request payload correct (voice id, model, text)
- `test_duration_gate.py` — fixture mp3 of 8s rejected; 25s accepted
- `test_text_clean.py` — markdown/emoji stripped before send

**Validation gate G7:** one real generation; blind listen vs Edge TTS baseline — ElevenLabs output clearly preferred; duration within bounds; cost logged (characters used).

---

### M8 — Assembly (MoneyPrinterTurbo)
**Purpose:** subtitles, BGM, 9:16 assembly via MPT CLI, local materials.

**Build tasks:**
1. `modules/assemble/task_builder.py` — build `mpt_task.json`: `video_source="local"`, `video_materials` from asset manifest, `custom_audio_file=voice.mp3`, subtitle style (word-by-word option), BGM volume, `video_aspect="9:16"`, `n_threads`
2. Batch runner: `python vendor/MoneyPrinterTurbo/cli.py --batch-file <manifest>` (per-video manifests also supported); logs to `logs/`
3. `modules/assemble/qc.py` — ffprobe QC on `final-*.mp4`: 1080×1920, has audio stream, duration ≈ voice duration ±1.5s, file size sane; subtitle burn spot check via extracted frame
4. Variants: `video_count=2` for A/B cuts on passing ideas only

**Unit tests:**
- `test_task_builder.py` — manifest maps to correct MPT fields; relative paths resolved from manifest dir
- `test_qc.py` — fixture good/bad mp4s pass/fail correctly (resolution, missing audio, duration drift)
- `test_batch_schema.py` — batch file ≤ 100 tasks, all entries pre-validated

**Validation gate G8:** one full assembly from real M6+M7 outputs; QC green; operator watches result — subtitles synced, hook shot first, audio clear over BGM.

---

### M9 — Publishing
**Purpose:** publish to YouTube Shorts first (analytics richest), TikTok/IG optional.

**Build tasks:**
1. `modules/publish/metadata.py` — title/caption/hashtags from idea + format CTA (LLM, platform-specific variants)
2. Lane 1 (default): MPT cross-post via upload-post integration, or manual upload checklist `docs/publish-manual.md`
3. `modules/publish/record.py` — write `publish_record` JSON (platform IDs, time, format_id, idea_id, niche) — **readback depends on this file**
4. Policy guardrail: max 2 posts/day/channel; channel identity checklist (niche-consistent name/avatar/description)

**Unit tests:**
- `test_metadata.py` — hashtags ≤ platform limits; title ≤ 100 chars; CTA keyword present
- `test_record.py` — schema-valid; duplicate video_id rejected
- `test_cadence.py` — cadence guard blocks 3rd post in a day

**Validation gate G9:** one real video published to a test channel; `publish_record` complete; video playable publicly.

---

### M10 — Analytics Readback (LEARN)
**Purpose:** close the loop; promote/kill formats and niches on evidence.

**Build tasks:**
1. `modules/analytics/pull.py` — YouTube Data API (public stats) + YouTube Analytics API (own channel: impressions, CTR, AVD, retention; OAuth `yt-analytics.readonly`)
2. `modules/analytics/windows.py` — scheduled pulls at 48h / 7d / 28d after publish; write `readback` JSON
3. `modules/analytics/verdict.py` — vs channel baseline: `win = views ≥ 2× median AND AVD ≥ 70% of length`; verdicts feed M3 promote/retire and M1 niche weighting
4. Weekly learning summary appended to radar report

**Unit tests:**
- `test_windows.py` — correct pull scheduling from `published_at` (timezone-safe)
- `test_verdict.py` — fixture stats at thresholds → win/loss correct
- `test_readback_schema.py` — schema-valid
- `test_promotion_feed.py` — verdict file triggers correct M3 status change

**Validation gate G10:** readbacks generated for all G9 videos at each window; at least one format status change computed (even if "stay candidate").

---

### M11 — Orchestration & Scheduling
**Purpose:** run the loop unattended.

**Build tasks:**
1. Kimi Work Automation (cron, weekly, off-peak minute, project workspace): run M1 scan → M2 grill → M3 extract/match → post ranked shortlist into the conversation
2. `run.sh produce <idea_id>` — one command runs M4→M9 for an approved idea (human approval gate before Jimeng/ElevenLabs spend)
3. `run.sh readback` — process due analytics windows
4. Cost ledger `data/costs.json` — log every paid call (LLM tokens, ElevenLabs chars, Jimeng credits spent manually); weekly cap in config; hard stop + alert at cap

**Unit tests:**
- `test_cost_ledger.py` — entries append; cap triggers stop
- `test_pipeline_order.py` — produce command runs stages in order, stops on failed gate
- `test_approval_gate.py` — no paid call executes without approval flag

**Validation gate G11:** weekly automation fires (verify run record); cost ledger shows all spend; approval gate demonstrably blocks an unapproved produce run.

---

### M12 — End-to-End Integration
**Purpose:** prove the whole loop on one video before scaling.

**Build tasks:**
1. Full run: radar → grill → format → hook → script → assets (Lane B) → voice → assemble → QC → publish (test channel) → first readback
2. Latency/cost measurement per stage; fill `docs/e2e-report.md`
3. Failure drills: kill LLM key / Jimeng lane / YT quota — pipeline must fail loudly at the right gate, never silently

**Unit tests:** `test_e2e_dry.py` — runs M1→M8 with all externals mocked (fixture radar report, fixture assets, fixture mp3); asserts every contract file appears and is schema-valid, in order.

**Validation gate G12 (release):** E2E report shows: real 1080×1920 video with synced subtitles published on test channel; total human time ≤ 30 min; variable cost within cap; 48h readback present. Only then green-light batch production (10 videos/niche test).

---

## 4. Testing strategy (global)

- **Framework:** pytest; `make test` runs everything in < 60s
- **No paid/external calls in unit tests** — all LLM/TTS/YT/Jimeng interactions behind small client interfaces with fixtures/mocks (`tests/fixtures/`)
- **Fixture media:** generate tiny valid mp4s/pngs/mp3s once with ffmpeg into `tests/fixtures/media/` (committed, < 5 MB total)
- **Schema tests:** every JSON contract has a `.schema.json` and a round-trip test
- **Live tests** (separate `make test-live`, never in default run): G1 scan, G7 TTS, G9 publish — each guarded by an env flag and budget check
- **CI-shaped discipline:** a module is "done" only when its tests pass *and* its validation gate is signed off in `docs/gates.md`

---

## 5. Build order & milestones

| Phase | Modules | Exit criteria |
|---|---|---|
| **P0 Foundations** | M0 | G0 green |
| **P1 Intelligence** (no spend) | M1 → M2 → M3 → M4 | G1–G4; first ranked shortlist produced |
| **P2 Production** | M5 → M6 → M7 → M8 | G5–G8; first finished video on disk |
| **P3 Distribution & learning** | M9 → M10 | G9–G10; first readbacks recorded |
| **P4 Autonomy** | M11 → M12 | G11–G12; weekly loop runs itself |

Human approval is required exactly twice per video: (1) approve idea after grill, (2) approve spend before production. Everything else is automatable.

---

## 6. Config & secrets checklist

| Item | Where | Needed by |
|---|---|---|
| `YOUTUBE_API_KEY` (Data API v3) | secrets | M1, M10 |
| YouTube Analytics OAuth | secrets | M10 |
| `ELEVENLABS_API_KEY` | secrets | M7 |
| LLM key (Kimi / DeepSeek / OpenAI-compatible) | secrets | M2, M5, M9 |
| `PEXELS_API_KEY` (free) | secrets | M6 fallback |
| Jimeng login (user's browser session) | n/a | M6 Lane A |
| Outlier.so free account | n/a | M1 cross-check (optional) |

---

## 7. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Jimeng web UI changes break Lane A | Selector map file; Lane B manual path always supported; Lane A never a blocker |
| YT API quota exhaustion | Quota manager; channel-only scan mode; weekly (not daily) cadence |
| "Inauthentic content" policy (mass-produced spam) | Grill quality gate, per-channel niche identity, ≤ 2 posts/day, consistent voice, real format variety |
| LLM judge drift (M2 scores inflate) | Deterministic temp-0 scoring; weekly human audit of 10 judgments; rubric versioned |
| Format copying crosses into plagiarism | `test_no_copy` similarity guard; structure-only extraction prompt; attribution stored |
| Paid-API runaway | Cost ledger + hard cap (M11); approval gate before any spend |
| Pexels filler hurts retention | Seedance/Jimeng hook shot mandatory; stock only for middle beats during testing |

---

## 8. Definition of done (whole system)

1. All gates G0–G12 signed in `docs/gates.md`
2. Weekly cron delivers a ranked niche shortlist without human action
3. One command turns an approved idea into a published video with a publish record
4. Every published video has 48h/7d/28d readbacks; ≥ 1 format promotion decision made from real data
5. Cost ledger proves ≤ $0.30/video during testing phase
