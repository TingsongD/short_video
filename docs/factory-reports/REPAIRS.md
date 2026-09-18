# Factory repair ledger

> **Current status (2026-09-18):** after the S0–S8 packages below, the
> independent [REVIEW-2026-09-18](REVIEW-2026-09-18.md) found 15
> implementation defects (Q01–Q15) — all patched; see its resolution
> table and `tests/test_factory_review_fixes.py`. Suite: 1062 backend +
> 29 frontend green.

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
| S7 publishing/learning | passed (offline checkpoint) | 932 tests passed; native protocol, exact publication authority, coverage-aware readback and current independent evidence. Public four-export/post/readback/decision journey. See REPAIR-S7-EVIDENCE.json. |
| S8 qualification | offline checkpoint passed (`c6ffad2`); live qualification pending | 952 backend tests; 28 frontend tests/build. Real short/long HTTP application journeys, five worker-kill points, six-worker capacity, restore activation, new auxiliary application routes and browser checks. See REPAIR-S8-EVIDENCE.json. |

## Finding dispositions

Disabling a capability is containment, not closure. Live qualification is
separate from engineering repairs; historical tests do not sign either gate.

| Finding | Engineering status | Validation |
| --- | --- | --- |
| R01 | repaired; offline evidence | Real public application produces A/B/C/D, reviews exact finals, verifies fake delivery and cleans up. S8 adds quoted audio/analysis and local recovery commands. |
| R02 | repaired; offline evidence | Shared effect boundary binds scoped authority, native-unit funding, reservations, outbox and attempts. All application external-effect routes use it; zero-price operations retain auditable settlements. |
| R03 | repaired; offline evidence | Edits invalidate draft quotes/authority; dispatch checks immutable bound record and experiment revision. |
| R04 | repaired; offline evidence | Native quotes retained before approval; fresh ceiling cannot increase; absent pricing blocks. Regression tests enforce both boundaries. |
| R05 | repaired; offline evidence | Duplicate and restarted submissions reuse the original attempt; unknown acknowledgements never dispatch again. |
| R06 | repaired; offline evidence | Remote holds count independently of leases; five-operation regression, configurable capacity and local heartbeat. |
| R07 | repaired; offline evidence | Accepted work collects while paused; bounded observation/transfer retries; terminal generation can take a reviewed manual replacement; local retries clean up and cannot create paid replacements. |
| R08 | repaired; offline evidence | Separate creator history, audited exclusions and minimum evidence; insufficient baseline is unavailable. |
| R09 | repaired; offline evidence | Native OAuth, typed pilot request and completed-step output parsing; durable ambiguous POST receipts. Unqualified reference modes visibly unavailable; live text route qualification still separate. |
| R10 | repaired; offline evidence | Installed CLI 1.0.1 contract; stable persisted IDs, shared video canvas, reference imports, exact draft checks, operation/resource provenance and native file receipts. |
| R11 | repaired; offline evidence | Pinned 0.1.8 nested build/status/get envelopes, workspace scope, original-build recovery and strict local plan gate. Real local 30-frame export retrieved; runtime stopped. |
| R12 | repaired; offline evidence | One bootstrap and independent durable worker serve the actual domain graph; documented startup works on a single loopback origin. |
| R13 | repaired; offline evidence | Typed API commands create authoritative records and durable jobs; no placeholder success. Generation, import, analysis, speech, research, publication and readback commands are wired. |
| R14 | repaired; offline evidence | Dashboard mounts actual collections, revision-aware plans, budgets, queue, comparison, reviews, delivery and isolated native Studio; auxiliary workflow screens use real API commands. |
| R15 | repaired; offline evidence | Missing technical/creative evidence, stale revisions and unowned final bytes block delivery; actual public fixture reviews bind current composition, plan and final hash. |
| R16 | repaired; offline evidence | Native Drive full-name listing, complete-list detection, descriptive upload copy, exact byte size and MD5/parent parsing. Live delivery remains separately qualified. |
| R17 | repaired; offline evidence | Repeated delivery returns/reconciles its original receipt. A real worker kill after fake remote upload recovers without a second upload. |
| R18 | repaired; offline evidence | Shared identity includes provider/model/duration/handles; supported remainders trim explicitly; plan hash includes allocations/quotes. Collected and manual coverage are measured before acceptance. |
| R19 | repaired; offline evidence | Source and target offsets, gaps, stills, captions, audio gains/offsets, clocks and full cache identities are enforced. Native Hypit 48-frame fixture verifies crossfade, still, source offset, captions and delayed sound. Unsupported effects return diagnostics. |
| R20 | repaired; offline evidence | Real fitted waveform is measured; alignment divides by rate; raw synthesis is separate from fitted cache/approval. New target reuses raw audio and needs its own fit/review. |
| R21 | repaired; offline evidence | Decode/resample, fixed sample count, float accumulation, ducking, measured RMS target/headroom and bounded music-loop overlap; regression checks waveform ratios and timing. |
| R22 | repaired; offline evidence | Real freeze-to-EOF, frame rate/duration, audio/narration coverage and detector failures checked; moving clean fixtures distinguish intended stills from accidental freezes. |
| R23 | repaired; offline evidence | Missing hashes/audio/coverage block; full unchanged frame intervals and audio evidence are checked. Both actual application fixture lengths pass treatment-region QC. |
| R24 | repaired; offline evidence | Owned resource descendants are recorded before parent termination, exit/ports verified; fixture Studio port freed while shared API/worker stay available. |
| R25 | repaired; offline evidence | Populated backup restores through CLI to the expected fresh-root DB, verifies artifacts and quarantines source PIDs. Activation requires current audit evidence, retires old budgets/approvals and preserves history. |
| R26 | repaired; offline evidence | Actual environment/dotenv/TOML precedence, shared DATA_ROOT, worker heartbeat and separate installed/authenticated/catalog/contract/live readiness facts. |
| R27 | repaired; offline evidence | Browser mutations persist action keys across uncertain retries; refreshed and separate tabs preserve independent logical actions. Server fingerprint includes expected revision and imported bytes. |
| R28 | repaired; offline evidence | Named factory SSE events and ordered replay, acknowledged browser action generations and durable uncertain retry keys; two-tab event cursors do not suppress each other. |
| R29 | repaired; offline evidence | API mutation, domain records, durable job and response commit atomically; action binds expected revision and upload content hash. External calls only occur in workers. |
| R30 | repaired; offline evidence | Read-only Admin price scalar and full variant/media pagination; bounded media fetch and redirects. Four queries passed schema validation; offline multi-page/redirect tests. |
| R31 | repaired; offline evidence | Durable receipt/payload recovery replaces in-memory operations. Research and registered-media analysis use exact quoted jobs; actual media bytes reach the injected native analysis boundary. Manual source import remains supported. |
| R32 | repaired; offline evidence | Native asynchronous multipart contract, per-platform results and stable client request identity. |
| R33 | repaired; offline evidence | Exact immutable final bytes/destination/action; verified delivery and cleanup required; manual declarations remain unverified. |
| R34 | repaired; offline evidence | Reporting job/report pagination, trusted bounded CSV downloads and source filtering. |
| R35 | repaired; offline evidence | Weighted metrics, per-metric full coverage, source timezone and explicit rolling-window eligibility. |
| R36 | repaired; offline evidence | Frozen horizon, per-arm exposure, actual experiment identity and immutable numeric decision history. |
| R37 | repaired; offline evidence | Rebranch preserves prior variants; composition history retained; persisted template references resolve |
| R38 | repaired; offline evidence | Structured redaction precedes durable events/receipts and API errors. Sensitive command fields are rejected; credentials resolve only at transport. Domain variant/operation keys remain usable. |
| R39 | repaired; offline evidence | Historical completion claims are explicitly corrected; real public HTTP renders, process-kill drills, six-worker concurrency, browser recovery and fresh-root restore have separately recorded evidence. |
| R40 | repaired; offline evidence | Approval grant/check share injected time; 7 approval tests pass |
| R41 | repaired; offline evidence | Actual production quote and dispatch recheck pinned route, current catalog and live qualification; unresolved or successful originals cannot cause automatic paid fallback. |
| R42 | repaired; offline evidence | Unknown baseline/metrics, pending evidence and nonexact windows cannot promote legacy formats. |
| R43 | repaired; offline evidence | Imports stream to bounded temporary files and probing leaves event loop; media validates registered identity and streams 64-KiB ranges; production long work runs independently. |

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

