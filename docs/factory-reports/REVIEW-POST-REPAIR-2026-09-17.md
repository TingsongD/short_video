# Viral Video Factory — review after S8 repairs

**Reviewed:** 2026-09-17  
**Branch / implementation:** `feat/factory` / `c6ffad2`  
**Scope:** current factory application, native adapter boundaries, recovery, media processing, delivery, publication, research, learning, and the completion claims in `DEV_LOG.md` and the S8 reports. The legacy pipeline was covered by the existing full test suite, not a second exhaustive line-by-line legacy review.

## Conclusion

**The repaired application is substantially more complete, but it is not ready for unattended production.** This review identifies **20 remaining code/integration issues: 11 P1 and 9 P2**. Eighteen findings have executable reproductions; two are established by tracing the application call paths. Separate qualification and operator-workflow gaps appear below.

The most urgent problems are publication after a withdrawn creative review, failed renders reported as successful jobs, recovery that cannot resume the production graph, and native-provider identity/receipt handling. Passing the existing suite does not establish that all 43 earlier findings are closed.

This report is a review, not an implementation or spending authorization. No application code, operational database, credentials, spending records, or generated production assets were changed. New files are this report, its evidence record, and review probes. The pre-existing changes to `DEV_LOG.md`, `docs/factory-reports/REPAIRS.md`, the deleted `LONGFORM_PLAN.md`, and the dashboard build cache were retained.

## Verification and evidence

| Check | Result | Interpretation |
| --- | --- | --- |
| Full `make test` under the restricted environment | 942 passed; 10 failed in 334.53 seconds | Failures involved unavailable process inspection and resulting supervisor/render timeouts. |
| The exact 10 failed tests, rerun with local process permissions | 10 passed in 114.46 seconds | All 952 existing tests are accounted for across those two runs. This is not a claim of a new single-run 952-pass result. |
| Frontend tests | 28 passed | Existing component/client tests remain green. |
| Frontend production build | Passed | TypeScript and Vite build completed. |
| Frozen `schemas/` and `tests/fixtures/` | No diff against HEAD | Contracts were preserved. |
| Additional review probes | See [evidence JSON](REVIEW-POST-REPAIR-2026-09-17-EVIDENCE.json) | They reproduce defects using fake remote services, fresh temporary databases and real local media where needed. |

The [saved probe module](probes/review_post_repair_2026_09_17.py) is intentionally outside the normal test suite. **Its assertions describe the current bad behavior. A passing probe confirms a defect; it does not mean the feature is correct.** After repair, invert the relevant assertion and add it to the permanent suite.

Run from the repository root in an environment that permits inspection and cleanup of owned local test processes:

```bash
PYTHONPATH=.:tests .venv/bin/python -m pytest -q -s \
  docs/factory-reports/probes/review_post_repair_2026_09_17.py
```

No live generation, paid research, real publication or real Drive upload was used. Existing fake publication/delivery journeys were rerun; their temporary exports are test fixtures, not production deliverables. A new interactive browser journey and the four 5,091-frame release exports were not repeated in this review.

## Issue index

P1 means repair before unattended production or the affected release workflow. P2 means a functional or operational defect that needs repair before claiming that capability complete.

