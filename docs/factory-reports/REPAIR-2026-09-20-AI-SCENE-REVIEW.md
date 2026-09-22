# Source-grounded AI scene review and recovery choices

## Scope

Automate the routine source-scene inspection previously assigned to the user.
One sequential builder; existing unrelated edits preserved. No frozen schemas
or test fixtures changed. Generation and publishing authorities remain separate.

## Behavior

- Flagged scenes invoke a bounded correction pass and a separate verification
  pass through the configured audiovisual provider. Both requests include real,
  hash-verified source video/audio, strict structured responses and a binding to
  the exact candidate/source. Neither is a text-only self-approval.
- Corrections may alter descriptions, roles and audible transcript, not scene
  IDs or timing. Every scene needs complete verdicts and in-range evidence.
  No invented speech for silence or on-screen captions. Verification must agree
  exactly; disagreement pauses instead of entering a paid retry loop.
- Approved corrections atomically replace run observations, retain the original,
  refresh derived analysis, propagate corrected speech downstream and go through
  normal blueprint acceptance before generation. Records say `automated_ai`.
  Changed audible words invalidate stale source-language assumptions and flow
  through the existing budgeted translation stage before adaptation.
- The live status bar reports review progress and unresolved reasons. A paused
  review exposes Manual fix and Proceed anyways. The latter needs explicit
  named, exact-blueprint risk consent, recorded as `human_override`.
- Manual fix navigates without mutation. Accepted manual observations have an
  explicit adoption action which rebinds the run and refreshes derived analysis;
  it is recorded as `human_review`, without buying another review.
- Missing media, source drift, unknown provider outcomes, credentials, budgets,
  timing contracts and mandatory technical QC cannot be overridden. Stable jobs
  survive Resume/restarts; unknown attempts retain their holds and block resume.

## Verification

Offline provider-interface coverage exercises source-bearing requests, role
correction, verification disagreement, malformed evidence, source speech
consistency, repeat Resume, explicit overrides, manual repair adoption, unknown
paid outcomes and budget shortfall. The successful path renders real local A–D
exports using mocked paid providers; it creates no publications.

Dashboard coverage checks active/paused messages, read-only Manual fix,
exact-blueprint confirmation, disabled hard-gate override, and later pipeline
failures not hidden by a previous AI pass. Final counts and deployment outcome
are recorded below.

- Final focused backend scene-review/prevention tests: **32 passed** (51.67s),
  including corrected-language handoff and malformed response types.
- Provider, credential and receipt/accounting regressions: **71 passed** (1.19s).
- Dashboard: **52 passed**, TypeScript/Vite production build passed.
- Complete offline suite: **1,227 passed**, two dependency deprecation warnings,
  776.66s. The final response-shape hardening and corrected-language handoff
  were covered again by focused tests after full-suite collection (overlapping
  coverage; the counts are not additive).

## Live run and UI evidence

Run `auto-bbf59fdd645e4bdb`, seed `7udu-FBXoy8`, resumed through the dashboard
after an idle, identity-checked API/worker restart. Restart preserved exact
run, budget, reservation and attempt snapshots. No ceilings were raised.

At 20:55:07 UTC the run paused with `ai_scene_review_unresolved`. Correction
returned pass and proposed descriptions/roles and Chinese audible transcript
instead of English text overlays. Verification returned fail: it reported a
missing spoken question around 21.5s in b4. This is the verifier's finding, not
a separately established human transcription. No unverified candidate was
adopted and no video generation or scheduling followed the pause.

Receipted jobs:

- Correction: `effect-b4bccb36a03d64e99c2f01f29057fcc7e1e7211b28f60b8ec532cb6f8920457a:0`.
- Verification: `effect-77ea3086eb47dcc51db9b0984db6abbc2d856d99fa82aa975109216f0ea62fa9:0`.

Both provider attempts succeeded at the transport level; verification's
creative verdict failed. Their conservative $0.25 holds remain accounted for
(`rsv:df39e76dfe2c47e7`, `rsv:c02684000cd546da`), not invoice-confirmed charges.
Remaining approved headroom: **$24.00 and 5,000 voice credits**. Existing
unrelated holds were not touched. No new budget, retries or publications.

In-app browser verification confirmed active pass-1 status, the final failure
reason, Manual fix and Proceed anyways, the risk-confirmation form, and manual
navigation to the correct seed. The confirmation was cancelled without consent;
manual navigation did not resume the job. Zero active queue jobs after the pause.
No finals were produced, so final-video Drive delivery was not triggered.

Final safeguards loaded at 21:04 UTC: registered API PID 57619, worker PID
57756. Both earlier process identities were verified before stopping. The
paused run, all budgets, reservations and attempts were byte-for-byte unchanged
across this reload. Browser refresh reconfirmed the pause and both choices.

## Limits

Two calls to the configured model are independent requests, not independent
models, and can share mistakes. This is an automated quality assessment, not
proof of ground truth. Missing/corrupt or undecodable provider responses still
require the existing receipt-based reconciliation path. An exhausted review
does not automatically buy another attempt. Source media above the configured
analysis size ceiling is refused rather than silently downsampled.
