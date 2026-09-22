# Remaining QA issues — safe patch report

Date: 2026-09-21. Scope: six approved functional/security findings, future runs
only where behavior changes. No paid generation, publishing, ceiling increases,
historical accounting reconciliation or changes to the twelve completed finals.

## Implementation

1. **Private, bounded logs.** API/worker access and error output, including
   exception rendering, is sanitized before writing. Query values, URL userinfo,
   credential headers and credential values are removed. Log-only redaction is
   separate from domain payload validation so seed URL queries and ordinary copy
   remain usable. Each service holds an exclusive writer lock; active logs and
   three rotations are owner-only, at most 4 MiB each. A repository-owned
   WhisperX `serviceCommand` wrapper preserves the existing environment, model,
   CPU/int8 settings, endpoint and health protocol without editing dependencies.
   The explicit-file cleanup command defaults to a dry run, refuses open/linked
   files, atomically sanitizes and records counts, and makes no raw secret backup.

2. **Safe session recovery.** Only an explicit pre-handler `403 csrf` triggers
   one reconnect and retry. Concurrent failures share the session refresh; late
   failures reuse the refreshed token. Body/file, revision and idempotency key
   remain identical. Timeouts, other authorization failures and conflicts are
   not automatically replayed. Failed reconnection explains how to recover.

3. **Source timing.** New Auto runs persist `source_timing.v1`. Run-owned evidence
   is keyed to source bytes, transcript, language and policy. Invalid ordering,
   bounds, missing text coverage and suspiciously long words trigger at most two
   persisted local cropped-audio attempts per passage. Interrupted attempts are
   consumed. Replacements must preserve spoken words and pass validation.
   Passage-only fallback is allowed only if one beat contains the whole passage;
   otherwise a technical pause identifies the passage. UI/API expose attempts
   and evidence quality. Shared historical evidence is never overwritten, scene
   review stays removed, and final captions retain replacement-speech alignment.

4. **Scoped refresh and waiting.** Active status polls at five-second cadence;
   idle and detailed fallbacks use 30 seconds. Hidden tabs suspend polling;
   returning refreshes immediately. Tab entry, actions and coalesced events load
   only the relevant collections plus shared navigation/history resources.
   Overlapping requests are deduplicated and old-selection responses discarded.
   Last successful refresh is visible. Provider unfinished/capacity/backoff
   outcomes remain deferred, not blocked; queue labels explain the wait. Retry
   budgets, scheduler delays and unknown-outcome protections are unchanged.

5. **Future delivery tracking.** New experiments carry
   `delivery_tracking=verified_receipts.v1`. The external-file reconciliation
   action verifies current final QC/revision, configured account/destination,
   explicit file ID, name, size and MD5 without uploading. Ambiguity or unavailable
   checks leave the intent unresolved. Verified status, external provenance and
   the delivery-only queue transition commit together. Current final identity
   is checked again in that transaction to reject a draft edit during remote
   verification. External-only intents cannot be converted into upload retries.
   Creative approval and cleanup remain separate. Historical experiments cannot
   use the new action; no historical receipt or queue status is backfilled.

6. **Budget selection.** Responses include classification, retirement and
   selection eligibility. User selectors offer reusable non-retired budgets;
   accounting separately shows internal authorization ceilings. Backend create,
   resume and approval boundaries reject internal/retired budgets while preserving
   acknowledged idempotent replays. Internal enforcement, amounts, reservations,
   historical holds and do-not-retry decisions are unchanged.

## Verification and rollout

All six findings are **fixed and rolled out locally**. Verification:

- Complete final offline backend suite: **1,349 passed in 924.18s**.
- Frontend: **64 passed** across 12 files; production TypeScript/Vite build passed.
- Final delivery/race/automatic-workflow set: **31 passed in 151.47s**.
- Final API/logging set: **31 passed in 9.13s**.
- `git diff --check`, Python/shell syntax checks and database integrity passed.

