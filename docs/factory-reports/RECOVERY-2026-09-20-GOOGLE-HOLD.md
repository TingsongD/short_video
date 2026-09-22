# Approved service, Google and historical-hold recovery

User authorization (2026-09-20): restart services, reconnect Google, and
reconcile the historical $0.25 hold. The user completed Google's approval.
This does not authorize resuming generation, scheduling or publication.

## Services and authentication

- Previous API and worker processes were no longer running; port 8100 was free.
- Started the patched API and exactly one worker with the existing owned-service
  manager (API PID 30192; worker PID 30213). Health reports both available.
- Refreshed Google Application Default Credentials through Google's native
  sign-in flow. No passwords or authorization codes were collected in chat.
- Explicit readiness recheck reports `authenticated=true`, `reason=ok` for
  Google Vertex and audiovisual analysis, project `sentientweb1`, configured
  identity `david.dai@robanka.com`.
- New private rotating diagnostic files exist with mode 0600.

## Exact historical target

- Run: `auto-bbf59fdd645e4bdb` (paused at `video_analysis`).
- Attempt: `att:effect-42bf99b105395d074d9fb913ba9d9a95cecd70edf94270c7837fbad67730766b:0:1`.
- Reservation: `rsv:4054f3d9ad71465d`.
- Request hash: `f1d81cf673f1414cad54efcbd1c57eee4250c2712378307105cea3e2bce3f8b8`.
- Provider/model/task: `audiovisual_analysis` / `gemini-2.5-flash` / `analyze`.
- Local receipt: `data/factory/providers/analysis/sync-8cb5676994540c4e7c5953ca86230292/receipt.json`.
- The single 250,000-micro-dollar hold is applied to five applicable ceilings;
  those lines are not five separate confirmed charges.

## Reviewed evidence and limits

1. Durable events 5801–5803 bind this request and attempt: prepared at
   `2026-09-20T17:38:56.786592Z`, dispatch started at
   `17:38:56.789085Z`, and acknowledgment lost at `17:38:57.666881Z` with
   `{cause: loader_failed, class: ambiguous}`. There is no remote ID or
   recorded success. The job failed with the same local error.
2. Reviewed the pre-patch implementation at commit
   `24537397d2d71ec1fcaaae069b7740bd114cbcee`. These credential, synchronous
   adapter and Vertex-analysis files were unmodified at the beginning of the
   repair. Searching this implementation locates `loader_failed` only in the
   local Vertex credential loader/status wrapper, not in analysis response
   parsing or HTTP transport.
3. The recorded `analyze` path calls `analyze_media`, which makes one
   `_generate` call. In the historical `_generate`, `auth.bearer()` is evaluated
   while constructing the transport's arguments. A loader failure therefore
   raises before the analysis HTTP transport is invoked. The OAuth refresh
   itself is not an analysis request.
4. Reproduced that historical code in memory, using a fixture RefreshError and
   a transport counter with no network. Result: `loader_failed`, **zero analysis
   HTTP calls**. This is code-path evidence, not a provider billing receipt.
5. The existing unknown receipt was written before execution in that old
   implementation; its presence does not establish remote acceptance. The old
   adapter returns the existing receipt on replay instead of executing again.
6. Read-only Cloud Logging search for Vertex audit entries in
   `17:38:40Z–17:39:15Z` returned no entries; the project IAM policy returned no
   audit configurations. Logging completeness is unverified, including inherited
   configuration. **No-log absence is not evidence of no charge and is not the
   basis for release.**

## Scoped operator decision

Based on the request-bound local error and reviewed single-request code path,
resolve this specific attempt as `confirmed_no_effect` and release its
reservation through the existing audited operator services, in one transaction.
Do not add a retroactive `not_sent` receipt, fabricate a provider invoice, alter
ceilings or settled usage, or generalize this decision to other unknown errors.
The original receipt and error events remain intact.

Execution outcome: pending the guarded operator transaction. The run remains
paused; no generation retry is part of this recovery.
