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

```bash
scripts/factory.sh start api --port 8100 --alt 8101 -- \
    .venv/bin/python -m uvicorn modules.factory.api.app:app
scripts/factory.sh status          # per-service state + ports
scripts/factory.sh drain           # stop NEW dispatch; accepted work
                                   # finishes, reservations persist
scripts/factory.sh stop api        # deliberate stop of THIS service
```

If the port is held by a process the factory does not own, `start`
tries `--alt` ports or fails with `port_occupied` — it never kills a
foreign listener. Re-starting an already-running service is a no-op
(`already_running`).

## Startup reconciliation

`scripts/factory.sh gate` must pass before new paid dispatch:
unfinished attempts and leased jobs block it
(`reconcile external history first`). After a restart, reconcile
remote state before spending again — the executor reconciles by
identity, never re-submits.

## Backup and restore

```bash
scripts/factory.sh backup data/backups/$(date +%Y%m%d) \
    --ledger data/ledger.jsonl
scripts/factory.sh restore data/backups/20260917 data/factory-restore
```

A backup contains: consistent SQLite snapshot (WAL-safe online
backup), artifact manifest, unresolved intents + budget/financial
state, and every `--ledger` file — all SHA-256'd into `manifest.json`.
Git is not the backup for ignored financial state.

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
