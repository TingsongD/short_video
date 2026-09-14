# Long-Form Conversion Plan — Short-Form AI Video System → Long-Form AI Video System

**Workspace:** `/Users/tingsongdai/Kimi-cursor/Short Form AI YouTube`
**Goal:** Convert the existing short-form pipeline (12 modules, M0–M12, 194 green tests) into a long-form YouTube pipeline (target 6–12 min videos, 16:9) that detects emerging long-form niches early, filters weak ideas, reuses proven long-form formats, and produces/publishes at low marginal cost — with the same measured feedback loop.
**Created:** 2026-09-14
**Status:** PLAN ONLY — no code modified by this document.

---

## 0. Conversion strategy (read first)

**Decision: profile-based conversion, not a hard fork.** Introduce an operating
`profile` dimension (`"short"` | `"long"`) that swaps per-module parameters,
prompts, thresholds, and contract extensions. `"long"` becomes the default,
primary profile — the product is converted. The `"short"` profile remains in
the tree as legacy regression armor: the existing 194 tests keep passing
unchanged, and every long-form change is provably additive.

Why not a hard fork/rewrite:
- 70%+ of the system is length-agnostic: schema validation, quota manager,
  cost ledger, approval gates, verdict/promotion machinery, fixtures
  discipline, cron wiring, CLI skeleton. Rewriting these rebuys solved
  problems and new bugs.
- The four genuinely length-sensitive areas — script structure, voice
  chunking, asset scale, analytics thresholds — are cleanly separable behind
  config + new contract versions.
- If a true hard cutover is wanted later, archiving the `"short"` profile is
  a one-commit deletion after the long profile is proven. The reverse
  (resurrecting shorts after a rewrite) is not cheap.

**What "long-form" means here (defaults, all tunable in config):**

| Parameter | Short profile (today) | Long profile (new default) |
|---|---|---|
| Target length | 15–60 s | 360–720 s (8+ min unlocks mid-roll ads) |
| Aspect / resolution | 9:16, 1080×1920 | 16:9, 1920×1080 |
| Structure | hook → 3 bullets → CTA | cold-open hook (0–30 s) → roadmap → 3–6 chapters → payoff → CTA/end-screen |
| Script size | ~80–150 words | ~900–1800 words (≈150 wpm pacing) |
| Shots per video | 4–8 | 40–100 (grouped: see L6) |
| Subtitles | word-by-word | sentence mode |
| Thumbnail | frame grab (implicit) | **generated asset, first-class contract** |
| Cadence | ≤ 2/day | 1–3/week |
| Readback windows | 48h / 7d / 28d | 7d / 28d / 90d (long-form matures slower) |
| Win AVD ratio | 0.7 | 0.45–0.55 (50% avg retention on 8 min is strong) |
| Variable cost/video | ≤ $0.30 | est. $1.50–$4.00 (see §6) |

---

## 1. System overview (long profile)

Same 3-act shape as BUILD_PLAN.md §1, with one NEW module (thumbnails) and
four heavily-extended modules (script, voice, assets, readback):

```
INTELLIGENCE                     PRODUCTION                          DISTRIBUTION & LEARNING
┌─────────────────────┐   ┌──────────────────────────────────┐   ┌──────────────────────────┐
│ L1 Niche Radar      │   │ L5 Script Engine (chaptered LLM) │   │ L10 Publishing (+chapters│
│   (long-form scan)  │──▶│ L6 Asset Pipeline (grouped shots)│──▶│     +thumbnail upload)   │
│ L2 Idea Grill       │   │ L7 Voice (chunked TTS + stitch)  │   │ L11 Analytics Readback   │
│   (long rubric)     │   │ L8 Assembly 16:9 (MPT, sentence  │   │   (long thresholds)      │
│ L3 Format Library   │   │     subtitles)                   │   │ L12 Orchestration        │
│   (long archetypes) │   │ L9 Thumbnails (NEW — Jimeng img  │   └──────────┬───────────────┘
│ L4 Hook/Intro Bank  │   │     + text overlay + QC)         │              │
└─────────▲───────────┘   └──────────────────────────────────┘              ▼
          └────────────────────── feeds results back to L1–L3 ──────────────────────────────┘
L0 Foundations (profile switch, contract v2s, config) underpins everything.
L13 End-to-end validation gates the first real long-form production spend.
```

