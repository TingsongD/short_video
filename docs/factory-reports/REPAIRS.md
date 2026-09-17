# Factory repair ledger

Starting revision: `dae132a`, branch `feat/factory`. The user authorized S0–S8
implementation and the public test boundaries listed in REPAIR-BASELINE.json.
All checks use offline providers; no new live spend or publication scope exists.

## Package evidence

| Package | Status | Evidence |
| --- | --- | --- |
| S0 containment | passed (offline checkpoint) | 856 suite tests passed in 115.35s; 5 focused safety tests passed (the final regression was added after full-suite collection); Approval clock regression reproduced then fixed; structured event redaction; unavailable handlers and empty reviews block; live transport policy defaults offline |
| S1 state/restore | passed | 863 tests pass (117.24s); atomic v7→v8 migration fault/retry; restored media/ledger checks; normal CLI shares restored database |
| S2 effects/budgets | shared-boundary checkpoint passed; adapter/application qualification remains S3/S5 | 875 tests pass (119.62s); 10 effect regressions; scoped atomic reservations/attempts/outbox/capacity; API uncertain retries blocked; per-experiment pause and collection; native provider enforcement verified with adapters in S3 |
| S3 adapters | passed (offline protocol checkpoint) | 886 tests pass (119.31s); 11 protocol regressions; installed Canvas schema; validated Shopify queries; real isolated Hypit 30-frame export and owned runtime cleanup. See REPAIR-S3-EVIDENCE.json. |
| S4 media/QC | passed (offline checkpoint) | 903 tests pass (125.61s); 16 media regressions, collected-coverage regression, real 48-frame Hypit timing fixture, actual speech fitting and full interval comparisons. See REPAIR-S4-EVIDENCE.json. |
| S5 application | first local milestone passed; final fault matrix remains S8 | 916 backend tests; 25 frontend tests/build; real HTTP/independent-worker four × 900-frame exports with distinct treatments, bound reviews, durable fake Drive receipts and verified cleanup. Native Studio opened and closed. See REPAIR-S5-EVIDENCE.json. |
| S6 research | passed (offline checkpoint) | 922 tests pass; public research plan/approval/budget/worker/evaluation journey. Separate creator histories and strict cohort exclusions. See REPAIR-S6-EVIDENCE.json. |
| S7 publishing/learning | planned | |
| S8 qualification | planned | |

## Finding dispositions

Disabling a capability is containment, not closure. Live qualification is
separate from engineering repairs; historical tests do not sign either gate.

