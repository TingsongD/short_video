# Viral Video Factory — Module Progress Tracker

**Version:** 2.1 · **Initialized/updated:** 2026-09-16 · **State:** implementation started 2026-09-16 on `feat/factory`; F00 baseline recorded (344-test green baseline verified). Authoritative acceptance records: legacy `docs/gates.md` (G0 signed; G1–G12 pending live) and this tracker — neither signs the other.

Use the [main handover](viral-video-factory-handover.md), [detailed module guide](viral-video-factory-implementation-modules.md) and [validation runbook](viral-video-factory-validation-runbook.md) together. Update this tracker during implementation with actual evidence; preserve the original requirement and explain deviations.

## Status rules

- **Engineering:** `planned`, `in_progress`, `passed`, `blocked`. A pass requires implemented scope, targeted tests and full offline suite evidence for the integrated source revision.
- **Offline manual:** `not_run`, `in_progress`, `passed`, `failed`, `blocked`. Complete the module's applicable offline manual scenarios and human review. A live-only case does not belong in this column.
- **Live:** `pending`, `in_progress`, `qualified`, `failed`, `blocked`, `not_applicable`. Qualification must name the exact account/project, provider/model/location/input mode and tested behavior without exposing credentials. Optional routes can remain disabled with a reason.
- An unavailable live dependency does not undo a passed engineering module. It does prevent enabling that unqualified capability. Do not mark a module fully accepted unless all gates required by the intended release scope have passed.
- Add owner, started/completed timestamps, source revision and actual evidence links as work proceeds. Default report location is `docs/factory-reports/Fxx.md`; create the report before linking it. Store large/private evidence in ignored QA/production data.
- If a regression invalidates evidence, change the affected status and list dependent modules needing revalidation. Preserve old evidence rather than editing history to look green.
- Intermediate milestones can use an explicitly validated sub-scope of a module, but its engineering status stays `in_progress` until all required module checks pass. Track the remaining scope in its report; a four-video demonstration does not complete all 36 modules.

## Acceptance ownership and working instructions

**G0–G12 govern the legacy pipeline and remain pending or signed independently in [gates.md](gates.md). F00–F35 govern the new factory. Neither system automatically completes the other.** Shared evidence must identify the precise common criterion, source revision and limits before either gate owner can use it. Existing scoped production evidence remains valid even while an aggregate legacy gate is pending.