**Success metrics (first 90 days — long-form compounds slower):**
- Radar: ≥ 2 validated long-form clusters per weekly scan
- Grill: rejects ≥ 40% of long candidates (long ideas are easier to over-rate)
- Production: ≤ 45 min human time per finished video; ≤ $4.00 variable cost
- Learning: every published video has 7d/28d/90d readbacks; ≥ 1 long format promoted to "proven" by day 75
- Retention: avg view duration ≥ 45% on at least one video by day 60

---

## 2. Contract changes (interfaces)

Existing rule preserved: every contract validates against a JSON Schema in
`schemas/`; contracts are append-only. Long-form uses **new schema files**
(`*.long.schema.json` or `v2` fields marked additive-optional) — the short
schemas stay frozen so the 194-test suite is untouched.

| Contract | Change | Path (long profile) | Key additions |
|---|---|---|---|
| `niche_report` | v2 additive | `data/long/radar/YYYY-MM-DD.json` | per-video `duration_s`, `length_class(medium/long)`; scan_meta gains `profile:"long"` |
| `scored_ideas` | v2 additive | `data/long/grill/YYYY-MM-DD.json` | `chapter_beats[]` (3–6) alongside `three_bullets`; `search_intent_score`; `series_potential` |
| `format_entry` | v2 additive | `data/long/formats/library.json` | `archetype(essay/deep_listicle/tutorial/mini_doc/storytime)`; `beats` now 5-slot (hook/roadmap/chapters/payoff/cta); `target_length_s` |
| `long_script` | **NEW** | `data/long/production/<video_id>/long_script.json` | `chapters[{idx, title, script_text, est_words, shots[]}], hook_line, roadmap_line, voice_text (concat), subtitle_lang` — supersedes `shot_list` for long profile |
| `asset_manifest` | v2 additive | `data/long/production/<video_id>/assets/manifest.json` | per-asset `role(hook/chapter_opener/broll/static)`; `ken_burns` flag for image beats |
| `voice_manifest` | **NEW** | `data/long/production/<video_id>/voice_manifest.json` | `chunks[{chapter_idx, file, duration_s, start_s}]` — start_s values are the **chapter timestamps** used by L10 description chapters |
| `mpt_task` | v2 additive | `data/long/production/<video_id>/mpt_task.json` | `video_aspect="16:9"`, sentence subtitle fields, concatenated materials list |
| `thumbnail_manifest` | **NEW** | `data/long/production/<video_id>/thumbnails/manifest.json` | `variants[{file, prompt, text_overlay, qc{readable_at_120px, contrast_ok}}], chosen` |
| `publish_record` | v2 additive | `data/long/published/<video_id>.json` | `profile:"long"`, `chapters[{title, start_s}]`, `thumbnail_file`, `video_len_s` (already added in B2) |
| `readback` | v2 additive | `data/long/analytics/<video_id>.json` | windows keyed `7d/28d/90d`; `retention_shape{intro_30s_retained, chapter_boundary_drops[]}`; verdict per long thresholds |

---

## 3. Module breakdown (L0–L13)

Each module lists: delta vs its M-counterpart, build tasks, unit tests, gate.
"Reuse as-is" means: no code change, only profile config.

### L0 — Foundations: profile switch (extends M0)
**Build tasks:**
1. `config/system.toml`: add `profile = "long"` (default) + `[long.*]` section
   mirrors of every length-sensitive key (`[long.radar]`, `[long.grill]`,
   `[long.voice]`, `[long.assembly]`, `[long.readback]`, `[long.costs]`).
   Short sections remain for the legacy profile.
2. `modules/common/config.py`: `profile_config(cfg, profile)` resolver —
   returns the profile-view of config; unknown profile = loud error.
3. Data-dir partitioning: all writers gain a `profile` path prefix
   (`data/long/...`); short data stays at existing paths (no migration).
4. New schemas: `long_script`, `voice_manifest`, `thumbnail_manifest` +
   v2-additive versions of the 7 extended contracts. Fixtures for all.

