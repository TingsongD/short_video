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
registration — pid + start-time + command).

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