| ID | Priority | Remaining issue | Earlier finding area |
| --- | --- | --- | --- |
| N01 | P1 | Queued publication ignores a subsequently failed creative review | R15, R33 |
| N02 | P1 | A failed render is recorded as a successful job | R01, R07 |
| N03 | P1 | Successful remote reconciliation does not resume failed production | R05, R07 |
| N04 | P1 | Canvas quoting can erase another worker's accepted-operation receipt | R05, R10 |
| N05 | P1 | Separate Canvas allocations can reuse one remote generation | R05, R18 |
| N06 | P1 | Vertex recovery cannot find an acceptance receipt already saved locally | R05, R09 |
| N07 | P1 | Ordinary TTS copy fails after synthesis, or attaches no speech | R20 |
| N08 | P1 | Copy changes can retain stale speech, captions and lip-sync footage | R15, R19, R23 |
| N09 | P1 | Delivery cannot recover through the application after a pre-upload failure | R07, R17 |
| N10 | P1 | Local retries replay a cached command failure indefinitely | R07, R24 |
| N11 | P1 | Moving restored media to a fresh root invalidates unfinished render identity | R25 |
| N12 | P2 | Vertex ignores settings that the router approved | R09, R19, R41 |
| N13 | P2 | Canvas and the router disagree on reference format | R10, R41 |
| N14 | P2 | Supported still-image compositions cannot pass the normal review/QC path | R14, R22 |
| N15 | P2 | Production bypasses the frozen audio-mix service | R21 |
| N16 | P2 | Approval reads the latest product snapshot instead of the pinned revision | R15, R37 |
| N17 | P2 | Product-claim validation omits B/C/D | R15 |
| N18 | P2 | Application research bypasses caching and reports zero calls/pages | R08, R31 |
| N19 | P2 | Publication/learning lookup does not respect experiment-revision scope | R36, R37 |
| N20 | P2 | Dashboard refreshes repeatedly run blocking live readiness checks | R26, R43 |

## Findings

### N01 — Recheck creative acceptance immediately before publication

**Location:** [publication_work.py](../../modules/factory/services/publication_work.py), `plan()` lines 12–25 and `execute()` lines 47–63.

Publication planning checks technical/creative acceptance, but execution only checks the publication authorization and final bytes. Between those steps an operator can record a new **failed** creative review on the same final. Its composition and experiment revision remain unchanged, so the old publication authorization still works.

**Reproduction:** `test_withdrawn_creative_acceptance_still_publishes` makes four real local fixture exports, reviews and fake-delivers them, authorizes one post, then withdraws creative acceptance before the worker runs. `quality.accept()` correctly rejects the final, but the worker still sends it to the fake publisher.

**Required repair:** bind the relevant acceptance evidence to the publication intent and revalidate current acceptance just before the external effect. A newly failed review must block queued publication while preserving the intent and audit history. Remote work already accepted must still be observed rather than blindly replaced.

### N02 — Do not complete jobs whose handler returned failure

**Location:** [worker.py](../../modules/factory/services/worker.py), lines 31–40; [rendering/service.py](../../modules/factory/rendering/service.py), lines 61–73.

`ApplicationWorker.tick()` special-cases review and pending states, then marks every other returned status successful. `RenderService.dispatch()` legitimately returns `{"status":"failed"}` for a renderer `RuntimeError`. The worker marks that job `succeeded`, even though it has no final. The `local_work` marker also remains, so local-render capacity can stay occupied while the UI reports completion. Delivery `conflict`/`unverified` returns fall through the same success branch.

**Reproduction:** `test_failed_renderer_is_successful_job` drives the public import/quote/review workflow and injects a renderer failure. The result says failed, the job says succeeded, and the local-work hold remains.

**Required repair:** use an explicit exhaustive result-state mapping; only recognized successful outcomes may complete a job. Preserve failed/unverified states and their valid retry/cleanup transitions.

### N03 — Reconciliation must resume collection and downstream dependencies

**Location:** [worker.py](../../modules/factory/services/worker.py), lines 49–54 and 130–140; [recovery.py](../../modules/factory/services/recovery.py), lines 7–15.

A lost generation acknowledgement marks the original production job failed and blocks descendants. The Reconcile command can find the successful remote operation, but only returns its status. It does not reopen the original job, schedule its collection, or unblock its dependent jobs. Retry Local explicitly refuses any job with an external attempt.

**Reproduction:** `test_ack_loss_reconcile_leaves_production_failed` has the fake service accept a clip and lose its reply. Public reconciliation subsequently reports success, while the original job remains failed and 13 descendant jobs remain blocked.

**Required repair:** reconcile the same attempt, then advance the original work item to observation/collection and update its dependency graph. Do not require or create a replacement generation. Extend this test to synchronous effects as well as video.