**Unit tests:**
- `test_profile_resolver.py` — long view returns long keys; short view
  byte-identical to current behavior; bad profile raises
- `test_long_schemas.py` — every new/v2 schema round-trips its fixture
- `test_existing_suite_untouched.py` — meta-guard: full pre-existing suite
  runs green with `profile="short"` (CI proves conversion is additive)

**Gate LG0:** `make test` = 194 legacy + new L0 tests green; zero changes to
existing schema files in `git diff`.

---

### L1 — Niche Radar, long-form (extends M1)
**Delta:** find breakouts in *long* videos; slower velocity, different bars.
**Build tasks:**
1. Scanner gains length filter: `search.list videoDuration=medium|long`
   (> 4 min); store `duration_s` + `length_class` per candidate.
2. Long thresholds (`[long.radar]`): `breakout_multiplier = 3.0` (long-form
   spreads thinner), `breakout_subs_ratio = 2.0`, `max_video_age_days = 30`
   (long-form pops later), cluster rule unchanged (≥ 2 distinct channels).
3. Search-intent tag: keyword-searched topics flagged `evergreen_candidate`
   when ≥ 3 breakout videos share a search-phrased title pattern.
4. Reuse as-is: quota manager, median math, degradation mode, report writer
   (report gains `profile` in scan_meta).

**Unit tests:**
- `test_long_filter.py` — fixture search page with mixed durations: shorts
  excluded, medium/long kept with correct `length_class`
- `test_long_thresholds.py` — multiplier 3.1/age 25d flagged under long
  config; same video NOT flagged under short config (profile isolation)
- `test_evergreen_tag.py` — 3 same-pattern titles → `evergreen_candidate`

**Gate LG1:** live long scan over ≥ 5 seed niches < 6,000 quota units;
spot-check 3 flagged videos — all genuinely anomalous AND genuinely long-form.

---

### L2 — Idea Grill, long rubric (extends M2)
**Delta:** long ideas need depth, searchability, retention design — not just a
5-second hook. Over-enthusiasm is the failure mode: gate tightens.
**Build tasks:**
1. `modules/grill/prompts.py` long rubric: scores `hook_score`,
   `virality_score` (kept) **+** `search_intent_score`, `depth_score`
   (can this sustain 6+ min without padding?), `retention_design_score`
   (open loops, chapter escalation). Judge sees rubric version `long-1`.