Test-driven public-boundary regressions cover concurrent recovery/upload identity, bounded timing
repair/restart/fallback, scoped polling/stale responses, external verification
ambiguity/stale revisions, log redaction/rotation/writer ownership, and backend
budget refusal. Inert browser fixtures have been inspected; their controls
cannot start real jobs. Frozen schemas and fixtures were not changed.

The tests also exposed and fixed three edge cases: a duplicate service writing
structured logs before acquiring ownership, a draft changing during remote
verification, and waiting-event bursts unnecessarily refreshing details.

Before rollout, read-only fingerprints cover all application records, jobs,
artifacts, budgets, reservations and lines, attempts, effect bindings, final
bindings and the bytes of all twelve final files. Heartbeat/operational events
are deliberately not treated as immutable historical accounting. The audit
utility is `scripts/factory-qa-audit.py`. No database restore is part of rollout
or rollback; newer activity must never be overwritten by an old snapshot.

The final before/after audit is identical for all eight fingerprinted tables,
the twelve final bindings and all twelve final files. Preserved counts:
2,525 application records, 500 jobs, 174 artifacts, 86 budgets, 444 reservations,
2,321 reservation lines, 347 attempts and 123 effect bindings. The twelve legacy
delivery-only jobs remain `awaiting_review`; no delivery record was backfilled.
Record digest: `b66a8e3c8bd5fabcfc262ce1f2b6a1a0a3e05299932cc5a558d7bd60919f5a7f`.
Job digest: `513bca728a000d696c053a6ef645f6106904aa6a2c04f991934e375870a9a449`.
Final-binding digest: `cb280131b190232cb04f6c1a037c75dbd7a4311832b3319d59ec046ef433bce5`.

Rollout drained the empty queue and stopped only the owned API, factory worker
and WhisperX helper. The broad all-services launcher was deliberately not used
after its safety check rejected the shared-service scope. Targeted persistent
launches restored the API and exactly one worker using absolute repository
paths, with matching pidfiles. API/storage/worker health passes; dispatch has
its original undrained state. WhisperX health matches the original protocol,
service/model/version/device/compute/batch settings. The live dashboard shows
`Mode: live`, `Worker: running`, preserved completed runs and last-refresh time.
Other shared media/render programs were not stopped. No database rollback or
new provider work was performed.

Cleanup first ran dry, then verified the relevant file handles were closed:

- Historical WhisperX `program.log`: **13 lines sanitized**; `install.log`:
  zero sensitive-pattern changes, owner-only permissions applied.
- Historical API console log: **7,235 lines sanitized**, retained as a private
  compressed diagnostic archive, `.run/api-legacy-qa-patch.log.gz` (668,623 bytes).
  The active API log restarted empty and now uses bounded rotation.
- Worker console log was empty; owner-only permissions applied. Structured
  diagnostic logs retain their safe error codes and diagnostic context.
- Dry-run rechecks report zero further changes to the four cleaned logs; the
  archive passes the same check. Original sensitive values are intentionally
  not retained in backup copies.
- Live health and rejected-path requests containing a clearly fake query value
  returned 200/404; neither API nor WhisperX logs retained that value. Current
  application logs, the new WhisperX launcher log, the historical helper logs,
  and the repository runtime-worker log are mode 0600. The helper's supported
  wrapper is confirmed by its actual process command.
- The inert browser tab/server were closed; temporary port 5191 is free. The
  user's live dashboard on 8100 remains open and running.

## Deferred / not claimed

- Hypit's Node `module.register()` deprecation warning remains a separate
  compatibility task; it is not suppressed.
- Live paid-provider acceptance, creative quality and latency/cost claims need
  fresh authorization. Offline fixtures do not prove live provider behavior.
- Historical delivery statuses and unresolved spending evidence stay exactly
  as recorded. This patch neither reconciles old charges nor retries old work.
- Redaction is not evidence of compromise. Google credentials are not rotated
  automatically; no password, OAuth code or token is copied into this report.