### N04 — Lock the entire Canvas quote receipt update

**Location:** [canvas.py](../../modules/factory/providers/canvas.py), lines 214–219; [state.py](../../modules/factory/providers/state.py), whole-document flush/locking.

`prepare_quote()` calls locked `prepare()`, releases that lock, performs external reads, modifies the returned preparation and saves the entire state file without a lock/reload. A different process can persist an accepted operation during that gap. The stale quote save overwrites it. Locking `submit()` does not protect a quote performed by another process.

**Reproduction:** `test_canvas_quote_flush_can_lose_other_worker_receipts` interleaves an independently locked state writer during the quote call. Its accepted-operation receipt is absent after the quote saves.

**Required repair:** make quote read/modify/save atomic with the other receipt operations, or move these records into transactional storage. Include a real multiprocess quote/submit test, not only parallel submits.

### N05 — Separate logical allocations from retry identity in Canvas

**Location:** [canvas.py](../../modules/factory/providers/canvas.py), lines 148–157 and 240–243; [production/plan.py](../../modules/factory/production/plan.py), lines 228–248.

Canvas preparations are keyed by request content and contain one submission ID. `submit()` reuses that operation even when the executor supplies a different `attempt_id`. Equal-duration allocations of the same long shot produce identical requests, so a planned pair of 10-second clips can resolve to one clip twice. An explicitly approved new take with identical settings also reuses the old take.

**Reproduction:** `test_canvas_distinct_attempts_share_one_operation` supplies two distinct durable attempt IDs. Both return the same operation; the fake Canvas service has only one generated clip.

**Required repair:** bind preparation/submission identity to the logical work allocation and generation revision. Retries of that allocation must reuse it; independently approved allocations must remain distinct. Recheck reservations, collection and sharing after this change.

### N06 — Recover Vertex by the durable attempt/submission mapping

**Location:** [vertex.py](../../modules/factory/providers/vertex.py), lines 151–156, 211–232 and 293–305; [executor.py](../../modules/factory/execution/executor.py), lines 251–260.

The executor hashes the request JSON. Vertex hashes `model + "|" + request JSON`. When the executor has no remote ID, it passes its hash to `reconcile()`, which compares against the incompatible Vertex hash. Vertex already saves a submission mapping keyed by the durable attempt ID, but reconciliation ignores it.

**Reproduction:** `test_vertex_cannot_recover_saved_acceptance_by_executor_hash` saves a native-adapter acceptance receipt, reconstructs the adapter, and reconciles under the original attempt context using the executor's hash. It returns `None` despite containing the remote ID. This is the crash window between adapter persistence and the executor's database update.

**Required repair:** resolve the original attempt through `submissions`, validate its request binding and observe that saved operation. Retain an unresolved state when acceptance truly is unknown; never fix this by resubmitting.

### N07 — Use one speech text identity from quoting through attachment

**Location:** [OperationsScreen.tsx](../../apps/factory-dashboard/src/features/operations/OperationsScreen.tsx), line 44; [audio_work.py](../../modules/factory/services/audio_work.py), lines 32–35 and 68–75.

The UI submits raw copy. After synthesis, `queue_fit()` requires the request text to equal normalized copy. For example, `It's 2 dollars.` normalizes to `It is two dollars.` and is rejected **after** synthesis. Manually normalizing before submission does not finish the workflow: attachment compares normalized `source_text` against the original copy, returns a successful new revision, and attaches no audio.

**Reproduction:** both cases of `test_tts_normalization_breaks_real_public_audio_flow` use the public quote, authorization, fake ElevenLabs synthesis and fitting routes. The raw route returns `speech_copy_mismatch`; the normalized route approves fitted speech and then silently leaves the segment's speech empty.

**Required repair:** preserve original display copy and a separately versioned normalized synthesis text/hash. Bind quotes, alignment, fitting and attachment to the same values. Attachment must reject zero matches, and target/voice/dependency bindings must be checked explicitly.

