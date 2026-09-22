# Restarted QA: accounting reconciliation

## Authorization and scope

The user authorized unlimited spending for exactly three restarted QA rounds and requested historical accounting reconciliation and safe reactivation. This is not authorization to fabricate provider outcomes, erase historical charges, or replay uncertain requests.

## Verified local evidence

The active database and the preserved snapshot at `data/factory-reset-backups/20260920T224757Z/factory/factory.db` contain identical financial rows: 50 budgets, 97 reservations, 286 reservation lines, and zero ledger imports. The active jobs and artifacts were cleared by the backed-up reset; historical attempts and receipts remain in the archive.

Three ambiguous analysis reservations remain, each estimated at USD 0.25 (USD 0.75 total, not confirmed charges). Their lines count against multiple ceilings and must not be added together as separate charges:

| Reservation | Evidence | Result |
| --- | --- | --- |
| `rsv:e89ddf2612114e95` | Historical `malformed_analysis`; unknown local receipt; no saved provider response found in the expected attempt folder | Unresolved; no refund or settlement asserted |
| `rsv:739adb527dd44595` | Transport failure; unknown local receipt and reconciliation event 5985 | Unresolved; local `sync-` ID is not proof of a Google operation |
| `rsv:cb39471f2b464560` | Saved HTTP 200 response, `MAX_TOKENS`, event 6007, response SHA-256 `6a22e521bda179345f7e55c130eb98278bcf70ea2ba6358a430d61fa56de3c9d` | Returned incomplete content; actual charge remains unverified |

An additional historical generation attempt for `rsv:470de0dc203b4e32` remains `unknown` although its reservation was previously released. Its event records `authority_required`; the existing release explanation relies on absence of a remote ID. That absence alone is not provider proof of no charge. This review did not change the historical release or replay the request.

## External check

A read-only Google Cloud Logging request succeeded with HTTP 200 for the configured project, filtering Vertex audit entries from 2026-09-20 02:00 through 22:30 UTC. It returned zero entries and no next page. Authentication worked for that request. Missing log entries do not prove no execution or no charge, and this check is not a billing statement.

## Current disposition

Spending approval is now present. Accounting verification is incomplete. The existing `restore_pending` activation lock is retained: the restore activation interface requires an evidence-backed external financial audit, which has not been established. No historical hold was released, no uncertain operation was resubmitted, and no new paid request was sent during this investigation.

Provider billing/usage evidence or support confirmation is needed to establish the unresolved historical outcomes. Archived connection configuration and route qualifications must also be validated before new production: the fresh data root does not inherit them automatically. All three restarted rounds and their twelve final outputs remain pending. This report does not claim QA completion.

## Subsequent user-directed operational closure

The user explicitly requested skipping historical billing investigation, closing the old requests, and never retrying them. Recorded `historical_requests_closed_no_retry` in the active database metadata and audit events, identifying all four archived nonterminal attempts. The active database has zero jobs and attempts; archived work was not restored or enqueued.

Removed only the manual `restore_pending` lock introduced by the backed-up reset. This is operational closure, not verified restore activation or evidence of provider billing outcomes. All 50 budgets, 97 reservations and 286 reservation lines remain unchanged, including the three ambiguous USD 0.25 estimates. The startup dispatch gate now returns `allowed: true`. Other approval, budget, provider-readiness and duplicate-request checks remain in place. Do not restore or replay the archived requests. No paid generation was submitted by this closure action.

## Provider settings restoration and validation

On the user's explicit approval, restored only `connections.json` and the two original `capabilitysnapshot` records. Did not restore old execution state, jobs, attempts, or media. Configuration bytes matched the archive; qualification expiry dates were preserved, not extended. Restarted the owned API and worker (PIDs 89599 and 89662).

The live readiness endpoint reported authenticated and qualified for audiovisual analysis, Google Vertex, Jimeng Canvas, ElevenLabs and generated music. A separate read-only ElevenLabs subscription request returned HTTP 200 with 45,195 used of 90,000 credits (44,805 remaining at this check). API/storage were healthy and the worker heartbeat current. The active database still had zero jobs, attempts and artifacts, passed integrity checking, and the startup dispatch gate allowed new work. No generation was submitted. These are readiness checks, not proof of successful new generation or sufficient credits for all twelve outputs; new run quotes and funding checks remain required.