| Finding | Engineering status | Validation |
| --- | --- | --- |
| R01 | in_progress | Real bootstrap and independent worker now execute the four-output import/render/review/delivery graph. Generated audio and research/publication app routes complete in remaining packages. |
| R02 | in_progress | Shared effect authority/reservation boundary connected to generation, speech, music, research, analysis, delivery and publication. Native transports and real bootstrap require S3/S5 qualification. |
| R03 | fixed | Edits invalidate draft quotes/authority; dispatch checks immutable bound record and experiment revision. |
| R04 | fixed (offline) | Native quotes retained before approval; fresh ceiling cannot increase; absent pricing blocks. Regression tests enforce both boundaries. |
| R05 | fixed | Duplicate and restarted submissions reuse the original attempt; unknown acknowledgements never dispatch again. |
| R06 | fixed | Remote holds count independently of leases; five-operation regression, configurable capacity and local heartbeat. |
| R07 | in_progress | Per-experiment pause, collection queue, bounded retries, terminal failures and manual replacement transitions repaired; application recovery journey pending S5/S8. |
| R08 | fixed (offline) | Separate creator history, audited exclusions and minimum evidence; insufficient baseline is unavailable. |
| R09 | fixed (offline) | Native OAuth, typed pilot request and completed-step output parsing; durable ambiguous POST receipts. Unqualified reference modes visibly unavailable; live text route qualification still separate. |
| R10 | fixed (offline) | Installed CLI 1.0.1 contract; stable persisted IDs, shared video canvas, reference imports, exact draft checks, operation/resource provenance and native file receipts. |
| R11 | fixed (offline) | Pinned 0.1.8 nested build/status/get envelopes, workspace scope, original-build recovery and strict local plan gate. Real local 30-frame export retrieved; runtime stopped. |
| R12 | fixed (offline) | Production graph includes collection, explicit asset reviews, composition, rendering, QC and awaited final acceptance. Short public HTTP journey passed. |
| R13 | fixed (offline) | Dashboard mounted to real collections/revision IDs, queue, compare, review, delivery and Studio; actual browser playback and two-tab selection checked. |
| R14 | fixed (offline) | Native Studio launch uses private composition copy and actual printed URL, durable session and owned cleanup; comments remain proposed changes. |
| R15 | in_progress | Technical and explicit creative acceptance require current plan/composition/final bindings; default production selector blocks. Application delivery ownership is S5. |
| R16 | fixed (offline) | Native Drive full-name listing, complete-list detection, descriptive upload copy, exact byte size and MD5/parent parsing. Live delivery remains separately qualified. |
| R17 | in_progress | Repeated delivery reconciles, expected size is persisted, and uncertain upload never repeats automatically; artifact acceptance and native Drive qualification pending S3/S5. |
| R18 | fixed (offline) | Shared identity includes provider/model/duration/handles; supported remainders trim explicitly; plan hash includes allocations/quotes. Collected and manual coverage are measured before acceptance. |
| R19 | fixed (offline) | Source and target offsets, gaps, stills, captions, audio gains/offsets, clocks and full cache identities are enforced. Native Hypit 48-frame fixture verifies crossfade, still, source offset, captions and delayed sound. Unsupported effects return diagnostics. |
| R20 | fixed (offline) | Real fitted waveform is measured; alignment divides by rate; raw synthesis is separate from fitted cache/approval. New target reuses raw audio and needs its own fit/review. |
| R21 | fixed (offline) | Decode/resample, fixed sample count, float accumulation, ducking, measured RMS target/headroom and bounded music-loop overlap; regression checks waveform ratios and timing. |
| R22 | fixed (offline) | Real freeze-to-EOF, frame rate/duration, audio/narration coverage and detector failures checked; moving clean fixtures distinguish intended stills from accidental freezes. |
| R23 | fixed (offline) | Missing hashes/audio/coverage block; every unchanged video frame is compared and audio evidence is combined; change away from midpoint regression passes. Integrated treatment-region binding remains in S5 application qualification. |
| R24 | fixed (offline) | Owned resource descendants are recorded before parent termination, exit/ports verified; fixture Studio port freed while shared API/worker stay available. |
| R25 | in_progress | Restore hold now enforced before reservation and dispatch; operator activation and full restore journey remain S5/S8. |
| R26 | fixed (offline) | API/worker share bootstrap and data resolver; documented serve/worker commands and setup includes ASGI runtime. |
| R27 | fixed (offline) | Nonempty environment > dotenv > private TOML > safe configuration, explicit readiness facts, isolated offline bootstrap. |
| R28 | fixed (offline) | Named factory SSE events and ordered replay, acknowledged browser action generations and durable uncertain retry keys; two-tab event cursors do not suppress each other. |
| R29 | fixed (offline) | API mutation, domain records, durable job and response commit atomically; action binds expected revision and upload content hash. External calls only occur in workers. |
| R30 | fixed (offline) | Read-only Admin price scalar and full variant/media pagination; bounded media fetch and redirects. Four queries passed schema validation; offline multi-page/redirect tests. |
| R31 | in_progress | Durable synchronous receipts and artifacts replace in-memory operations; verified search adapter and actual source-media analysis boundary added. Research cache/cohort decisions remain S6; app wiring S5. |
| R32 | open | |
| R33 | open | |
| R34 | open | |
| R35 | open | |
| R36 | open | |
| R37 | fixed | Rebranch preserves prior variants; composition history retained; persisted template references resolve |
| R38 | in_progress | Nested credentials redacted before durable events and replay; live transport/API audit remains |
| R39 | open | |
| R40 | fixed | Approval grant/check share injected time; 7 approval tests pass |
| R41 | in_progress | Pinned model enforced; live routing requires qualified catalog and active authority; unresolved or successfully completed originals cannot trigger paid fallback. Adapter qualification remains S3. |
| R42 | open | |
| R43 | fixed (offline) | Imports stream to bounded temporary files and probing leaves event loop; media validates registered identity and streams 64-KiB ranges; production long work runs independently. |

## S2 implementation notes

Parent implementation revision: `006f274`. The S2 commit contains the code,
regressions and this checkpoint. Tests use explicit fixture operator approvals
through `EffectService.approve`, not an exemption for fake paid providers.
Requests bind account, provider/model, full settings, immutable record digest,
experiment revision, dated quote and expiry. Applicable aggregate/provider and
authority caps reserve together. Real overcharges are recorded and halt spending.

The generic legacy API draft surface is retained only until S5 replaces it. It
cannot mint the scoped authority required by the effect executor. This checkpoint
does not qualify native adapter protocols, integrated UI delivery, a real provider
or the full factory. R02/R07/R25/R29/R41 remain open where those journeys are needed.

Frozen contracts and the legacy ledger match the starting hashes. The pre-existing
`LONGFORM_PLAN.md` deletion and dashboard build-cache change remain unstaged.