### N08 — Declaring dependencies is not proof that derived media was updated

**Location:** [diff.py](../../modules/factory/experiments/diff.py), lines 88–97; [worker.py](../../modules/factory/services/worker.py), speech assembly at lines 243–253.

Treatment validation checks whether `speech`, `captions` and `picture` appear in the allowed-field list when copy may change. It does not establish that the actual derived tracks match the new copy. A branch can change its copy while retaining all old speech and lip-sync assets, and pass treatment validation. The render uses the old supplied audio; duration/hash checks do not verify spoken content.

**Reproduction:** `test_treatment_dependency_declaration_allows_stale_speech` changes copy and lists the dependency fields, leaving their values unchanged. Validation returns no problems.

**Required repair:** record source text/voice/reference versions on derived tracks and invalidate incompatible assets. Require current speech/alignment and, where relevant, lip-sync evidence before approving the plan. Allow truly unaffected footage only through an explicit supported dependency rule.

### N09 — Expose a real delivery retry after failure before submission

**Location:** [delivery/service.py](../../modules/factory/delivery/service.py), lines 55–58, 157–166 and 177–195; [services/app.py](../../modules/factory/services/app.py), lines 310–312.

If Drive listing fails before upload, the delivery record exists but no external attempt was made. Re-entering `deliver()` now only reconciles; finding no remote file returns `pending / retry_transfer` forever. The application returns the existing failed job on another Deliver request, does not invoke `DeliveryService.retry()`, and its generic retry path does not support delivery jobs. Reconcile also has no attempt to observe in this case.

**Reproduction:** `test_delivery_failed_before_upload_has_no_application_retry` fails the initial listing, restores the fake Drive service and re-enters delivery three times. No upload starts; every return asks for a transfer retry that the application cannot perform.

**Required repair:** add a durable retry transition that reconciles first and transfers the exact approved bytes only when prior non-submission is established. Keep ambiguous upload acceptance held for reconciliation. Return the current verified receipt for completed deliveries.

### N10 — An explicit local retry needs a new command-attempt identity

**Location:** [runner.py](../../modules/factory/resources/runner.py), lines 20–40; [recovery.py](../../modules/factory/services/recovery.py), `retry_local()`.

The local supervisor caches by argv, working directory and owner. It returns any `done` receipt, including a nonzero exit code, forever. Retry Local resets the job and releases owned resources but leaves that failed receipt and identity unchanged. A fixed disk or temporary renderer problem therefore encounters the same recorded failure without executing again. Timed-out receipts also lack a usable explicit retry transition.

**Reproduction:** `test_repeated_render_failure_is_cached_forever` calls the same safe command twice with an existing failed receipt and gets that failure both times; the command never starts.

**Required repair:** distinguish resuming one local attempt from explicitly authorizing a bounded new local attempt after verified cleanup. Preserve old receipts; do not erase them or blindly relaunch an unresolved process.

### N11 — Render identity must survive an authorized fresh-root restore

**Location:** [rendering/service.py](../../modules/factory/rendering/service.py), lines 50–56 and 139–146; [operations/paths.py](../../modules/factory/operations/paths.py), `restored_path()`.

`inputs_hash` includes the entire input dictionaries, including absolute `src` paths. Restore relocates registered artifacts and workspaces into a fresh root. The next dispatch of an unfinished build supplies different absolute paths for identical approved bytes, so it raises `render_input_revision_mismatch`. Workspace remapping alone does not solve the input identity change.

**Reproduction:** `test_restore_paths_change_render_identity` starts a build, preserves its failed/interrupted identity, then dispatches with byte-identical media at a fresh path. The mismatch blocks recovery. This isolates the path component; it is not a claim that a full restored render journey was run in this review.

**Required repair:** key content identity on artifact IDs/hashes, timing and settings, with transport paths outside that identity. Add an integrated fresh-root restore of an unfinished render after reconciliation/activation, preserving all spending blocks.

