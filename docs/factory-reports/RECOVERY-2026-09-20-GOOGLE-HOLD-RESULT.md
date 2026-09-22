# Approved recovery — execution result

Completed on 2026-09-20 under the user's explicit authorization to restore
services, reconnect Google, and reconcile the historical $0.25 reservation.

## Confirmed outcome

- API PID 30192 and exactly one worker, PID 30213, are running. Final health
  check reports API/storage `ok` and a current, available worker heartbeat.
- After the user completed native Google approval, an explicit non-billable
  readiness refresh reported `authenticated=true`, `reason=ok` for both Google
  Vertex and audiovisual analysis, using the configured identity
  `david.dai@robanka.com` and project `sentientweb1`.
- Reservation `rsv:4054f3d9ad71465d` is `released`. This restores the single
  $0.25 hold across its applicable ceilings; it is not a provider refund or
  five separate charges. No ceilings or settled usage were increased.
- Existing operator services recorded the attempt's `confirmed_no_effect`
  resolution and reservation release in one guarded transaction. Attempt
  `att:effect-42bf99b105395d074d9fb913ba9d9a95cecd70edf94270c7837fbad67730766b:0:1`
  is now terminal (`failed`); audit event 5808, `human_resolution`, is dated
  `2026-09-20T18:36:12.520677Z`.
- Run `auto-bbf59fdd645e4bdb` remains **paused at video analysis**. Final
  verification found no runnable/in-progress queued jobs. No generation retry,
  paid generation request, scheduling or publication was performed.

## Evidence preservation

The pre-execution evidence snapshot is
`docs/factory-reports/RECOVERY-2026-09-20-GOOGLE-HOLD.md`. Its SHA-256 is
`f17987c31c10410624210ecbe77a36e43727d129e1b589930f949e99fd5998ac`.
That digest is recorded in the resolution evidence and was verified after the
transaction. The snapshot remains unchanged; this separate result supersedes
its pending-execution status without altering the evidence.

The release is based on the specific request-bound local error and reviewed
historical code path, not absent Cloud logs or missing remote identifiers.
The original receipt remains `unknown`, without a fabricated `not_sent`
marker; original events 5801–5803 remain intact. The appended operator
resolution is the authoritative reconciliation record for this attempt.
