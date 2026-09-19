# Factory operations guide

Local operation of the Viral Video Factory. Everything here runs
through `scripts/factory.sh` (or `python -m modules.factory.cli`);
no undocumented manual commands are required.

## Setup

```bash
make setup            # pinned venv + deps (pytest, jsonschema,
                      # python-dotenv, fastapi, httpx)
scripts/factory.sh doctor    # preflight: python/ffmpeg required;
                             # node/hypit/gdrive optional + provider
                             # readiness (read-only, never generates)
```

## Configuration

Precedence: **nonempty env var > `.env` > `config/secrets.toml`**.
Safe settings live in `config/factory.toml` (copy
`config/factory.example.toml`); credentials live only in the
environment, `.env`, or `config/secrets.toml` — never in frontend
build variables. `scripts/factory.sh config` shows resolved safe
values, their sources, and which credential refs are set (values are
never printed).

## Services

API and worker are **separately owned** processes (F26 identity
registration — pid + start-time + command). The managed launcher
(`scripts/factory-up.sh` / `factory-down.sh`) starts them through this
checkout's absolute `.venv` path and records `.run/api.pid` /
`.run/worker.pid`; stop/status match only that path, so workers from a
sibling checkout of the same repository are never matched, signaled or
stopped here.

Build the dashboard once, then start the API and worker in separate terminals:

```bash
cd apps/factory-dashboard
npm ci
npm run build
cd ../..
scripts/factory.sh serve --port 5184
# In another terminal at the same workspace:
scripts/factory.sh worker
```

Open `http://127.0.0.1:5184`. The API serves the compiled dashboard, media and
progress from one loopback origin; the worker exposes no port. Both construct
the real domain services through `modules.factory.bootstrap.bootstrap` and use
`DATA_ROOT/factory.db` (default `<workspace>/data/factory/factory.db`). Closing
or refreshing the browser does not stop queued work.

For managed background services, use the same entry points with `start` and
inspect `status`. Start requires a process identity and readiness check. A port
belonging to another application is never terminated. `stop` verifies the owned
process tree and ports. `drain` stops new work while accepted effects can be
observed and collected.

Execution defaults to **offline**. Import media and manually reviewed source
observations in **Seeds**; accept the blueprint, prepare the four variants and
edit the plan. Select your own imported footage and narration/music, save,
prepare the quote, approve the plan, and start it. **Reviews** records asset
reviews before rendering and exact-final creative verdicts afterward. **Compare**
shows the reference and four exports; **Delivery** requires the configured folder,
account, current review evidence and registered final identity. Delivery repeats
reconcile the original receipt. Per-video cleanup preserves these shared services.

Studio opens an isolated copy of the current composition through a durable job.
Use its returned URL; closing Studio verifies owned child processes and ports.
Comments create proposed edits, not new spending authority. Changes to a frozen
plan need a new experiment revision and quotes.

Paid routes require explicit `FACTORY_EXECUTION_MODE=live`, non-secret
`DATA_ROOT/connections.json`, a current qualified capability snapshot for the exact
provider/model/location/input mode, and an exact effect grant plus native-unit
budget. The default application has no configured live transports. Imported music
is supported; unqualified generated-media routes remain unavailable. Credentials
stay in native login storage or the existing private credential sources.

### Reproducible offline application qualification

Use a **fresh `/tmp` root**, not the operational database:

```bash
.venv/bin/python scripts/factory_fixture_app.py --root /tmp/factory-qa --port 5197
# Separate terminal:
.venv/bin/python scripts/factory_fixture_app.py --root /tmp/factory-qa --worker
# Separate terminal:
.venv/bin/python scripts/factory_application_journey.py \
  --url http://127.0.0.1:5197 --root /tmp/factory-qa-evidence --frames 900
```

The journey imports generated test media through HTTP, creates real domain plans,
waits for the independent worker, renders four actual videos, requires distinct
final hashes, and submits explicitly labeled fixture reviews and fake Drive
delivery. It writes stage timestamps and receipts to `journey.json`. Substitute
`--frames 5091` for the long fixture. These receipts are **not real Drive links**.
Native external services are never selected by this fixture launcher.

## Startup reconciliation