### N12 — Vertex must render the exact approved settings

**Location:** [router.py](../../modules/factory/providers/router.py), lines 43–60; [vertex.py](../../modules/factory/providers/vertex.py), lines 132–149.

The router accepts `request.settings.aspect` and `request.settings.resolution`. Vertex's native payload reads only top-level fields, otherwise defaulting to portrait 720p. A supported, approved nested 16:9/1080p request therefore becomes 9:16/720p. Depending on the request, the wrong output is delivered to review or rejected after spending.

**Reproduction:** `test_vertex_nested_settings_ignored` uses a capability matrix permitting both settings and observes the wrong payload. This verifies request translation, not that every combination has been live-qualified.

**Required repair:** normalize one canonical request before pricing, approval, preflight and transport. Reject conflicting duplicate fields and assert the native wire payload matches the approved settings.

### N13 — Normalize registered references across router and Canvas

**Location:** [router.py](../../modules/factory/providers/router.py), lines 45–51; [canvas.py](../../modules/factory/providers/canvas.py), lines 105–117.

For `refs`, the router requires typed dictionaries such as `{kind:"image", artifact_id:...}`. Canvas treats each element as a string and calls `startswith()`. The alternative `reference_artifact_ids` form is understood by Canvas, but the router does not derive reference roles from those registered artifacts, so its input-mode qualification can disagree with the adapter.

**Reproduction:** `test_canvas_reference_shape_conflicts_with_router` passes the router's accepted reference shape to Canvas and gets `AttributeError` before a useful provider result.

**Required repair:** use a typed registered-artifact reference contract, derive media roles from verified registry entries, and translate to Canvas node/resource identifiers only at the adapter boundary. Test the complete public quote-to-adapter path with product references.

### N14 — Intentional stills need review controls and explicit QC evidence

**Location:** [App.tsx](../../apps/factory-dashboard/src/App.tsx), `videoAssets` and the Reviews tab; [worker.py](../../modules/factory/services/worker.py), line 284; [technical.py](../../modules/factory/quality/technical.py), lines 53 and 92–96.

Planning and rendering accept images, but the dashboard's asset review list contains only videos. Even when the image is approved through the API, production does not pass intentional-still intervals to QC. The freeze detector rejects a correctly rendered static product image as frozen footage, and creative acceptance cannot override that technical failure.

**Reproduction:** `test_still_images_rejected_by_production_qc` imports a product image, creates and approves a plan through the public API, renders it, and gets a `frozen_section` technical failure. The saved expected-QC data has no intentional-still evidence.

**Required repair:** show image assets for review and carry approved still intervals from the composition into QC. Continue rejecting unintended video freezes; do not globally disable the detector.

### N15 — Connect frozen mix policy to the actual render

**Location:** [bootstrap.py](../../modules/factory/bootstrap.py); [worker.py](../../modules/factory/services/worker.py), lines 243–262; [ffmpeg_fast.py](../../modules/factory/rendering/ffmpeg_fast.py), lines 170–187; [audio/mix.py](../../modules/factory/audio/mix.py).

`MixService` implements a frozen profile with sample rate/channels, gains, ducking, clipping policy and measured loudness. The application does not construct or call it. Production forwards individual gains to FFmpeg's `amix`/limiter instead; there is no application mix-profile binding. Technical QC checks gross silence/clipping but not the promised frozen loudness target. Independent mixer unit tests therefore do not prove application behavior.

**Evidence:** static call-path inspection, not a new audio-quality or loudness measurement.

**Required repair:** bind a frozen mix profile to the experiment/composition, render through that policy or an equivalent verified renderer implementation, and measure the final against it. Reject unsupported mix settings explicitly rather than accepting unused data.

### N16 — Resolve pinned product revisions when authorizing a plan

**Location:** [experiments/service.py](../../modules/factory/experiments/service.py), product pins in `create()`; [services/app.py](../../modules/factory/services/app.py), lines 218–219.

