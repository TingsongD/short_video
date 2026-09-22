# Credential, preview and diagnostic recovery repair

Scope: safe offline implementation of the reported findings, including
dashboard recovery messages. Existing worktree edits were preserved. No
production run, attempt, reservation, budget or credential was changed. No
production service was restarted and no paid request was made.

## Findings and changes

1. **Google reauthentication remains an operator task.** Credential failures
   now distinguish reauthentication, missing credentials, transport problems,
   missing dependencies and other refresh errors without returning raw OAuth
   exception text. Explicit Providers re-check now refreshes cached credentials
   rather than only bypassing the application readiness cache.
2. **Actionable recovery.** Both newly paused runs and the dashboard view of
   historical generic failures explain the recovery steps. Authentication
   recovery is separate from financial reconciliation; messages do not promise
   a refund or authorize a retry. Ordinary unknown job errors keep their
   existing fallback guidance.
3. **Evidence-backed pre-request failure.** The synchronous Vertex analysis
   adapter marks credential preflight failure with a durable `not_sent`
   receipt, bound to the attempt ID and canonical request hash. Only matching
   proof, with no existing remote ID or settled charge, can close the attempt
   and release its hold in one transaction. Restart/replay reads that receipt
   without reissuing the request. A bare error code is not sufficient.
4. **Historical reservation unchanged.** The old `loader_failed` attempt did
   not record this proof. Reservation `rsv:4054f3d9ad71465d` is not migrated,
   released or relabelled by this patch. Lost-response/unknown outcomes still
   retain their holds; operator reconciliation requires separate evidence.
5. **Preview safety.** Verification formerly fetched metadata twice, including
   on a hashing thread sharing the API writer connection, and dereferenced the
   second lookup without checking for a missing row. Preview requests now use
   one metadata snapshot through an independently opened/closed read-only
   connection on the hashing thread. Ordinary artifact verification also
   eliminates the duplicate lookup. Missing records/files and changed bytes
   return typed failures. Range responses and containment checks remain intact.
6. **Historical SQLite error not conclusively explained.** The unsafe shared
   preview connection path is removed and covered by concurrent preview tests
   that enforce SQLite thread ownership. This is hardening, not a claim that
   the exact historical `InterfaceError` root cause has been proven.
7. **Durable manual-session logs.** CLI API and worker launches write private
   `.run/factory-api.jsonl` / `.run/factory-worker.jsonl` logs (4 MiB, three
   backups), separate from launcher stdout/stderr files. Events include time,
   PID, service, job/run ID, stage and typed errors as applicable. Raw exception
   messages, request bodies, headers and query strings are excluded. Startup,
   shutdown, worker failure, run pause and API failure paths are covered.

## Verification

- Targeted offline coverage: `tests/test_factory_auth_recovery.py`,
  `tests/test_factory_media_recovery.py`,
  `tests/test_factory_diagnostic_logging.py`: **28 passed**.
- Dashboard recovery, existing run-progress and all other frontend tests:
  **42 passed**; production build succeeds.
- Full backend regression: **1168 passed**, 2 dependency deprecation warnings
  in 734.29s. The last disappearing-record test was added after collection;
  it passes in the final 28-test targeted rerun. Current collection: 1169 tests.
- Initial restricted run could not supervise local test processes because
  macOS process inspection was denied (`PermissionError` launching `ps`). It
  was stopped and rerun with process-inspection permission, still offline.
- Frozen `schemas/` and `tests/fixtures/` were not modified. No live gate is
  signed off by these offline tests.

## Deployment / recovery still required

Restart the API and the single worker deliberately to load backend changes,
and refresh the dashboard. Reconnect Google ADC outside the application and
re-check Providers. Resolve the old ambiguous attempt using evidence before
resuming the run. No automatic retry, retroactive refund, budget increase,
generation, scheduling or publication is part of this repair.