2. Hard-reject rules, long: no chapter structure possible / payoff fits in
   30 s (it's a short, kill or demote) / monetization-hostile topic /
   unsupported numeric claim (kept).
3. Generator emits `chapter_beats[3–6]` per idea; gate: pass requires
   `hook ≥ 7 AND virality ≥ 6 AND depth ≥ 6 AND search_intent ≥ 5`
   (`[long.grill]`).

**Unit tests:**
- `test_long_hard_reject.py` — 30-second-payoff idea killed with reason
  "payoff too shallow for long-form"
- `test_long_threshold.py` — boundary scores per axis
- `test_chapter_beats.py` — passing ideas carry 3–6 beats
- `test_determinism.py` — temp-0 rescore identical

**Gate LG2:** on LG1's report: kills ≥ 40%, ≥ 3 passing ideas, operator
agrees with ≥ 8/10 sampled judgments.

---

### L3 — Format Library, long archetypes (extends M3)
**Delta:** beats triple → 5-slot structure; statuses/promotion machinery
unchanged (per-profile stats).
**Build tasks:**
1. Seed `data/long/formats/library.json` with 6 archetype candidates:
   video essay, deep-dive listicle ("7 X explained"), tutorial,
   mini-documentary, storytime/commentary, explainer-with-demo. Each:
   `beats = [hook, roadmap, chapters, payoff, cta]`, `target_length_s`.
2. `extract.py` long prompt: structure-only from long breakouts (hook
   style, chapter count, escalation pattern, payoff placement) — same
   no-copy Jaccard guard.
3. Promotion per profile: `our_stats` keyed by profile so long/short
   multiplier histories never mix.

**Unit tests:**
- `test_archetype_schema.py` — 6 seeds validate
- `test_extract_long.py` — extraction from fixture long breakout yields
  5-slot beats, no-copy guard fires on near-duplicate wording
- `test_profile_stats_isolation.py` — short-profile readback cannot touch
  long entry stats

**Gate LG3:** library seeds load; match assigns every L2 passing idea exactly
one archetype.

---

### L4 — Hook Bank → Intro Bank (extends M4)
**Delta:** long-form hook = cold open (first 15–30 s) + roadmap + open loop.
**Build tasks:**
1. Intro entries: `{intro_id, niche, archetype, cold_open_pattern,
   roadmap_pattern, open_loop, source_url, date_found}`; seed 3/archetype
   from pattern knowledge (viralhooks.org-style patterns, re-worded for
   long-form intros — never copied verbatim).
2. `select.py` gains intro selection by (niche, archetype); short-path
   `select()` untouched.

**Unit tests:** `test_intro_select.py` (deterministic pick, curated-over-
filler ordering), `test_intro_schema.py`.
**Gate LG4:** every archetype has ≥ 3 curated intros.

---

### L5 — Script Engine, chaptered (HEAVIEST DELTA — extends M5)
**Delta:** this is the core of the conversion. Short path (one-shot LLM,
template fallback) becomes a 3-pass long generator.
**Build tasks:**
1. **Outline pass:** idea + format + intro → chapter outline (titles +
   per-chapter payoff + target words, total 900–1800 @ ~150 wpm).
2. **Chapter pass:** one LLM call per chapter (context: outline + previous
   chapter's last paragraph — continuity without re-sending everything).
   Verbatim cold-open enforcement carried over from short: `hook_line` must
   appear unaltered at script head.
3. **Continuity/claims pass:** whole-script review — transition quality,
   repeated-fact check, numeric-claims audit (same unsupported-claim kill
   rule), reading-level target.
4. Shot extraction per chapter: 1 shot per 4–8 s of narration with
   `role` tagging (chapter openers → Jimeng; middle → stock/Ken Burns).
5. Output: `long_script` contract + concatenated `voice_text` with chapter
   markers. Template fallback kept: per-chapter templates if LLM JSON fails
   (loud degradation, never silent).

**Unit tests:**
- `test_outline_schema.py`, `test_chapter_stitch.py` (concat order +
  markers), `test_hook_verbatim_long.py` (hook integrity survives 3 passes),
- `test_claims_audit.py` (unsupported number → flagged), 
- `test_shot_roles.py` (openers Jimeng-tagged; density within 4–8 s/shot),
- `test_fallback_long.py` (broken chapter JSON → template chapter + warning
  surfaced)
- `test_word_budget.py` — total within ±15% of target length

**Gate LG5:** one real LLM script from an L2-passing idea: reads coherently
aloud end-to-end, chapters escalate, hook verbatim, 900–1800 words, zero
unsupported claims.

---

### L6 — Asset Pipeline at scale (extends M6)
**Delta:** 8 min @ 4–8 s/shot = 60–120 shots. Generating all via Jimeng is
slow and expensive — introduce **shot grouping**.
**Build tasks:**
1. Roles (from L5): `hook` + `chapter_opener` (≈ 8–14 shots) → Jimeng
   Seedance; `broll` → Pexels first, Jimeng only on stock-miss;
   `static` → Jimeng image + Ken Burns pan/zoom in assembly.
2. Reuse rule: same b-roll clip may repeat ≤ 2× per video, never adjacent.
3. Queue/manifest gains `role` + `ken_burns`; completeness rule unchanged
   (all roles required before assembly).
4. Lane B (manual drop) remains fully supported — at long scale, Lane B
   folder gets per-role subfolders.

**Unit tests:**
- `test_grouping.py` — role assignment counts vs script length
- `test_reuse_rule.py` — 3rd repeat rejected; adjacent repeat rejected
- `test_manifest_roles.py` — v2 manifest validates; short manifests still
  validate against the v1 schema (isolation)

**Gate LG6:** full asset set for the LG5 script with ≤ 15 Jimeng generations;
manifest complete.

---

### L7 — Voice, chunked (extends M7)
**Delta:** 900–1800 words ≈ 5k–11k chars — exceeds comfortable single-call
size and, more importantly, we need **per-chapter audio** to derive chapter
timestamps.
**Build tasks:**
1. Chunk per chapter (split long chapters at paragraph boundaries, ≤ ~4.5k
   chars/request); same `voice_id` + model across chunks.
2. Stitch with ffmpeg concat (crossfade 50 ms optional); measure per-chunk
   durations → `voice_manifest.json` (`start_s` cumulative sums = chapter
   timestamps for L10).
3. Bounds (`[long.voice]`): total 300–780 s; per-chunk prosody spot-check
   stays manual at gate.
4. Cost ledger: per-chunk units recorded (chars), service `elevenlabs`.

**Unit tests:**
- `test_chunking.py` — paragraph-boundary splits, size cap respected
- `test_stitch_manifest.py` — fixture mp3s stitched; `start_s` monotonic;
  total = sum(chunks) ± 0.1 s
- `test_duration_bounds.py` — out-of-bounds total raises at voice stage

**Gate LG7:** real TTS of the LG5 script: audition 3 voices (per
`docs/voice-selection.md`, long-form addendum: 60 s stamina listen), stitched
file plays clean, timestamps within 1 s of chapter boundaries.

---

### L8 — Assembly 16:9 + long QC (extends M8)
**Delta:** geometry, subtitle mode, duration; MPT (vendored v1.3.7) already
accepts arbitrary lengths/material counts.
**Build tasks:**
1. Task builder long profile: `video_aspect="16:9"`, `resolution="1920x1080"`,
   `subtitle_mode="sentence"`, `video_count_variants=1` (long videos don't
   need variants), Ken Burns params for `static` assets, BGM unchanged at
   0.15 with ducking.
2. Optional chapter title cards (config flag, default off for v1).
3. QC long: resolution/duration/frozen-frame checks kept; add loudness
   normalization target (−14 LUFS, loudnorm pass) and subtitle-overflow
   check (sentence length × font metrics vs frame width).

**Unit tests:**
- `test_task_long.py` — 16:9 task validates against v2 mpt_task schema;
  materials concat order = script order
- `test_ken_burns.py` — static assets carry zoompan params
- `test_qc_long.py` — fixture 6-min video passes; loudness fixture out of
  range fails; overlong subtitle line flagged

**Gate LG8:** real MPT render of the full video: 1920×1080, audio synced,
subtitles correct at sentence granularity, QC green.

---

### L9 — Thumbnails (NEW MODULE — no M-counterpart)
**Purpose:** long-form CTR lives and dies on the thumbnail; Shorts never
needed one. First-class pipeline stage.
**Build tasks:**
1. `modules/thumbs/generate.py` — 2–3 Jimeng image variants from
   title+chapter-1 payoff (prompt template per archetype).
2. `modules/thumbs/overlay.py` — Pillow text overlay: ≤ 4 words, stroke +
   shadow, safe margins; font from bundled CJK-safe set.
3. `modules/thumbs/qc.py` — automated checks: readable at 120 px width
   (downscale + variance heuristics), contrast ratio, no text in bottom-
   right duration-badge zone; emits `thumbnail_manifest`.
4. Selection: `chosen` set by operator approval (3rd approval gate) for
   first 10 videos; later: YouTube Test & Compare via API (V-item, not v1).

**Unit tests:**
- `test_overlay.py` — text fits, margins respected, deterministic render
- `test_thumb_qc.py` — fixture failing contrast/legibility rejected
- `test_thumb_schema.py` — manifest validates

**Gate LG9:** 3 variants generated for the E2E video; QC passes ≥ 2;
operator picks one.

---

### L10 — Publishing, long (extends M9)
**Build tasks:**
1. Metadata builder long: title ≤ 70 chars front-loaded, description with
   **chapter timestamps from `voice_manifest`** (`0:00 Intro`, …), tags,
   end-screen CTA line, thumbnail upload (`thumbnails.set`).
2. Cadence (`[long.publish]`): `max_posts_per_week = 3` (replaces daily cap
   for long profile); duplicate-record rejection unchanged.
3. `publish_record` v2 fields written (`profile`, `chapters`,
   `thumbnail_file`, `video_len_s`).
4. Premiere scheduling: config flag, default off (V-item).

**Unit tests:**
- `test_chapters_format.py` — timestamps render `H:MM:SS`/`M:SS` correctly;
  monotonic; match voice_manifest
- `test_cadence_weekly.py` — 4th post in 7 days blocked
- `test_publish_v2_schema.py`

**Gate LG10:** real upload to test channel: chapters clickable in player,
thumbnail set, record v2 schema-valid.

---

### L11 — Analytics Readback, long thresholds (extends M10)
**Delta:** maturity timeline and success bars differ; machinery (windows,
verdict, baseline median — post-B3) reused per profile.
**Build tasks:**
1. `[long.readback]`: `windows_hours = [168, 672, 2160]` (7d/28d/90d);
   `win_views_multiplier = 2.0`; `win_avd_ratio = 0.45`; window-name mapping
   made order-explicit (fixes minor note M1 while touching this code).
2. Retention shape: from retention_points compute `intro_30s_retained` and
   per-chapter-boundary drop deltas (needs `chapters` from publish record);
   store in readback v2.
3. Baseline: `channel_median_views` per profile — long baseline computed
   from long uploads only (`duration_s ≥ 240` filter on uploads playlist).
4. Verdict/promotion: unchanged logic, long config values.

**Unit tests:**
- `test_long_windows.py` — due/naming for 7d/28d/90d; order-explicit mapping
- `test_retention_shape.py` — fixture curve → correct 30 s retention +
  boundary drops
- `test_long_baseline.py` — uploads mixed short/long → median over long only
- `test_verdict_long.py` — AVD 46% + views 2.1× → win; 44% → loss

**Gate LG11:** first real long readback: windows recorded, baseline non-zero,
verdict sane, retention shape present.

---

### L12 — Orchestration (extends M11)
**Build tasks:**
1. `run.sh` / `__main__`: `--profile long` flag (default from config);
   weekly cron produces the long shortlist (B4-fixed composition reused
   with long radar config).
2. Cost caps (`[long.costs]`): `weekly_cap_usd = 40` (2–3 videos × ≤ $4 +
   radar quota is free); ledger services gain `jimeng-image` for thumbnails.
3. **Three approval gates per video** (was two): idea, spend, **thumbnail
   choice** — wired through the same `approval.require` mechanism.
4. Failure drills extended: kill Jimeng mid-assets → loud stop with
   per-role missing list; kill TTS on chapter 3 → resume-from-chunk state
   on disk (V1.1 item — v1 may re-run whole voice stage).

**Unit tests:**
- `test_profile_wiring.py` — CLI long profile injects long ctx end-to-end
  (fakes), short profile unchanged
- `test_three_approvals.py` — all three gates demanded in order
- `test_ledger_long.py` — cap enforcement across the enlarged service set

**Gate LG12:** cron fires, long shortlist lands in `data/long/weekly/`.

---

### L13 — End-to-End Integration (extends M12)
**Build tasks:**
1. `test_e2e_dry_long.py` — L1→L10 with all externals mocked; every long
   contract appears schema-valid, in pipeline order (mirrors `test_e2e_dry.py`).
2. One real 6–12 min video on the test channel; `docs/e2e-long-report.md`
   with per-stage latency/cost.
3. Retention post-mortem at 7d: compare intro_30s_retained vs hook design;
   feed findings into L4 intro bank.

**Gate LG13 (release):** real 1920×1080 video with chapters + generated
thumbnail published; human time ≤ 45 min; cost ≤ $4; 7d readback present.
Only then green-light the 2–3/week cadence.

---

## 4. Testing strategy (delta vs BUILD_PLAN §4)

- All existing rules hold (offline unit tests, fixtures, no paid calls,
  schema round-trips, `make test-live` gated).
- **Additive-only proof:** CI runs the suite twice — once default (long),
  once `KIMI_PROFILE=short` — both must be green. This is the mechanical
  guarantee the conversion didn't break shorts.
- New fixture media: one 6-min synthetic 16:9 mp4 + 3 fixture thumbnails
  (< 8 MB added to `tests/fixtures/media/`).
- Contracts: short schemas frozen forever; long v2 schemas new files;
  cross-profile contamination tests (L3, L11) are first-class.

---

## 5. Build order & milestones

| Wave | Modules | Exit criteria | Depends on |
|---|---|---|---|
| **LW0** | L0 | LG0 green; suite green in both profiles | — |
| **LW1 Intelligence** | L1 → L2 → L3 → L4 | LG1–LG4; first long shortlist | LW0 |
| **LW2 Script & Voice** | L5 → L7 | LG5, LG7; stitched chaptered voiceover | LW0 (L5), LW0 (L7) |
| **LW3 Visuals** | L6 → L8 → L9 | LG6, LG8, LG9; full asset set + render + thumbs | LW2 (script/voice feed L6/L8) |
| **LW4 Distribution** | L10 → L11 | LG10, LG11 | LW3 |
| **LW5 Autonomy** | L12 → L13 | LG12, LG13; weekly long loop runs itself | LW4 |

Parallelizable: within LW2, L5 and L7 are independent until stitch-test;
within LW3, L9 (thumbnails) is fully independent of L6/L8 and can run
concurrently; L1–L4 (intelligence) can run parallel to LW2 entirely.

---

## 6. Cost model (long profile, per 8-min video, estimates)

| Stage | Driver | Est. cost |
|---|---|---|
| LLM (outline + 4–6 chapters + continuity + judge + metadata) | ~15–25k tokens | $0.10–$0.40 |
| ElevenLabs TTS | ~6k–11k chars | $0.30–$2.20 (tier-dependent) |
| Jimeng Seedance | 8–14 grouped shots | credit-dependent, est. $0.50–$1.50 |
| Jimeng image (thumbnails) | 3 variants | ~$0.10 |
| Pexels | b-roll | $0 |
| **Total** | | **≈ $1.00–$4.20** |

Weekly at 2 videos: ≤ $8.40 + radar (free quota) ≪ proposed $40 cap.
Approval gate still fires before every spend; ledger proves actuals.

---

## 7. Risks & mitigations (long-form specific)

| Risk | Mitigation |
|---|---|
| 8 min of AI voice = listener fatigue | 3-voice stamina audition (LG7); chapter-level pacing marks; BGM ducking; human listen-through before publish |
| Asset monotony over 60–120 shots | Shot grouping + reuse caps (L6); Ken Burns motion on stills; chapter openers always fresh Jimeng |
| "AI slop" policy enforcement is harsher on long-form | Grill depth gate; real chapter structure; ≤ 3 posts/week; one consistent voice/niche identity per channel |
| Chapter timestamp drift | Timestamps derived from measured audio (voice_manifest), never estimated; LG10 verifies clickable chapters |
| Cost per failed video 10× shorts | Grill kills harder (≥ 40%); spend approval shows full per-stage estimate; first 5 videos at 4–6 min (cheaper) before 8–12 min |
| MPT render time/memory on 8-min jobs | LG8 measures; fallback: render per-chapter segments + ffmpeg concat (design noted, not built in v1) |
| Thumbnail is the new bottleneck skill | 3-variant generation + QC heuristics + operator pick; promotion data (L11 CTR) trains later iteration |

---

## 8. Explicitly out of scope (v1)

- Multi-language dubbing of long videos (dubbing skill exists; later wave)
- YouTube Test & Compare API thumbnail A/B (manual pick first)
- Premiere scheduling, end-screen/card API automation
- Horizontal clips auto-cut from long videos back into the short profile
  (attractive loop — design after LG13)
- Per-chapter TTS resume after partial failure (v1 re-runs voice stage)

---

## 9. Definition of done (long-form system)

1. All gates LG0–LG13 signed in `docs/gates.md`; suite green in BOTH profiles
2. Weekly cron delivers a ranked long-form shortlist without human action
3. One command turns an approved long idea into a published, chaptered,
   thumbnailed video with a v2 publish record
4. Every published video has 7d/28d/90d readbacks with retention shape;
   ≥ 1 long format promoted to "proven" from real data
5. Ledger proves ≤ $4.00/video; intro_30s_retained ≥ 70% on the release video