Experiment packaging records each product snapshot's revision, but authorization loads snapshots using only their IDs, which selects the latest revision. A later Shopify refresh changes the facts used to approve an already-pinned experiment without changing its experiment hash. Old valid claims can be rejected; newly added facts can be accepted even though the plan did not pin them.

**Reproduction:** `test_authorization_uses_latest_product_instead_of_pin` pins a cotton claim at snapshot revision 0, writes revision 1 with a different material, and observes approval use revision 1 while the experiment still pins revision 0.

**Required repair:** resolve `(snapshot_id, revision)` consistently. Updating product evidence must be an explicit experiment revision with new dependent approval.

### N17 — Validate product claims on all four variants

**Location:** [experiments/service.py](../../modules/factory/experiments/service.py), `acceptance_report()` lines 182–209.

Acceptance checks claims only in the control's packaging segments. A B/C/D branch can declare `claims` among its allowed fields, add a claim absent from every selected product snapshot, and still be authorized. The treatment check controls where fields change, not whether the replacement claim is supported.

**Reproduction:** `test_unsupported_variant_claims_are_accepted` adds an invented certification to B with no product evidence and receives a successful experiment authorization.

**Required repair:** validate claims and supported capabilities on every current variant against the exact pinned product revisions. This does not require inferring every claim from natural-language copy; the existing explicit claim contract must at least be enforced for all branches.

### N18 — Use the research cache and preserve actual scan coverage

**Location:** [effect_work.py](../../modules/factory/services/effect_work.py), `prepare()`/`execute()`; [worker.py](../../modules/factory/services/worker.py), lines 75–94; [discovery/service.py](../../modules/factory/discovery/service.py), `_request()` and `_finish()`.

The application executes research through generic effect plans, bypassing `DiscoveryService`'s provider/account/query cache. Identical newly prepared searches make new chargeable requests. Evaluation then calls `_finish()` with empty queries, zero pages, no received-page list and a newly initialized zero call counter. The saved discovery report consequently claims zero calls and zero pages despite successful paid work. The financial ledger still records the fake reported charges; the defect is duplicate work and incorrect research coverage.

**Reproduction:** `test_research_application_bypasses_cache_and_reports_no_calls` executes two identical approved two-request plans within one budget. Four remote fake receipts exist, the discovery cache is empty, and the first report says zero calls/pages.

**Required repair:** implement cache lookup/reuse within the shared execution boundary and construct coverage from durable request/receipt records. Keep cache age, account/settings scope and an explicit refresh choice visible.

### N19 — Scope learning/publication selection to the intended revision

**Location:** [learning/service.py](../../modules/factory/learning/service.py), lines 68–77 and 399–401.

Policy freezing rejects a new revision whenever any earlier nonfailed publication exists for the experiment. Conversely, `_publication_for()` matches only the stable variant ID, ignoring the publication's experiment revision and final bytes. The lookup also returns no publication once multiple public posts share that variant ID, rather than choosing an explicitly scoped platform/account cohort. The current application therefore cannot safely advance the publication/learning workflow through normal revisions.

**Reproduction:** `test_new_learning_policy_blocked_by_old_revision_posts` preserves an earlier public post, advances experiment and variants immutably to revision 2, and cannot freeze revision 2's policy. Direct lookup still resolves the earlier variant's post. This probe does **not** claim that a wrong-revision winner was produced through the complete public workflow.

**Required repair:** bind policy, publication selection and metric evidence to experiment revision, final artifact and an explicit platform/account comparison scope. Preserve earlier decisions independently. Add revision and multiple-publication tests.

### N20 — Do not run live readiness on every dashboard refresh

**Location:** [App.tsx](../../apps/factory-dashboard/src/App.tsx), lines 32–43; [api/app.py](../../modules/factory/api/app.py), lines 70–72; [services/app.py](../../modules/factory/services/app.py), lines 52–63.