Keep gate statuses in their authoritative documents and cross-link them from `PROGRESS.md`; do not maintain a second mutable copy here. F00 adds reciprocal scope pointers. This factory uses the single-builder workflow; the historical swarm ownership/write-partition/branch rules are superseded for this assignment. F00 must make that scope explicit in the instruction files, retaining the applicable contract, test, secret and delivery rules. See [main Section 2.3](viral-video-factory-handover.md#23-working-instructions-and-acceptance-ownership).

## F00 entry checklist from the review

The default checkpoint, runtime-data and authorization decisions are defined in [main Sections 2.4–2.5](viral-video-factory-handover.md#24-repository-checkpoint-and-runtime-data-policy). These rows are work for the implementing engineer, not actions completed by this documentation revision.

| Entry requirement | Evidence required | Status |
| --- | --- | --- |
| Record assigned offline implementation scope | Task/scope reference; no duplicate permission request where already explicit | not_run |
| Inventory tracked/untracked work | HEAD, branch, diff hash and manifest; inspect `LONGFORM_PLAN.md` deletion | not_run |
| Establish reviewed source checkpoint | Separate code/test and documentation commits; preserve unrelated work; record isolated worktree if used | not_run |
| Establish actual baseline | Fresh offline suite result and frozen-file hashes | not_run |
| Protect runtime financial state | Ledger backup/hash, tested ignore policy, `.gitkeep` preserved and no private runtime data staged | not_run |
| Clarify instruction/gate scope | Scope banners, reciprocal G/F links and original states preserved | not_run |
| Preserve configuration behavior | Environment > `.env` > TOML regression evidence | not_run |
| Plan R0/R1 from reuse | Component inventory, bounded first-export scope and estimate with explicit uncertainty | not_run |

## Review defects and capability gates

| Finding | Implementation owner | Required validation / limit |
| --- | --- | --- |
| Active Viral Outliers path is follower-only; old YouTube baseline math already exists | F10 | Test all selection modes through actual service/saved plans with fake transport; cohort evidence required |
| Optional uploader sends local path without required account or durable request handling | F31 | Inspect uploaded bytes/URL, account/platform fields, idempotency and async recovery before automated publishing |
| Analytics uses inappropriate reach metric names and unavailable baseline `0.0` | F32 | Correct report queries and unknown-value adapter; retain frozen legacy contracts |
| Runtime ledger is untracked and not ignored in reviewed snapshot | F00, F05, F30 | Preserve/ignore/back up; migrate and restore without duplicate accounting or restored spending headroom |
| Historical balance and approvals can be misread as current state | F00, F05, F16, F17, F35 | Date observations; distinguish current funds, credentials, scope and remaining authority; initial engineering stays zero-spend |

These live-connector defects do not block the independent offline foundation or the local-media production slice. Keep affected live capabilities disabled until their own gates pass.

## Module checklist

Dependencies below define implementation prerequisites, not permission to spend. Tests use fake transports until the corresponding live scope is valid. The main module order is a valid topological order; modules with independent prerequisites can be developed separately if the project later authorizes that working arrangement.

| Module | Prerequisites | Engineering | Offline manual | Live | Owner / evidence / blocker |
| --- | --- | --- | --- | --- | --- |
| [F00 — Baseline and engineer onboarding](viral-video-factory-implementation-modules.md#f00) | None | passed | in_progress | not_applicable | Devin; rev `13a5d51`+F00 commit; [report](factory-reports/F00.md); M01–M04 agent-verified, human sign-off pending |
| [F01 — QA harness, deterministic fixtures and fake providers](viral-video-factory-implementation-modules.md#f01) | F00 | passed | in_progress | not_applicable | Devin; [report](factory-reports/F01.md); 25 tests green in 369-suite; M01–M04 agent-verified |
| [F02 — Factory contracts and immutable revisions](viral-video-factory-implementation-modules.md#f02) | F01 | passed | in_progress | not_applicable | Devin; [report](factory-reports/F02.md); 35 tests green in 404-suite; M01–M04 agent-verified |
| [F03 — SQLite store and migrations](viral-video-factory-implementation-modules.md#f03) | F02 | passed | in_progress | not_applicable | Devin; [report](factory-reports/F03.md); 15 tests green in 419-suite; M01–M04 agent-verified |
| [F04 — Artifact registry, media intake and provenance](viral-video-factory-implementation-modules.md#f04) | F03 | passed | in_progress | not_applicable | Devin; [report](factory-reports/F04.md); 16 tests green in 435-suite; M01–M04 agent-verified |
| [F05 — Prices, budgets, approvals and reservations](viral-video-factory-implementation-modules.md#f05) | F03 | passed | in_progress | not_applicable | Devin; [report](factory-reports/F05.md); 15 tests green in 450-suite; M01–M04 agent-verified |
| [F06 — Dependency scheduler, capacities and leases](viral-video-factory-implementation-modules.md#f06) | F05 | passed | in_progress | not_applicable | Devin; [report](factory-reports/F06.md); 13 tests green in 463-suite; M01–M04 agent-verified |
| [F07 — Submission recovery and retry policy](viral-video-factory-implementation-modules.md#f07) | F06 | passed | in_progress | not_applicable | Devin; [report](factory-reports/F07.md); 16 tests green in 479-suite; M01–M04 agent-verified |
| [F08 — Events, timing and observability](viral-video-factory-implementation-modules.md#f08) | F06, F07 | passed | in_progress | not_applicable | Devin; [report](factory-reports/F08.md); 11 tests green in 490-suite; M01–M04 agent-verified |
| [F09 — Seed registry and source acquisition](viral-video-factory-implementation-modules.md#f09) | F04, F05 | passed | in_progress | not_applicable | Devin; [report](factory-reports/F09.md); 23 tests green in 513-suite; M01–M04 agent-verified |
| [F10 — Outlier discovery and baseline evidence](viral-video-factory-implementation-modules.md#f10) | F09, F05 | passed | in_progress | not_applicable | Devin; [report](factory-reports/F10.md); 16 tests green in 529-suite; M01–M04 agent-verified |
| [F11 — Shopify product and media snapshots](viral-video-factory-implementation-modules.md#f11) | F04, F05 | passed | in_progress | not_applicable | Devin; [report](factory-reports/F11.md); 14 tests green in 543-suite; M01/M03/M04 agent-verified, M02 awaiting human verdict |
| [F12 — Reference analysis and blueprint review](viral-video-factory-implementation-modules.md#f12) | F09, F05, F06 | passed | in_progress | pending | Devin; [report](factory-reports/F12.md); 12 tests green in 555-suite; M03/M04 agent-verified, M01/M02 awaiting human verdict |
| [F13 — Reusable format and template authoring](viral-video-factory-implementation-modules.md#f13) | F12 | passed | in_progress | not_applicable | Devin; [report](factory-reports/F13.md); 17 tests green in 572-suite; M02–M04 agent-verified, M01 awaiting human verdict |
| [F14 — Experiment, control and treatment planning](viral-video-factory-implementation-modules.md#f14) | F11, F12, F13, F05 | passed | in_progress | not_applicable | Devin; [report](factory-reports/F14.md); 11 tests green in 583-suite; M02–M04 agent-verified, M01 awaiting human verdict |
| [F15 — Shared generation contract and provider routing](viral-video-factory-implementation-modules.md#f15) | F14, F05, F07 | passed | in_progress | not_applicable | Devin; [report](factory-reports/F15.md); 16 tests green in 599-suite; M02–M04 agent-verified, M01 awaiting human verdict |
| [F16 — Official Jimeng Canvas adapter](viral-video-factory-implementation-modules.md#f16) | F15 | passed | in_progress | pending | Devin; [report](factory-reports/F16.md); 17 tests green; M02–M03 agent-verified, M01 + M04(live) awaiting human verdict |
| [F17 — Google Vertex video adapter](viral-video-factory-implementation-modules.md#f17) | F15 | passed | in_progress | pending | Devin; [report](factory-reports/F17.md); 20 tests green in 636-suite; M02–M03 agent-verified, M01 + M04(live) awaiting human verdict |
| [F18 — Product, presenter and outfit references](viral-video-factory-implementation-modules.md#f18) | F11, F14, F16 | passed | in_progress | pending | Devin; [report](factory-reports/F18.md); 11 tests green in 647-suite; M02–M04 agent-verified, M01 awaiting human verdict |
| [F19 — TTS, speech fitting and alignment](viral-video-factory-implementation-modules.md#f19) | F14, F07 | planned | not_run | pending | Unassigned; no evidence yet |
| [F20 — Music, sound and shared mix](viral-video-factory-implementation-modules.md#f20) | F19 | planned | not_run | pending | Unassigned; no evidence yet |
| [F21 — Unique-work production plan and asset graph](viral-video-factory-implementation-modules.md#f21) | F06, F15, F18, F19, F20 | planned | not_run | not_applicable | Unassigned; no evidence yet |
| [F22 — Hypit composition compiler and asset binding](viral-video-factory-implementation-modules.md#f22) | F13, F14, F21 | planned | not_run | not_applicable | Unassigned; no evidence yet |
| [F23 — Render execution and output retrieval](viral-video-factory-implementation-modules.md#f23) | F22 | planned | not_run | not_applicable | Unassigned; no evidence yet |
| [F24 — Technical, creative and changed-region QC](viral-video-factory-implementation-modules.md#f24) | F23, F14 | planned | not_run | pending | Unassigned; no evidence yet |
| [F25 — Verified Google Drive delivery](viral-video-factory-implementation-modules.md#f25) | F24 | planned | not_run | pending | Unassigned; no evidence yet |
| [F26 — Process ownership and resource cleanup](viral-video-factory-implementation-modules.md#f26) | F25 | planned | not_run | not_applicable | Unassigned; no evidence yet |
| [F27 — Application API and local security](viral-video-factory-implementation-modules.md#f27) | F08, F14, F21, F24, F25, F26 | planned | not_run | not_applicable | Unassigned; no evidence yet |
| [F28 — Dashboard seed, planner and budget screens](viral-video-factory-implementation-modules.md#f28) | F27 | planned | not_run | not_applicable | Unassigned; no evidence yet |
| [F29 — Queue, comparison, review and Studio feedback UI](viral-video-factory-implementation-modules.md#f29) | F28 | planned | not_run | not_applicable | Unassigned; no evidence yet |
| [F30 — Local installation, services and backup/restore](viral-video-factory-implementation-modules.md#f30) | F29 | planned | not_run | not_applicable | Unassigned; no evidence yet |
| [F31 — Manual and authorized automated publishing](viral-video-factory-implementation-modules.md#f31) | F27, F25 | planned | not_run | pending | Unassigned; no evidence yet |
| [F32 — Analytics readback and coverage](viral-video-factory-implementation-modules.md#f32) | F31 | planned | not_run | pending | Unassigned; no evidence yet |
| [F33 — Experiment decisions and learning library](viral-video-factory-implementation-modules.md#f33) | F32 | planned | not_run | not_applicable | Unassigned; no evidence yet |
| [F34 — Failure drills and performance qualification](viral-video-factory-implementation-modules.md#f34) | F30, F33 | planned | not_run | not_applicable | Unassigned; no evidence yet |
| [F35 — Funded pilot, release and engineer handoff](viral-video-factory-implementation-modules.md#f35) | F34 | planned | not_run | pending | Unassigned; no evidence yet |

## Live qualification scopes

These are planned gates. Historical evidence can be linked after checking its precise scope; it does not automatically qualify new adapter code, changed models or untested reference modes.

| Module | Evidence required before enabling the corresponding live behavior |
| --- | --- |
| F09 | Selected source-acquisition route |
| F10 | Funded Viral Outliers research |
| F11 | Authorized read-only Shopify import |
| F12 | Selected audiovisual analysis mode |
| F16 | Exact Canvas model and input mode |
| F17 | Exact Vertex model, location and input mode |
| F18 | Generated-reference route, if enabled |
| F19 | Selected speech/voice/alignment routes |
| F20 | Generated music route, if enabled |
| F24 | Actual generated product/presenter/speech QC |
| F25 | Verified authorized Drive upload |
| F31 | Authorized publication or verified manual post |
| F32 | Real due readback and coverage |
| F35 | Enabled live release capabilities and real horizons |

For F18/F20, a manual/imported-reference or soundtrack route may satisfy the selected release without enabling generated media. Record that choice and leave the generation route disabled. F16/F17 qualification is per mode: one provider can be enabled while the other remains pending. F24's live creative proof can be collected during F35's funded experiment. F35-M03 waits for actual publication/analytics scope and elapsed horizons; documenting a pending gate is not a passed learning test.

## Incremental delivery milestones

Follow the detailed milestone boundaries in [main Section 14.2](viral-video-factory-handover.md#142-sequenced-delivery-plan). These milestones expose useful progress before full application acceptance; they do not replace the module or release gates.

| Milestone | Demonstration | Status | Evidence / remaining scope |
| --- | --- | --- | --- |
| R0 | Reviewed baseline and durable zero-spend foundations | not_run | — |
| R1 | Four real local fixture exports, controlled differences, restart, fake verified delivery and owned cleanup | not_run | — |
| R2 | Local operator dashboard and service/backup recovery | not_run | — |
| R3 | Qualified, funded four-final production with real Drive verification | not_run | — |
| R4 | Authorized/manual posts, actual due analytics and reproducible learning | not_run | — |

F10 discovery can be deferred outside R1's production dependency chain. Record accepted partial interface scope and leave unfinished modules open. Execute J01/J03/J04 when ready rather than deferring integration checks until F34. R3 may precede R4's live posting/readback horizons, while still requiring the production-relevant recovery and budget checks.

## Phase exits

| Phase | Modules | Required demonstration | Status | Evidence |
| --- | --- | --- | --- | --- |
| P0 | F00 | Baseline, version/frozen inventory and restore convention | not_run | — |
| P1 | F01–F08 | Safe durable fake execution, budgets, recovery and timing | not_run | — |
| P2 | F09–F14 | Source/product evidence, accepted blueprint and four plans | not_run | — |
| P3 | F15–F20 | Two fake provider routes plus accepted references and fitted audio | not_run | — |
| P4 | F21–F26 | Four real local fixture exports, fake delivery and owned cleanup | not_run | — |
| P5 | F27–F30 | Usable local app, background worker and verified restore | not_run | — |
| P6 | F31–F33 | Correct fake publication, readbacks and decisions | not_run | — |
| P7 | F34–F35 | Integrated failure drills plus scoped live release evidence | not_run | — |

## End-to-end journey checklist

Use the runbook's exact fixture, numerical and evidence requirements. An offline journey and a funded journey have different allowed effects.

| Journey | Gate | Status | Evidence / pending reason |
| --- | --- | --- | --- |
| J01 | Offline seed → four fixture outputs and fake verified delivery | not_run | — |
| J02 | Long source → four 5,091-frame outputs | not_run | — |
| J03 | Worker crash and recovery without duplicate effects | not_run | — |
| J04 | Both fake video routes, budgets and eligible fallback | not_run | — |
| J05 | Each enabled live provider/model/input-mode qualification | not_run | — |
| J06 | Funded real seed → four accepted, delivered, cleaned finals | not_run | — |
| J07 | Authorized public/manual posts → real due readbacks and decision | not_run | — |
| J08 | Browser/service/backup recovery and no duplicate effects | not_run | — |

## Release summary — fill only from evidence

| Field | Current value |
| --- | --- |
| Release/source revision | Not implemented |
| Reviewed repository checkpoint | Pending F00; preserve unrelated work and resolve the observed deletion explicitly |
| Engineering gate | Pending |
| Live production gate | Pending |
| Learning-loop gate | Pending |
| Enabled Canvas models/input modes | None qualified for the new factory adapter yet |
| Enabled Vertex models/input modes | None qualified for the new factory adapter yet |
| Historical evidence | Existing Canvas workflow and Vertex text-only pilot; see main handover for limits |
| Frozen legacy contracts preserved | Must verify at implementation baseline and release |
| Current live spending authorization | Must resolve exact remaining scope before a funded test; do not assume historical ceilings remain |
| Historical account balances | Dated observations only; no fresh balance check performed by this revision |
| Legacy runtime ledger | Preserve and back up; implement ignore policy in F00 and reconcile during any migration/restore |
| Remaining blockers / next owner | Assign during F00 |
| Operations and recovery guide | Deliver in F30 and validate in F35 |

This tracker records the new factory project. Existing batch videos, working credentials and previously delivered Drive files remain valid evidence of those earlier workflows; they are not erased or rerun merely because this checklist starts empty.
