# Build Review — Remaining Issues (2026-09-14)

Audited against BUILD_PLAN.md after the K3 sequential build (commits `f14ac3f`→`1fd2144`).
Overall: **high-quality build** — 182 tests green, zero contract drift vs Wave 0,
secret sweep clean, dry E2E genuinely chains M1→M8, gates.md is honest
(G1–G12 correctly pending, no overclaiming). Issues below, severity-ordered.

---

## 🔴 Bugs — must fix before Wave 3 live gates

### B1. Weekly shortlist crashes on real grill output (KeyError)
- **Where:** `modules/orchestrate/stages.py:278`
- **What:** sorts passing ideas by `i["scores"]["total"]`, but M2's contract-shaped
  output has top-level `virality_score` / `hook_score` and **no `scores` dict**.
  The weekly cron will crash at the `formats` stage on first real run.
- **Why tests missed it:** the only fixture with a `"scores"` key is
  `tests/test_failure_drills.py:50` — it does NOT match the scored_ideas contract,
  so the suite exercises weekly_stages with a shape the grill never produces.
- **Fix:** sort by `-(hook_score + virality_score)`; rewrite the drill fixture to
  the contract shape; add one weekly-stages test that runs on
  `fixtures/contracts/scored_ideas.sample.json`.

### B2. Readback verdicts computed against a phantom 30s video length
- **Where:** `modules/orchestrate/stages.py:245` — `rec.get("video_len_s", 30)`
- **What:** `publish_record` never records `video_len_s` (publish stage builds the
  record without it, stages.py:184–194), so the M10 win check
  (`avg_view_duration ≥ 0.7 × length`) always uses the 30s default. Verdicts are
  wrong for any video that isn't ~30s.
- **Fix:** measure final video duration with ffprobe at QC stage and write
  `video_len_s` into the publish record (additive field — schema allows it;
  coordinator-approved contract extension). Update `publish_record.sample.json`
  fixture + add a verdict test with a non-30s length.

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

## 🟢 Setup tasks before live gates (not defects)

| # | Item | Blocks | Notes |
|---|---|---|---|
| S1 | Hook bank: 2 hooks/niche, gate requires ≥ 5 | G4 | Run the curation pass in `docs/hook-curation.md` (viralhooks.org, manual) |
| S2 | Format library empty (`data/formats/library.json` missing) | G3 | Needs one LLM seeding run (≥ 10 entries) after first live radar scan |
| S3 | `voice_id` empty in `config/system.toml` | G7 | Do the 3-voice audition per `docs/voice-selection.md`, pin the winner |
| S4 | API keys (batched) | G1, G5–G10 | YOUTUBE_API_KEY, PEXELS_API_KEY, ELEVENLABS_API_KEY, LLM key, YT Analytics OAuth → into `config/secrets.toml` |
| S5 | Live cron fire verification | G11 | After D1 decision |

---

## ⚪ Verify-at-live (assumptions to confirm, not known bugs)

- V1. `stages.py:212` divides Analytics `ctr` by 100 — confirm the API's actual
  unit at G10 first pull; adjust if it already returns a ratio.
- V2. Lane A bridge protocol (`JIMENG_BRIDGE_URL` + `/run` actions) is an assumed
  WebBridge HTTP shape — Lane B (manual) is the supported path; Lane A is
  best-effort and correctly non-blocking. No action unless Lane A is wanted.
- V3. MODULE_REPORT.md exists only in `modules/radar` and `modules/grill`.
  gates.md already carries per-module evidence, so either backfill the other 6
  or drop the convention — cosmetic.

---

## Verified strengths (no action)

- Contracts frozen and respected: `git diff 94579c8..HEAD -- schemas/ tests/fixtures/` empty
- Paid calls correctly ordered: `authorize → approval → call → ledger` (stages.py:37-44)
- Produce refuses grill-killed ideas before any stage runs (stages.py:29-32)
- Publish gated by cadence check + explicit approval (stages.py:168-174)
- 9 failure drills each fail loudly at the right gate, incl. unapproved publish
- Radar baseline excludes the candidate video from its own median (scanner.py:248-253)
- Zero network in unit tests; suite runs fully offline in ~13s