## S8 disposition rules

The rows above describe **engineering repair**, not live qualification. Exact
implementation commits and regression coverage are mapped in
[S8 finding evidence](REPAIR-S8-FINDINGS.md). No finding is closed solely by
turning its feature off. Required native protocol corrections are implemented and
tested offline; optional unsupported routes remain explicitly unavailable.

Human creative/listening acceptance of actual generated products is still pending.
All selected live provider/account/model/input modes, real Drive delivery,
publication and elapsed analytics horizons require their own funded qualification.
Legacy G-gates remain independent. Historical checkpoint descriptions above are
retained as dated evidence; later S8 evidence supersedes their pending dependencies.

## Post-repair review repairs (N01–N20, 2026-09-17)

Review: [REVIEW-POST-REPAIR-2026-09-17.md](REVIEW-POST-REPAIR-2026-09-17.md)
Plan: [REPAIR-PLAN-2026-09-17.md](REPAIR-PLAN-2026-09-17.md)
Probes (audit trail, assert old bad behavior — expected to FAIL after repair):
`probes/review_post_repair_2026_09_17.py`
Permanent regression tests (assert repaired contracts):
`tests/test_factory_repairs_2026_09_17.py` — 21 tests.

| Issue | Repair commit | Probe | Regression test |
| --- | --- | --- | --- |
| N01 publication ignores withdrawn acceptance | 7822430 | test_withdrawn_creative_acceptance_still_publishes | test_withdrawn_acceptance_blocks_publication |
| N02 failed render marked successful | bab1004 | test_failed_renderer_is_successful_job | test_failed_result_fails_job_and_releases_hold |
| N03 reconcile doesn't resume production | 901d09b | test_ack_loss_reconcile_leaves_production_failed | test_reconcile_resumes_failed_production |
| N04 Canvas quote loses receipts | e46bc21 | test_canvas_quote_flush_can_lose_other_worker_receipts | test_canvas_quote_flush_preserves_concurrent_receipts |
| N05 Canvas attempts share one op | e46bc21 | test_canvas_distinct_attempts_share_one_operation | test_canvas_attempts_get_distinct_operations |
| N06 Vertex misses saved acceptance | c8dbe17 | test_vertex_cannot_recover_saved_acceptance_by_executor_hash | test_vertex_recovers_saved_acceptance_by_attempt |
| N07 TTS normalization breaks flow | 7822430 + alignment fix | test_tts_normalization_breaks_real_public_audio_flow | test_tts_normalized_copy_fits_and_attaches |
| N08 stale derived media | 7822430 | test_treatment_dependency_declaration_allows_stale_speech | test_treatment_stale_derived_media_flagged |
| N09 no delivery retry after pre-upload failure | 901d09b | test_delivery_failed_before_upload_has_no_application_retry | test_delivery_reentry_delegates_to_retry |
| N10 local retries replay cached failure | 901d09b | test_repeated_render_failure_is_cached_forever | test_runner_retry_executes_fresh_attempt |
| N11 restore paths break render identity | 99bbe88 | test_restore_paths_change_render_identity | test_restore_paths_preserve_render_identity |
| N12 Vertex ignores nested settings | c8dbe17 | test_vertex_nested_settings_ignored | test_vertex_nested_settings_applied_and_conflicts_rejected |
| N13 Canvas/router refs shape conflict | e46bc21 | test_canvas_reference_shape_conflicts_with_router | test_canvas_typed_reference_contract |
| N14 stills fail QC | c739802 | test_still_images_rejected_by_production_qc | test_still_images_pass_production_qc |
| N15 frozen mix never wired | c739802 | (static finding) | test_production_render_uses_frozen_mix |
| N16 latest snapshot not pin | 7822430 | test_authorization_uses_latest_product_instead_of_pin | test_authorization_uses_pinned_snapshot |
| N17 claims control-only | 7822430 | test_unsupported_variant_claims_are_accepted | test_variant_claims_are_validated |
| N18 research bypasses cache | c739802 | test_research_application_bypasses_cache_and_reports_no_calls | test_research_cache_and_truthful_coverage |
| N19 learning ignores revision | 7822430 | test_new_learning_policy_blocked_by_old_revision_posts | test_new_revision_policy_not_blocked_by_old_posts |
| N20 readiness checks on refresh | c739802 | (static finding) | test_readiness_cached_and_refresh_bypasses |

### Notes

- No DB migrations: all repairs use additive record-body fields
  (Publication.experiment_id/experiment_revision), adapter-state files, or
  hash-material versioning (render.v4).
- bab1004 (N02) is unsafe to revert alone — it removes the fail-open
  catch-all that turned arbitrary handler results into silent successes.
- N07 additionally surfaced an alignment defect: provider character
  alignment was checked against normalized text instead of the spoken
  source_text (fixed in modules/factory/audio/alignment.py).
- pytest.ini now scopes default collection to tests/ — bare `pytest`
  no longer collects vendor/ suites and dies on their missing deps.
- Original probe file retained as audit trail; every assertion in it
  encodes pre-repair behavior and must not be re-greened.