`scripts/factory.sh gate` must pass before new paid dispatch:
unfinished attempts and leased jobs block it
(`reconcile external history first`). After a restart, reconcile
remote state before spending again — the executor reconciles by
identity, never re-submits.

## Backup and restore

```bash
scripts/factory.sh backup data/backups/$(date +%Y%m%d) \
    --ledger data/costs/ledger.json
scripts/factory.sh restore data/backups/20260917 data/factory-restore
```

A backup contains a consistent SQLite snapshot (WAL-safe online
backup), verified artifact bytes and manifest, unresolved intents and
budget/financial state, the existing legacy spending ledger, and every `--ledger` file — all SHA-256'd into `manifest.json`.
Git is not the backup for ignored financial state.

Restore uses `<fresh-root>/data/factory/factory.db`, the same default layout as
normal application startup. Restored authority remains blocked even when the
snapshot has no unfinished jobs, until post-backup effects are reconciled.

Restore copies verified files into a **fresh** root (an existing,
nonempty root is refused; tampered files fail with `hash_mismatch`).
After restore, `activation_gate` keeps dispatch gated until external
effects are reconciled — spend headroom only opens on verified remote
history. The original workspace is never touched.

## Provider reconnects

Native logins need human action:
- Jimeng Canvas: re-run the Canvas CLI login flow, then
  `scripts/factory.sh doctor` to confirm readiness.
- Google Vertex: re-auth the Application Default Credentials / OAuth
  loader, then check `GET /api/providers` for granular readiness
  (installed/authenticated/catalog/tested/qualified).

## Research repair workflow

The operator records a funded native-credit budget, creates `/api/research/plans`
with bounded `search` and `creator_history` requests, reviews the exact quote, then
uses its `/authorize` and `/run` commands. `/api/research/evaluate` consumes only
completed plan IDs. These endpoints enqueue durable worker commands; no search
runs in the browser request. Search results are candidates, not their baseline.
History is scoped by platform and creator, restricted to preceding comparable
uploads, deduplicated and bounded to 50 observations with a 20-observation minimum.
The full history request is bounded at 100 posts; an older seed may consequently
have insufficient available history. Missing baseline evidence remains unavailable.