Every durable event triggers a complete refresh of the collections, queue, health, providers, Studio and selected experiment. A five-second timer does the same, without coalescing in-flight refreshes. The async providers endpoint synchronously calls adapter readiness; Canvas invokes its CLI doctor and Vertex can refresh authentication. A slow native check blocks the API event loop, while frequent progress events queue still more checks.

**Evidence:** static call-path inspection; no live provider latency benchmark was run. The existing offline dashboard tests have no equivalent slow native readiness service.

**Required repair:** cache readiness with an explicit refresh action and expiry, move blocking checks out of the API event loop, coalesce dashboard refreshes, and refresh only affected collections. Test progress streaming and mutations while a fake readiness check is slow.

## Remaining capability and qualification work

These are additional release constraints, not interchangeable with the 20 confirmed defects.

1. **Live route qualification remains pending.** Qualify each selected account/provider/model/input mode, then one complete four-variant experiment with actual charge evidence, product/voice/creative review, verified Drive receipts and owned-process cleanup. Historical pilots, configuration flags and the offline suite do not qualify the repaired routes. The existing reports record local Hypit qualification; this review does not claim that work was absent.
2. **Ordinary posting times cannot currently produce a complete rolling-horizon result.** `ReadbackService.collect()` marks calendar reports partial unless both endpoints align exactly with midnight in `America/Los_Angeles`; learning requires an exact rolling window. The integration fixture deliberately uses midnight. For a normal midday post, waiting longer will not fix the calendar/window mismatch. Define and freeze a supported calendar-aligned evaluation policy, or provide a qualified source for the exact windows. Preserve honest metric-specific availability; do not relabel calendar totals as rolling data. This limitation is already partly documented and tested.
3. **The operator interface still requires technical JSON authoring.** Source observations and four-variant plans are JSON text areas. The default draft reuses source media and placeholder captions, not an automatically completed original-product adaptation. Asset/product assignment, copied source structure, voice selection, reference preparation and controlled copy dependencies need a guided editor for the requested nontechnical factory workflow. The UI does provide real commands; it is no longer the old empty shell.
4. **Financial and restore reconciliation lack a complete operator path.** Unknown generation charges retain reservations correctly, but the application/CLI has no clear invoice/evidence settlement workflow. Canvas's adapter does not emit an actual-credit amount for the production settlement hook. `activate-restore` requires unresolved work to be reconciled, yet prepared/non-submitted attempts and some failed workflows have no complete operator resolution path. Add reviewed accounting and attempt-resolution commands; never clear these holds automatically or restore spent headroom.
5. **Optional routes and elapsed analytics gates remain distinct.** Generated music and unqualified video reference modes remain unavailable; imported licensed music is supported. A fresh funded production scope, real publication qualification and actual 48-hour/7-day/28-day observations remain necessary. Full F-module/operator acceptance and legacy G-gates stay independent. Low-resolution fixture exports do not qualify production image quality, product identity or speaking quality.

## Documentation corrections and recommended sequence

The S8 evidence accurately demonstrates substantial offline functionality. Its broad finding-closure language and the completed-repair dev-log entry should now be supplemented with this follow-up. At minimum, reopen the affected acceptance areas listed in the issue index; preserve historical successful results. **Do not erase earlier evidence, equate test counts with complete behavior, or claim these defects are only live-qualification gaps.**

Recommended repair sequence:

1. N01–N06: current acceptance, truthful job outcomes, durable recovery and native receipt identity/concurrency.
2. N09–N11: complete local retry, delivery retry and fresh-root render recovery.
3. N07–N08 and N12–N17: speech dependencies, native requests, product/still handling and the actual frozen mix.
4. N18–N20: research coverage/cache, revision-aware learning and dashboard responsiveness.
5. Rerun the existing suite plus inverted versions of these probes, the public short/long application journeys and fault injection against the **native adapters with sanitized fake transports**. Then complete the separate operator/live gates under a current scope.

The report lists issues established in this review. It is not a guarantee that untested provider behavior or every legacy code path is defect-free.
