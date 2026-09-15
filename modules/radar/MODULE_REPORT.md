# M1 Niche Radar — module report

**Built:** `client.py` (urllib YT Data v3, injectable transport), `quota.py`
(search=100u, others=1u, hard cap), `metrics.py` (median baseline excl.
candidate, multiplier, subs_ratio, breakout flag), `scanner.py` (seed channels
→ uploads baseline → keyword search → discovered channels; degrades to
channel-only on QuotaExhausted), `cluster.py` (topic_key via niche-keyword
overlap, confirm at ≥2 distinct channels), `report.py` (contract JSON +
Markdown + Outlier.so checklist), `__main__.py` CLI.

**Contract decisions (schema-faithful, no change requested):**
- One `niches[]` entry per topic cluster; niche with zero breakouts gets one
  empty entry (`cluster_size=0, confirmed=false`) — matches sample fixture.
- `channel_avg` carries the **median** of in-window videos excluding the
  candidate (plan says median; fixture 6200/1000→6.2 confirms).
- `scan_meta.degraded` added (schema has no additionalProperties lock).

**Tests (23, green):** multiplier/median edge cases, breakout flag at 5x/2x/14d
boundaries (fixture vid_outlier_1 flags, 4.9x doesn't, 25d excluded), cluster
confirmation (2 channels same topic ✓, same channel ✗, diff topics ✗), quota
cap + degraded scan, full fixture scan → schema-valid report.

**Gate G1 self-check:** unit-testable criteria pass. Live criteria (<5,000
units over ≥5 niches, 3 spot-checks) deferred to Wave 3 — needs YOUTUBE_API_KEY.

**Risks for integration:** `topic_key` fallback ("misc:*") may split true
clusters when titles share no niche keyword; `guess_format` is a coarse
heuristic M3 should not over-trust; search hit stats require an extra
videos.list call (already batched).

## Viral Outliers integration — 2026-09-15

User selected Viral Outliers with the key in the private root `.env` and the
strict views/followers >2 rule. Added `viral_client.py` (official REST transport),
`viral_records.py` (normalization and evidence filtering), `viral_scan.py`
(reviewed batches, receipts, credit limits, recovery), and `service.py` (shared
CLI/weekly provider selection). Current config selects YouTube + TikTok through
Viral Outliers; the native YouTube route is retained explicitly.

The CLI supports doctor, free preview, plan, scan, and resume. Both credit and
weekly dollar limits are checked before requests. Request intent is persisted
before billing/submission; uncertain responses are not repeated. Fully received
batches are replayable without network. Original platform URLs and follower
ratios flow into M2/M3. See `docs/radar-viral-outliers.md` for operation and limits.

Contracts and frozen fixtures are unchanged. Missing channel medians retain
zero values with `baseline_available=false`; vendor average-based scores are
separate metadata. Live checks confirm authentication and 1-credit pricing,
but available credits are zero. Free teaser metadata cannot establish fresh
candidates. Authenticated filtered search and G1 live sign-off remain pending.

**Validation:** full offline suite **300 passed in 26.22s** (baseline 239).
The additional 61 cases cover the adapter and credential configuration, plus
cross-module evidence handoff and weekly orchestration. G1 remains pending
its live paid-search acceptance, not merely an authentication check.
