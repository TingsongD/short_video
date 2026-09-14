# Build Review — Remaining Issues (2026-09-14, patched)

Audited against BUILD_PLAN.md after the K3 sequential build (commits `f14ac3f`→`1fd2144`).
Overall: **high-quality build** — 182+ tests green, zero contract drift vs Wave 0,
secret sweep clean, dry E2E genuinely chains M1→M8, gates.md is honest.

**Patch round 1 (2026-09-14): B1, B2 fixed; S1, S2 partially addressed; V3 decided.**
Remaining: S3 + S4 (need keys), S5 (needs live fire), V1 + V2 (verify at live).

---

## 🔴 Bugs — FIXED ✅

### B1. Weekly shortlist crashed on real grill output (KeyError) — ✅ FIXED
- **Was:** `stages.py` sorted by non-contract `i["scores"]["total"]`; grill emits
  top-level `virality_score` / `hook_score`.
- **Fix:** sort by `-(hook_score + virality_score)`; drill fixture rewritten to the
  contract shape; new `tests/test_weekly_shortlist.py` runs weekly_stages end-to-end
  on the frozen `scored_ideas.sample.json` + guards against non-contract fields
  returning.

### B2. Readback verdicts used a phantom 30s video length — ✅ FIXED
- **Was:** `publish_record` never carried `video_len_s`; M10 verdicts defaulted to 30s.
- **Fix:** QC stage now ffprobe-measures the final video and the publish record
  carries `video_len_s` (additive, schema-permitted; fixture updated). New
  `tests/test_analytics_verdict_length.py` proves a 30s watch wins on a 30s video
  but loses on a 50s video, and that missing length can never silently win.
  Happy-path drill asserts the record carries the measured ~20s.

---

## 🟡 Plan deviations

### D1. Weekly scheduling via user crontab instead of Kimi Work Automation — ✅ DECIDED (2026-09-14): keep macOS crontab
- Plan §M11 specified a Kimi Work Blueprint Automation; K3 built
  `modules/orchestrate/schedule.py` appending to the user crontab.
- **Owner decision: keep the crontab approach.** Accepted consequences:
  fires only while this Mac is awake at the scheduled time; weekly shortlist
  lands in `data/weekly/` + `logs/runs/`, not in the Kimi conversation.
  BUILD_PLAN.md §M11 amended accordingly.

---

## 🟢 Setup tasks before live gates

| # | Item | Status | Blocks | Notes |
|---|---|---|---|---|
| S1 | Hook bank depth | 🟡 partially addressed | G4 | Bank now 5/niche: 12 curated + 18 `original-pattern` hooks (site is a JS SPA — authentic viralhooks.org curation stays a manual weekly pass per docs/hook-curation.md) |
| S2 | Format library seeding | 🟡 partially addressed | G3 | `data/formats/library.json` seeded offline with 10 pattern-based candidate entries; radar-extracted refresh after G1 with real LLM |
| S3 | `voice_id` empty in `config/system.toml` | ⬜ open — needs ElevenLabs key | G7 | Do the 3-voice audition per `docs/voice-selection.md`, pin the winner |
| S4 | API keys (batched) | ⬜ open | G1, G5–G10 | YOUTUBE_API_KEY, PEXELS_API_KEY, ELEVENLABS_API_KEY, LLM key, YT Analytics OAuth → into `config/secrets.toml` |
| S5 | Live cron fire verification | ⬜ open | G11 | After first `install-cron` run |

---

## ⚪ Verify-at-live (assumptions to confirm, not known bugs)

- V1. `stages.py` `_pull_window` divides Analytics `ctr` by 100 — confirm the
  API's actual unit at G10 first pull; adjust if it already returns a ratio.
- V2. Lane A bridge protocol (`JIMENG_BRIDGE_URL` + `/run` actions) is an assumed
  WebBridge HTTP shape — Lane B (manual) is the supported path; Lane A is
  best-effort and correctly non-blocking. No action unless Lane A is wanted.
- V3. MODULE_REPORT.md coverage — ✅ DECIDED: gates.md is the canonical
  per-module evidence record; no backfill needed.

---

## Verified strengths (no action)

- Contracts frozen and respected: `git diff 94579c8..HEAD -- schemas/ tests/fixtures/` empty
- Paid calls correctly ordered: `authorize → approval → call → ledger` (stages.py)
- Produce refuses grill-killed ideas before any stage runs
- Publish gated by cadence check + explicit approval
- 9 failure drills each fail loudly at the right gate, incl. unapproved publish
- Radar baseline excludes the candidate video from its own median
- Zero network in unit tests; suite runs fully offline
