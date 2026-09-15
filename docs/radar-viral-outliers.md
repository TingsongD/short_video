# Viral Outliers discovery

Viral Outliers is the configured M1 discovery provider for YouTube and TikTok.
Its results feed the existing niche report → Idea Grill → format library →
script → Jimeng assets → voice/music → assembly workflow. This change covers
research intake; it does not change generation, editing, or publishing providers.

## What counts as an outlier

A candidate must have **video views / creator followers or subscribers > 2**.
The comparison uses the unrounded counts: 20,000 views / 10,000 followers fails;
20,001 / 10,000 passes. A channel-median multiplier is not an additional gate
in the current configuration. The native YouTube scanner follows this setting
as well; the historical median-and-followers mode remains available in code.

The adapter also requires a verified video content type, a valid YouTube or
TikTok reference, a title/caption, a positive audience count, an identifiable
creator, and a publication timestamp within the configured 14-day window.
Deleted posts, inactive profiles, future dates, photo posts and slideshows are
excluded. Missing information is recorded for review, never invented. YouTube
video results can include long-form references; this adapter does not claim
all results are Shorts or verify their duration.

Repeated posts are deduplicated within each niche using platform + native
video ID. Confirmation still requires two distinct creator identities in the
same topic cluster. Cross-platform identities remain separate; a human should
check whether apparently independent accounts belong to the same person.

Viral Outliers' `outlierScore` compares performance to the creator's average;
it is saved separately as `vendor_outlier_score`. It is neither our >2 ratio
nor a measured channel median. Its search request is not given a minimum
vendor-score filter. `channel_avg=0`, `multiplier=0`, and
`baseline_available=false` explicitly represent an unavailable median in the
existing contract. Idea and format prompts receive the follower ratio and the
original platform link, and are told that the median is unavailable.

## Setup and free checks

Keep `VIRAL_OUTLIERS_API_KEY` in the root private `.env`. Existing configuration
precedence is nonempty environment → project `.env` → private TOML. The client
uses the official HTTPS API with Bearer authentication; it does not follow
redirects with the key or print the key in responses/errors.

From the project folder:

```bash
.venv/bin/python -m modules.radar doctor
.venv/bin/python -m modules.radar preview
```

`doctor` checks authentication, available credits and live search pricing.
`preview` retrieves the free trending teaser and saves browsing evidence. Free
preview never advances candidates into production. The observed free feed
omits publication dates, so it cannot establish freshness.

**Account check on 2026-09-15:** authenticated successfully, available balance
**0**, search price **1 credit**, nominal value **$0.01/credit**. A subscription
allowance and an available balance are different: the provider says credits
are granted on paid invoices, with none granted during the trial. If a paid
invoice should already have funded this account, check its billing/credit
allocation with Viral Outliers before purchasing an additional pack. The
integration does not enable auto-topup, create payment links, or buy credits.

## Review and run a search batch

A prepared pilot already exists: `viral-pilot-20260915`, searching `ai tools`
once on YouTube and once on TikTok. It costs **2 credits**, nominally **$0.02**,
and requests up to 100 records per platform. Paid search has not run.

To prepare that same plan (no network or spending):

```bash
.venv/bin/python -m modules.radar plan --run-id viral-pilot-20260915 \
  --niche ai_tools --query 'ai tools'
```

Review the saved plan. Once credits are available and you approve those
searches, the explicit execution command is:

```bash
.venv/bin/python -m modules.radar scan --run-id viral-pilot-20260915 --credit-ceiling 2
```

The ceiling is for the whole prepared batch, including searches already
submitted in that run. The adapter verifies live pricing, available balance,
and the project's remaining weekly dollar budget before submitting anything.
Each submitted request conservatively reserves its nominal value in the
existing dollar ledger. The receipt records actual `X-Credits-Charged` and
`X-Credits-Balance` headers when present. Failed or ambiguous calls are not
assumed refunded; ledger reservations can therefore exceed final billing.
Jimeng credits remain separate.

Useful planning options:

