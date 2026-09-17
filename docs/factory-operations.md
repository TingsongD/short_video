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
