# Build Review — Remaining Issues (2026-09-14, pass 2)

Pass 1 audited + patched (B1, B2 fixed; S1, S2 partially; D1 decided; V3 decided).
Pass 2 (this document): full line-by-line audit of all 67 module files.
Suite state: **189 tests green**, secrets clean, data files schema-valid.

---

## 🔴 Bugs — open, must fix before Wave 3

### B3. `baseline_median_views` is never populated — verdicts AND format promotions are broken
- **Where:** `modules/analytics/readback.py:14-19` (initializes 0); nothing in
  `stages.py readback_stages` ever sets it.
- **Impact 1 (verdicts):** `verdict.py:13` computes `views >= 2.0 × baseline`
  → with baseline 0 the views leg always passes → win/loss decided by AVD alone
  → systematically over-reports "win".
- **Impact 2 (promotions — worse):** `formats/promote.py:11-14` computes the
  multiplier as `views / baseline` → 0.0 forever → `avg_multiplier` can never
  reach `promote_min_multiplier` (1.5) → **no format can ever be promoted to
  "proven"**. The entire M3 learning loop is dead until this is fixed.
- **Fix:** at readback pull time, fetch our channel's recent-uploads view counts
  via Data API (channels→uploads playlist→videos.list ≈ 3 quota units) and
  compute the median with `radar.metrics.channel_median`, storing it into the
  readback doc before `record_window`. Add a test with a non-zero baseline
  proving win/loss/promote all move correctly.

### B4. Live weekly wiring passes the wrong shape to the grill — silent empty shortlist every week
- **Where:** `modules/orchestrate/__main__.py:103` — `radar_scan` returns raw
  `scan()` output (`{"clusters": …}`), but `grill.gate.run()` iterates
  `niche_report["niches"]` (the contract shape built by `radar/report.build_report`).
- **Impact:** on a real `run.sh weekly`, the grill sees zero clusters → zero
  candidates → shortlist says "0/0 ideas killed" **with no error**. The weekly
  cron would run forever producing nothing, and `data/radar/<date>.json` (the
  G1 evidence artifact) is never written.
- **Why tests missed it:** weekly tests mock `radar_scan`/`grill_run` separately;
  nothing tests the `_live_weekly_clients` composition.
- **Fix:** in `_live_weekly_clients`, compose `scan → build_report → write_report`
  inside `radar_scan` (same composition as the dry E2E). Add a wiring test that
  runs the composition through `weekly_stages` with a fake YT transport.

---

## 🟡 Plan deviations

### D1. Weekly scheduling via user crontab — ✅ DECIDED (2026-09-14): keep macOS crontab
- Owner-approved; BUILD_PLAN.md §M11 amended. Crontab fires Monday 06:37 local
  (off-peak), only while the Mac is awake; shortlist lands in `data/weekly/`.

---

## 🟢 Setup tasks before live gates

| # | Item | Status | Blocks | Notes |
|---|---|---|---|---|
| S1 | Hook bank depth | 🟡 partially addressed | G4 | 5/niche (12 curated + 18 `original-pattern` fillers dated below curated); authentic viralhooks.org curation stays a manual weekly pass |
| S2 | Format library seeding | 🟡 partially addressed | G3 | 10 pattern-based candidates seeded; radar-extracted refresh after G1 |
| S3 | `voice_id` empty in `config/system.toml` | ⬜ open — needs ElevenLabs key | G7 | 3-voice audition per `docs/voice-selection.md` |
| S4 | API keys (batched) | ⬜ open | G1, G5–G10 | YOUTUBE_API_KEY, PEXELS_API_KEY, ELEVENLABS_API_KEY, LLM key, YT Analytics OAuth |
| S5 | Live cron fire verification | ⬜ open | G11 | After `install-cron` |

---

## ⚪ Minor / verify-at-live (noted, no urgent action)

- M1. `analytics/windows.py:15` maps window names to hours by positional zip —
  a reordered `windows_hours` in config would silently rename windows. Guarded
  only by the sorted-order config test; make it order-explicit when touching M10.
- M2. `assets/manifest.py:26` — `shot_kinds` override can relabel an image file
  as kind "video" when the shot wanted video but the folder had an image. MPT
  tolerates images in materials; manifest then misrepresents the file. Minor.
- M3. `assemble/task_builder.py:45` — fallback output dir uses unsanitized
  `video_subject`; dormant because produce always passes `video_dir`. Harden
  if the fallback is ever used.
- M4. `script/shots.py` — very short scripts (< 4 sentences after splitting)
  yield < 4 shots → schema rejection. Loud failure at the script stage
  (acceptable), but the error message should name the cause when touching M5.
- M5. `grill/score.py:100` pads killed ideas' `three_bullets` with empty strings
  to stay schema-valid. Harmless (killed ideas never reach production); noted
  for honesty of "schema-valid" claims.
- M6. `__main__` produce asks for spend approval BEFORE discovering missing
  keys/empty `voice_id` (approval-then-fail ordering). Add a cheap preflight
  (keys present, voice_id set) before the approval prompt.
- V1. YT Analytics `ctr` units (÷100 assumption in `_pull_window`) — confirm at
  G10 first pull. Also confirm metric name availability for Shorts traffic.
- V2. Lane A bridge protocol (`JIMENG_BRIDGE_URL` + `/run`) is an assumed shape;
  Lane B is the supported path. No action unless Lane A is wanted.
- V3. MPT batch-manifest field compatibility (`subtitle_display_mode` etc. vs
  actual `VideoParams` fields in vendored v1.3.7) — confirm at G8 live run.
- V4. MODULE_REPORT convention — ✅ DECIDED: gates.md is canonical.

---

## Fixed in pass 1 (for the record)

- B1. Weekly shortlist KeyError on contract-shaped ideas — ✅ FIXED
  (sort by real score fields; drill fixture corrected; `test_weekly_shortlist.py`).
- B2. Phantom 30s video length in verdicts — ✅ FIXED
  (QC measures via ffprobe → `video_len_s` in publish record;
  `test_analytics_verdict_length.py`).

## Verified strengths (pass 2, no action)

- grill: deterministic hard-reject ordering; killed ideas still judged for audit
- radar: quota-aware degradation, baseline excludes candidate from its own median,
  distinct-channel cluster confirmation
- script: hook-verbatim enforcement, hook shot forced to video, LLM output
  falls back to templates on bad JSON
- extract: no-copy guard (Jaccard > 0.6 rejected)
- publish: cadence guard + duplicate record rejection + approval before upload
- ledger: weekly cap enforced before the call; ordered authorize→approval→call→record
- cron: Monday 06:37 off-peak, dupe-guarded install
- Zero network in unit tests; suite fully offline
