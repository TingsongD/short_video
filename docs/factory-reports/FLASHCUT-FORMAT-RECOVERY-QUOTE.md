# AVvVLM5b-mE — bounded request-format recovery

> Historical quote and recovery checkpoints, not new spending authorization.
> The run later completed; see [current status](FLASHCUT-CURRENT-STATUS.md).
> The unknown request described below remains preserved despite completion.

Prepared 2026-09-22 UTC for `auto-2c9de6ddf2e34d5c`.
The user approved fixing the compatibility issue and preparing a revised bounded
quote within the existing cumulative **$50** run ceiling. No historical budget,
attempt, reservation or completed video is modified by this recovery.

## Revised quote

Identity: `82472b6126d3306e29826e3e9ecae82897e71547a5862ec658a70a3aab120463`.

| Request | Maximum estimated reservation |
| --- | ---: |
| Correct completed whole-source answer | $0.184593 |
| Correct completed targeted-window answer | $0.352968 |
| Shared source-evidence clarification, only if needed | $0.184545 |
| **Maximum additional total** | **$0.722106** |

These are conservative usage estimates, not confirmed invoice charges. They
include source media, prompt/schema input bounds and at most 32,768 output
tokens per request with MEDIUM thinking. Each request is independently reserved
through the existing execution/budget system. The smaller overview must pass
before the window correction can be dispatched. The third request is optional,
not an automatic extra generation. No retries or further automatic extensions.

At preparation, previous held/ambiguous estimates total $1.298942. Adding every
new quoted request would bring that estimate to **$2.021048**, still part of the
existing $50 cap. Subsequent footage, speech and QC remain subject to their own
normal quotes and the same cumulative authority. The separate prepaid-TTS
allowance is unchanged; no subscription or overage is enabled.

## Compatibility change

The old provider schema had large candidate-ID enums, array bounds including
`maxItems: 0`, and numeric constraints. Google identifies schema complexity as
a possible source of HTTP 400 errors, but the exact rejected constraint is not
yet isolated. The new version uses a smaller shape-only schema and an
instructions-only prompt instead of repeating a conflicting JSON layout.

Reference: [Google structured-output guidance](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/capabilities/control-generated-output).

The application still checks every evidence ID, continuous cited video-window
coverage, ordered/positive timestamps, complete beat layout and creative-context
bindings. Simplifying the remote schema does **not** loosen those acceptance
checks. The new prompt/schema is versioned and part of each new request identity;
old request payloads and receipts retain their original version.

## Safety and verification

- Only returned HTTP 200/STOP answers with matching attempt/request/file hashes
  are eligible for new corrections. Unknown transport outcomes remain blocked.
- Activation requires the exact quote identity, an identified reviewer, a proven
  earlier HTTP 400 pre-acceptance rejection and unchanged source evidence.
- The supplementary plan is immutable, limited to three requests, and cannot
  reset the original clarification ledger or extend itself after a failure.
- Recovered/valid analysis is reused. PE, audio, Jev and old video work are not
  repeated. Unresolved charges are not refunded or marked settled.
- Consistent pre-deployment snapshot:
  `/private/tmp/factory-flashcut-acceptance.sAinMF/before-compact-recovery`.
  Zero active jobs and all 16 protected final hashes verified.
- Focused offline provider/accounting regressions, including the subsequent
  gap-evidence recovery checks: **94 passed**.
- Native-render, shared-clarification and budget-refusal end-to-end regressions:
  **3 passed in 251.05 s**. All provider and Drive calls were mocked; the native
  renderer actually produced the four local fixture finals.

## Scoped rollout and live verification

- Deployed while idle on 2026-09-22 at 05:32 UTC. Only the registered API and
  worker were restarted; the current run was resumed separately with the exact
  quote identity. Historical runs were not resumed.
- The first compact whole-source request was accepted and completed at
  05:33:29 UTC. Its returned analysis passed the unchanged application checks.
  This establishes compatibility for that payload, not every possible payload.
- The larger window request was also accepted, returning HTTP 200/STOP. Its nine
  observations pass the unchanged timestamp/citation checks, but it put two
  coverage-gap sentences in `essential_missing` instead of candidate IDs. The
  strict validator correctly paused the run; the request is not replayed and
  its accounting remains unresolved.
- A narrow local recovery recognizes only that precise gap-sentence grammar,
  retains the original text/ranges and response hashes in a separate immutable
  evidence bundle, and requires the already quoted full-source clarification.
  It does not drop the missing-evidence claims or mark the response complete.
  Unrecognized prose, invalid ranges, incorrect observations, missing receipts
  and uncertain transport outcomes remain blocked. Clarification must provide
  observed, source-cited coverage for every reported gap before proceeding.
- No new requests or quote extensions were added. The optional clarification
  remains at most one request, reserved at $0.184545. Production and delivery
  are not yet verified; offline tests do not establish completed delivery.

## Current outcome — 05:42 UTC

The shared clarification returned **HTTP 500 INTERNAL**, with the provider
message "Internal error encountered." No usable response or remote operation
ID was returned. The executor correctly records an **unknown** attempt and
preserves reservation `rsv:4f0db240ebca446b`; it must not be automatically
resubmitted, refunded, marked successful or counted as resolved clarification.

- Request job: `effect-418af0c97970d6dba630b8455c4abb3e146600b624d87a742328b82929751e3e:0`.
- Current run remains paused at `video_analysis`; no new production draft,
  footage, TTS or finals have been created.
- Aggregate held/ambiguous estimates are **$2.021048**, leaving $47.978952
  within the unchanged $50 run cap. These are not confirmed invoice amounts.
- The three-request supplementary plan is exhausted. Do not reset it or replay
  the unknown request. Any further recovery must first inspect existing evidence
  and preserve the original operation/accounting identities.
- Gap-format recovery integration: **1 passed in 28.87 s**, with mocked paid
  calls. The earlier sandbox-restricted test was interrupted; it is not counted
  as a pass. The successful rerun had required local process/localhost access.
- HTTP-500 status/no-replay integration: **1 passed in 25.06 s**. A subsequent
  Resume retains the same unknown attempt and makes no additional provider call.
  Final focused regression rerun: **94 passed in 5.34 s**; diff checks passed.
- At 05:46 UTC, the status-message patch was deployed while idle. API/storage
  health passed; exactly one registered worker (PID 84110) is running. The run
  was **not resumed**. The dashboard now explicitly displays the HTTP 500,
  unknown outcome and no-retry instruction; updating its message created zero
  jobs, attempts or reservations. Service log permissions remain owner-only.
- Pre-gap deployment snapshot verified zero active jobs and all 16 historical
  final hashes. Post-change comparison found all 3,135 old records, 645 jobs,
  408 attempts, 505 reservations, 2,676 reservation lines, 236 artifacts and
  182 effect bindings unchanged. The five historical budget differences are
  the earlier explicit run authorization, not changes from this recovery.

**Fixed:** accepted compact payloads; guarded local format recovery; bounded
quotation and no-replay checks. **Unverified/blocked:** successful shared
clarification and the complete live A/B/C/D generation/Compare/Drive path.