The adapter's configured, expiring tariff supplies pricing. Missing tariffs or
funded scope block dispatch. Live research remains unconfigured until separately
qualified. Fixtures use disk receipts and fake credit balances. The source protocol
is [Viral Outliers search](https://viraloutliers.com/docs/skills/api/search-viral-outlier-posts):
creator history uses the same search endpoint's exact handle filter, all-time range
and descending publication date. It does not assume a profile response envelope.

## Publication and learning repair workflow

Freeze `/api/experiments/{id}/policy` before planning any publications. It defines
the primary metric, 48h/7d/28d horizon, minimum exposure **per variant**, guardrails
and minimum independent experiments for promotion. All four variants share it.

A reviewed final must already have verified delivery and cleanup. Create its
`/api/variants/{id}/publications` intent with the current revision, exact check IDs,
platform/account and metadata. `/api/publications/{id}/authorize` explicitly binds
its final hash, destination, action and expiry. `/run` queues a durable publication;
`/observe` reconciles its existing provider identity. An uncertain reply never
becomes a new upload. Manual declarations remain unverified until a platform
verifier confirms post identity, destination and actual publication time.
YouTube declarations verify against the Data API (`videos.list` on the
configured `youtube_analytics` transport); when no verifier exists for a
destination, registration is rejected as `platform_verifier_unavailable`
and `readiness()` reports the gap — it never fails mid-flow as a
transport error.

The adapter sends actual file bytes, a client request ID and async parameters,
then reads the documented per-platform results. Completed aggregates can contain
skipped platforms; they do not prove that the selected platform published.
See [Upload Post video](https://docs.upload-post.com/api/upload-video/) and
[status](https://docs.upload-post.com/api/upload-status/). Metadata edits and
unpublishing are separate effects using their respective JSON endpoints, with
separate exact-action authorization; see [edit](https://docs.upload-post.com/api/edit-post/)
and [unpublish](https://docs.upload-post.com/api/unpublish-post/).

`/api/publications/{id}/readbacks` queues a read of the selected due horizon.
YouTube thumbnail reach lists existing reporting jobs, paginates their reports,
and downloads/filters CSV files by video and day. Newer files replace the same
reported channel/video/day observation. An absent job is explicit missing data;
job creation is a separate authorized setup action. See [Reporting jobs](https://developers.google.com/youtube/reporting/v1/reference/rest/v1/jobs/create)
and [report discovery](https://developers.google.com/youtube/reporting/v1/reference/rest/v1/jobs.reports/list).

Reach uses `channel_reach_basic_a1`, impression-weighted percentage CTR, and
metric-specific coverage. Source days are America/Los_Angeles calendar days;
DST and publication offsets matter. A calendar aggregate that cannot represent
the exact frozen rolling horizon remains partial; it cannot produce a winner.
Lifetime public views are labelled separately. See [reach report](https://developers.google.com/youtube/reporting/v1/reports/channel_reports),
[metric definitions](https://developers.google.com/youtube/reporting/v1/reports/metrics)
and [day semantics](https://developers.google.com/youtube/reporting/v1/reports/dimensions).

`/api/experiments/{id}/decisions` compares current verified posts, compatible
coverage/query definitions and per-arm exposure. New evidence creates a new
immutable decision; supersession is a separate relation. Four siblings count as
one experiment. A superseded or stale winner cannot promote a template. All
rankings remain observational. Live posting and elapsed readbacks remain separate
qualification gates; offline fixtures do not authorize them.

## Repair release (S8): operator workflow and limits

The supported offline route is an actual application, with an independent worker
and registered artifacts. Imported media is a first-class path. There is no
permission to call real services merely because the application starts.

- **Seeds / Analysis:** attach an imported video. Either enter observations, or
  prepare a seed-bound audiovisual analysis quote, approve it against a USD
  budget, run it, and collect the completed job. Accept the resulting blueprint
  separately. The Vertex analysis adapter sends actual registered video bytes
  using `Content.inlineData`; its conservative 20-MiB input limit requires a
  smaller proxy or imported observations for larger media. Analysis is not the
  Vertex video-generation route and needs separate qualification.
- **Products:** prepare an explicitly selected, read-only Shopify import (up to
  50 handles/IDs). It has a zero-USD quote, account-bound authority, durable job
  and immutable snapshots. A zero-dollar budget records scope; it does not buy
  credits. Imports paginate the catalog and media; interrupted ambiguous work
  retains its receipt and requires reconciliation instead of blind repetition.
- **Plan:** save A/B/C/D, declare each treatment region, select registered media
  or a qualified provider/model, prepare quotes, record funding and approve the
  exact plan. Edits create a new revision and invalidate old spending authority.
- **Audio:** quote ElevenLabs `eleven_v3` for a selected segment and voice. After
  synthesis, fit the actual waveform, listen, approve its hash and attach it to
  a new revision. Existing authored variant captions are preserved. Raw synthesis
  can be reused for fitting without another synthesis charge. Imported licensed
  background music is supported. Generated music remains an optional unqualified
  adapter route and is not enabled by this repair release.
- **Queue:** reconcile original effects after uncertain responses. Retry local
  failed work only after owned cleanup; retries are bounded and cannot create
  paid replacements. Manual picture replacement is available through
  `POST /api/experiments/{id}/assets/replace` with expected revision, reviewer,
  current plan hash, picture node key and registered artifact ID. An unfinished
  remote operation must be collected first. Cleanup releases failed render
  capacity only after owned processes have stopped.
- **Reviews / Compare / Delivery / Studio:** asset and final acceptance remain
  explicit. Technical and unchanged-region QC cannot be substituted by a browser
  verdict. Delivery verifies final hash, destination, filename, size and checksum,
  then cleans up video-owned resources. Shared API/worker services remain running.
  Studio edits are proposed changes, not permission to spend.
- **Publishing / Learning:** freeze the evaluation policy before publication.
  Approve exact final bytes, platform and account. Collect asynchronous post
  identity before readbacks; manual declarations are not verification. Reporting
  job creation uses `POST /api/analytics/reporting/prepare` followed by the generic
  effect-plan approval/run endpoints. Observe existing jobs after ambiguous setup.
  Calendar reports that do not cover the frozen rolling horizon remain partial.

### Optional live connection configuration

`connections.json` contains **no credentials**. Its `enabled` list is explicit.
Canvas/Vertex generation additionally require a current capability snapshot for
that exact model, region and input mode. Auxiliary routes require `account_id`,
`contract_evidence`, `live_evidence`, and an unexpired `qualified_until`. These
fields are evidence references, not switches to mark an untested route tested.
Do not populate them until the corresponding live pilot passes.

| Route key | Additional non-secret settings |
| --- | --- |
| `jimeng_canvas` | profile, region, account_id, location, qualified input_modes |
| `google_vertex` | project, account_id, location, input_modes, verified rates |
| `elevenlabs` | model `eleven_v3`; dated pricing with credits_per_character, valid_until, evidence |
| `audiovisual_analysis` | project, model, location; pricing with estimate_usd_micros, reserve_usd_micros, valid_until, evidence |
| `generated_music` | model; dated pricing with credits_per_second, valid_until, evidence |
| `shopify` | authorized `shop` ending in `.myshopify.com` |
| `publish` | Upload Post user and configured platform/account mapping |
| `youtube_analytics` | exact OAuth account_id and Reporting API qualification |
| `drive` | exact account_id, current contract_evidence, live_evidence and qualified_until |

Credentials resolve at the transport boundary. Google OAuth identity must match
configuration; a key alone does not establish the configured OAuth account.
Offline startup constructs none of these live transports. Unknown actual USD
charges retain reservations until accounting evidence arrives. An overrun is
recorded and blocks new dispatch; it never silently raises authority.

Accounting corrections are first-class routes, both evidence-gated:
`POST /api/reservations/{id}/adjust` upgrades a settlement up the
confirmation ladder (`usage_estimate` → `reported_usage` →
`invoice_confirmed`) — the prior entry is preserved in a
`settlement_adjusted` event and downgrades are refused, so an
estimate-era hold can always be reconciled to the real invoice later.
`POST /api/budgets/resolve-overrun` lifts the `spend_overrun` dispatch
block with operator, evidence and resolution recorded; the overrun
event stays in the ledger.

### Restored activation and rollback

Migration versions 8–10 are forward-only. Validate copies before operational
migration. Never open a migrated database with an older application version.
Use a compatible backup restored into a fresh root instead.

Restore intentionally exits with code **3** when files were restored but dispatch
is gated; this is not permission to start new effects. Inspect its JSON output.
Historical process IDs are quarantined as unowned; restore cannot terminate
processes in the original workspace. Their originals are retained under
`restore-evidence/original-resources.json`.

After verifying all registered assets, reconciling unresolved jobs/attempts and
reviewing account effects and financial activity since `backup_at`, prepare a
local JSON evidence file containing:

```json
{
  "reviewer": "operator name",
  "external_audit_reference": "location of reviewed account and charge evidence",
  "backup_at": "exact timestamp recorded by restore_pending",
  "financial_activity_through": "current reviewed UTC timestamp"
}
```

Then run:

```bash
scripts/factory.sh --root /absolute/fresh-root activate-restore /absolute/audit.json
```

Activation verifies current audit coverage (within one hour), assets and lack of
unresolved effects. It **retires all historical budgets and approvals** while
preserving their original content. Record new funding and new approvals from
current account evidence; old headroom is never restored. Keep original outputs,
provider receipts and financial records even when rolling application code back.

### Qualification evidence

The final repair ledger is [REPAIRS.md](factory-reports/REPAIRS.md); reproducible
release evidence is [REPAIR-S8-EVIDENCE.json](factory-reports/REPAIR-S8-EVIDENCE.json).
The 180×320 fixture exports test timing, changed regions, audio, recovery and the
application graph. They do not qualify production resolution, product identity,
voice quality, provider economics or real publication performance.

Primary protocol references for the new analysis adapter:
[Vertex video understanding](https://cloud.google.com/vertex-ai/generative-ai/docs/multimodal/video-understanding)
and [Vertex Content / inlineData](https://cloud.google.com/vertex-ai/generative-ai/docs/reference/rest/v1/Content).
The model is configured from qualification evidence; documentation examples are
not treated as proof of availability in this account.