- `--niche ai_tools` (repeat for other configured niches).
- `--query 'ai tools'` overrides keywords for exactly one selected niche.
- `--platform youtube` or `--platform tiktok` restricts platforms.
- `--pages 1` through `--pages 5`, and `--page-size 1` through `100`.
- By default, each configured keyword is searched once on each platform.
  Six niches × three keywords × two platforms = **36 credits** per full batch.

Every requested page is included in the quote. There is no automatic expansion,
profile enrichment, media download, transcription, crawl, or regeneration.
The API's one-month search window is narrowed locally to the configured age
limit. Bounded keyword search results do not represent an exhaustive platform
scan; ordering by views can miss lower-view outliers outside the selected pages.

## Saved results and recovery

Private generated files live under
`data/radar/viral-outliers/<run-id>/` (gitignored):

- `plan.json`: frozen search scope, criteria and quote.
- `state.json`: saved request outcomes and provider receipts, without auth headers.
- `observations.json`: per-result provenance, ratio and exclusion reasons.
- `niche_report.json` / `.md`: the validated report after every request succeeds.

The completed report is also written to the existing `data/radar/YYYY-MM-DD`
JSON/Markdown locations for downstream compatibility. No schema or frozen
fixture was changed; provider metadata uses the schema's allowed extra fields.
A date-named report can be replaced by a later completed scan on the same day;
run-specific evidence remains available.

```bash
.venv/bin/python -m modules.radar resume --run-id viral-pilot-20260915
```

A fully received batch can be reprocessed without any API calls or approval.
If a prior interruption occurred between requests, repeat with the approved
whole-batch `--credit-ceiling` to submit only requests never attempted.
An interrupted request with an unknown HTTP outcome is **never automatically
resubmitted**. HTTP failures, unknown response shapes and unexpected credit
charges also stop the batch. Inspect `state.json` and provider billing before
preparing a deliberate replacement run. Do not delete recovery state to retry.
Changing query/settings requires a new run ID.

## Weekly workflow

Both the CLI and weekly orchestration use the same provider selection:

```bash
./run.sh weekly --radar-run-id viral-pilot-20260915 --radar-credit-ceiling 2
```

This continues into Idea Grill and therefore still needs its separate existing
LLM spend approval. For discovery-only review, use the radar CLI instead.
Weekly without a run ID prepares the configured `weekly-YYYY-MM-DD` batch;
without a credit ceiling it stops at the radar stage before searches or LLM
calls. Existing scheduled runs do not gain implicit paid-search approval.
The native YouTube route is still explicit:

```bash
.venv/bin/python -m modules.radar scan --provider youtube
./run.sh weekly --radar-provider youtube
```

## Validation and remaining live gate

Full `make test`: **300 passed in 26.22s**. Offline tests cover ratio boundaries, missing/invalid statistics, dates and
media types, provenance, duplicate posts and distinct creators, quote/credit/
dollar caps, changed pricing, partial requests, process interruption, safe
replay, failed responses, weekly provider selection, and TikTok handoff through
Idea Grill and format extraction. Unit tests make no network or paid calls.

Live evidence on 2026-09-15: authentication/pricing checks passed; free preview
returned 12 posts, all without publication timestamps (3 were non-video posts).
No paid searches, purchases or production calls were made. Filtered search
response mapping, YouTube coverage, niche relevance and G1's live acceptance
remain pending until credits are available and the reviewed pilot is approved.
The provider does not publish a fully specified search response schema: the
adapter recognizes explicit post-list envelopes and fails closed on unknown
shapes, retaining receipts for an offline parser correction without repayment.

Sources: [official content search documentation](https://viraloutliers.com/docs/skills/api/search-viral-outlier-posts)
and [live API pricing catalog](https://viraloutliers.com/api/v1/pricing).

### Pilot execution update — 2026-09-15, 21:37 UTC

The user approved the two-search batch and execution was attempted with its
2-credit ceiling. The balance check returned **0**, so execution stopped before
submitting either search. **No credits were spent.** A fresh authentication
check succeeded. The receipt is saved as `last-attempt.json` in the pilot folder.
The unchanged pilot is approved; resolving the available API balance is now
the blocker. Resume the same run after that is resolved, without expanding
its scope or buying credits automatically.
