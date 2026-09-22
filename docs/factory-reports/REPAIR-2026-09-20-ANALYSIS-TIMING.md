# Analysis timing-response recovery — 2026-09-20

## Scope and evidence

The user approved patching the timing-response handling, reconciling the new
attempt, and retrying the existing run within its current limits. Scheduling
and publication remain unauthorized.

Run: `auto-bbf59fdd645e4bdb`, seed `7udu-FBXoy8`.
Attempt: `att:effect-b85441cb91a5904adbb7b075c765f7560468e6df7a48033a6179f303e2899d58:0:1`.
Reservation: `rsv:d37e1550136e4807` ($0.25).

Event 5821 records `malformed_analysis` with detail
`malformed_analysis: entry 14: end 3.0 <= start 3.0` at
`2026-09-20T18:45:01.049265Z`. The reviewed synchronous `analyze` path invokes
one Google request, receives a successful HTTP response with completed JSON
content, then fails local structural validation. This is not evidence of a
free/unsent request. The old wrapper omitted the field name, and no original
response was saved, so the evidence does **not** identify whether this was a
beat, passage, or optional word. The offline reproduction covers those cases
separately; it is not a replay of the missing provider payload.

## Repair

- Keep scene and passage bounds strict. Reject reversed/non-finite/out-of-range
  timestamps and invalid duration coverage. Frozen schemas/fixtures unchanged.
- At the Vertex boundary only, a zero-duration optional word invalidates that
  passage's optional word-alignment list, not its text or passage timing. Every
  other bound is checked first so this cannot hide another invalid word. An
  uncertainty note explicitly requires independent word alignment; no word
  duration is synthesized. Valid alignment is preserved.
- Supply verified duration and explicit positive-duration rules to the model;
  request passage-level transcription and leave word timing to the local
  speech aligner.
- Save private, redacted, attempt/request-bound `provider-response.json`
  evidence before content validation. Preserve response hash and usage metadata
  when supplied. Validation errors now include the failing field.
- Add an explicit operator-only reconciliation endpoint for this narrow
  completed-but-unusable synchronous analysis case. It atomically settles the
  full reserved estimate and closes the attempt as failed with outcome
  `completed_unusable`. It does not assert invoice confirmation, refund,
  remote cancellation, or successful analysis. It enqueues no retry.
- Reject unrelated providers/tasks/events, transport/auth failures and known
  remote operations. Failed reconciliation rolls back accounting. Preserve
  original receipts/events; stale reconciliation cannot reopen this resolved
  attempt. Existing unknown-outcome behavior elsewhere remains unchanged.
- Dashboard and backend recovery text explain the potentially billable result
  and evidence/settlement requirements before Resume, including older pauses.

## Validation and live outcome

Nineteen new offline backend cases cover the provider submission boundary,
timing guardrails, response retention/redaction, operator API, atomic refusal,
idempotent replay and recovery messages. The focused timing/auth run passes
38 tests, re-run after the stale-reconciliation guard was added. Dashboard:
44 tests and production build pass, including two new recovery-message cases.
Full offline suite: **1188 passed**, two dependency deprecation warnings,
786.45 seconds. The full-suite process collected before the final stale-
reconciliation assertion was added; the final focused 38-test run covers that
additional assertion and guard. Later local-recovery refinements are covered
separately below; this full-suite result predates those refinements.

A restricted-environment broad test run was interrupted after one local
owned-renderer timeout (57 passed). The same integration case passed with
process inspection permitted (19.18 seconds). No production service was
interrupted by that test cancellation. A browser reload of the rebuilt
dashboard confirms the new potentially-billable recovery message appears for
the existing paused run.

## Saved-response recovery refinement

The approved retry completed at Google but returned one empty transcript
placeholder (`text=""`, `words=[]`, `start_s=end_s=0`). Event **5843** binds
that rejection to attempt
`att:effect-92eb38c8c3332859eea13d2d9b573cc59d103a395abd6eacd5aa818aa15f8b4c:0:1`
and reservation `rsv:02a61fc8b71a4dc7`. The private response captured before
validation records HTTP 200, completed content, usage metadata, request hash
`f1d81cf673f1414cad54efcbd1c57eee4250c2712378307105cea3e2bce3f8b8`, and original
response hash `f4b79fbb4bb83807bcf364123c5dfc7bfaafc42d67299e9f0de74ade09a3e7a2`.

Dropping only that completely empty placeholder passes structural and
temporal validation: ten scenes tile the verified **45.281-second** source;
ten nonempty transcript segments remain unchanged. No scene bounds, speech
or duration were fabricated. An uncertainty note records the normalization.

The new operator-only `recover-analysis-response` API revalidates the saved
response against its attempt, immutable request and current source bytes,
settles the completed request at the full conservative estimate, and adopts
the analysis in one transaction. It leaves the run paused for explicit Resume.
It neither invokes a provider nor rewrites the original failed job/receipt.
Missing review evidence, source mismatch and invalid responses fail closed.

Also found: terminally resolved attempts retained dispatch-capacity slots.
Terminal resolution now releases remote-operation capacity only when the job
has no unfinished sibling attempts. Unknown and local-work holds are retained.
The response-recovery regression file now passes **29 offline cases**, including
these refusal, no-extra-request and capacity-preservation boundaries.

## Verified live outcome

- Latest offline integration batch: **144 passed**, two dependency warnings,
  328.67s. It covers timing/auth/incident recovery, APIs, scheduling, effect
  repairs, autoruns and application rendering. The final focused file passes
  **29 cases**, including two capacity-preservation cases added after that
  integration batch collected. `git diff --check` is clean.
- Restarted only the registered API and worker at 19:33 UTC. Current PIDs are
  86862 (API, port 8100) and 86922 (worker); health and heartbeat verified.
  Private logs contain the recovery-stage progression and review pause.
- Cleared stale dispatch slots only for the two already-resolved attempts,
  checking terminal status, reservation state and resolution events 5808/5832.
  Recovery closed the latest attempt and released its slot. The unrelated
  unknown attempt's dispatch hold remains untouched.
- Local recovery committed as audit event **5857** at 19:33:56 UTC. Saved
  evidence-file SHA256 is
  `9fa8e220385c78a969b3e06d114e0791d17ad3b9defb41dbb0a86369227a63d9`.
  Original receipt and provider response were not rewritten. No additional
  analysis request was sent during local recovery or subsequent Resume.
- Historical authentication hold `rsv:4054f3d9ad71465d` remains **released**.
  `rsv:d37e1550136e4807` and `rsv:02a61fc8b71a4dc7` are **settled** at $0.25
  conservative estimate each ($0.50 total, not confirmed invoices). Each is
  counted across applicable budget ceilings, not charged once per line.
  Run authority remains $25 / 5,000 credits; run budgets show $24.50 / 5,000
  available after these settlements.
- Resume advanced through analysis write-up/review to **Blueprint**, then
  correctly paused at 19:34:19 UTC: eight low-confidence scenes (b1,b2,b3,b4,
  b6,b7,b9,b10), plus b2's missing speech link. No flags were silently accepted.
  Browser verification shows the correct seed, live worker, **29% (5/17)**
  stage progress and the Analysis-review instruction.
- No experiment/final videos yet for this run; nothing scheduled or published.
  Next step requires reviewing the flagged blueprint, accepting it, then
  resuming. The finished-video Drive completion rule is not triggered yet.
