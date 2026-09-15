# Build Review — Remaining Issues (2026-09-14, pass 2)

Pass 1 audited + patched (B1, B2 fixed; S1, S2 partially; D1 decided; V3 decided).
Pass 2 (this document): full line-by-line audit of all 67 module files.
Patch round 2: B3, B4 fixed (see "Fixed in patch round 2" below).
Historical review baseline: **194 tests green**. See the Canvas integration
addendum below and `PROGRESS.md` for current validation.

---

## 🔴 Bugs — none open

B3 and B4 were the only open bugs; both fixed in patch round 2. See below.

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
| S4 | API keys (batched) | ⬜ open | G1, G5–G10 | YOUTUBE_API_KEY, YT_CHANNEL_HANDLE (B3 baseline), PEXELS_API_KEY, ELEVENLABS_API_KEY, LLM key, YT Analytics OAuth |
| S5 | Live cron fire verification | ⬜ open | G11 | After `install-cron` |

---

## ⚪ Minor / verify-at-live (noted, no urgent action)

- M1. `analytics/windows.py:15` maps window names to hours by positional zip —
  a reordered `windows_hours` in config would silently rename windows. Guarded
  only by the sorted-order config test; make it order-explicit when touching M10.
- M2. Image relabeling in the asset manifest — fixed by Canvas integration:
  actual media kind and requested duration are validated before acceptance.
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
- V2. Legacy assumed WebBridge protocol is no longer used by production.
  The official Canvas CLI is primary; manual intake remains available.
- V3. Native MPT local fixture render and returned-file retrieval passed with
  subtitles disabled. The full subtitle/Whisper path still needs live validation.
- V4. MODULE_REPORT convention — ✅ DECIDED: gates.md is canonical.

## Canvas integration addendum

- Implemented Canvas-first production, resumable quoted batches, strict media
  acceptance, explicit stock substitution and native credit ceilings.
- Fixed shuffled clips, narration timing and stale/mislocated final detection.
  MPT auto-upload is disabled in the assembly process; production defaults to QC.
- Canvas CLI 1.0.1 and its Skill installed. Separate Canvas authorization and
  live catalog verification are pending. No paid generation has been performed.
- Pilot and complete asset-set spend require explicit approval after quotes.
  Blender remains deferred. See `docs/jimeng-canvas-cli.md` and
  `docs/production-resume.md` for operation and recovery.

---

## Fixed in patch round 2 (2026-09-14)

- B3. `baseline_median_views` never populated — ✅ FIXED.
  `AnalyticsClient.channel_median_views()` (Data API key auth: channels
  `forHandle` → uploads playlist → videos.statistics, median via
  `radar.metrics.channel_median`); `readback_stages.record` computes the
  baseline once per run from `channel_handle` (new `YT_CHANNEL_HANDLE` in
  `config/secrets.toml`) and stamps it on the readback doc before
  `record_window`. Fail-loud on client errors; legacy fakes without the
  method keep old behavior via a `hasattr` guard.
- B4. Weekly wiring shape mismatch — ✅ FIXED.
  `_live_weekly_clients.radar_scan` now composes
  `scan → build_report → write_report(data/radar/<date>) → return report`,
  so the grill receives the contract shape and the G1 evidence artifact is
  written every run.
- Regression coverage: `tests/test_readback_baseline.py` (5 tests) — median
  computation, loss/win verdicts against a real baseline, 3-win promotion
  to "proven", and the full scan→report→grill composition.

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
