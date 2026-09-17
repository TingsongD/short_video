# Viral Video Factory — Detailed Implementation Modules

**Version:** 2.1 · **Status:** proposed development specification; no module below is certified complete by this document. Incorporates repository, acceptance-ownership and connector review findings.

Read the [main handover](viral-video-factory-handover.md) for product decisions and architecture. Use this document for implementation, the [validation runbook](viral-video-factory-validation-runbook.md) for reproducible tests, and the [module tracker](viral-video-factory-module-tracker.md) for actual progress. Existing production scripts are evidence and reusable components, not proof that the proposed factory has been implemented.

## How to build from this document

1. Complete F00, then work in dependency order. Each module is a separately reviewable change; split its numbered build steps further if necessary. Follow the main handover's R0/R1 milestones to demonstrate the local production slice early; a partially implemented module remains `in_progress` until all of its engineering checks pass.
2. Implement the service boundary and offline tests before attaching a paid provider or dashboard button. Put orchestration policy in services, provider protocol in adapters, and presentation in the UI.
3. Register the module's four manual scenarios with the F01 harness. A scenario prepares and exercises the real services; its human checks still require a reviewer. Follow the runbook's `cases`, `run`, `inspect` and `evidence` workflow. Those commands are **proposed**, not installed commands today.
4. Record engineering, manual and live status separately. A missing subscription or balance blocks only the affected live qualification. Downstream offline work may consume the same validated interface through a fake transport.
5. Complete the module gate, update its tracker row, then continue. When delivering an expressly scoped intermediate slice, validate its interface before use and record remaining module work. Full-suite checks happen at each completed module; do not call an unexecuted test a pass. G0–G12 remain independent legacy gates; F-module progress does not sign them.

**Path convention:** paths below are proposed unless explicitly marked existing. The factory package is `modules/factory/`; its new contracts belong in `modules/factory/contracts/v1/`, fixtures in `tests/factory_fixtures/`, and module tests in `tests/test_factory_<area>.py`. Frozen legacy `schemas/` and `tests/fixtures/` stay unchanged. Prefer small submodules behind the named public boundary over a single growing file.

**Contract convention:** every durable record has a schema version, stable ID, revision where applicable, creation time in UTC, and links to the exact input revisions. Media references use artifact IDs and hashes. Requests return typed domain errors with safe messages; unexpected errors retain a redacted diagnostic ID. Service methods never infer spend authority from the existence of credentials.

**Evidence convention:** each `Fxx-Mnn` below must produce the runbook's validation record, including expected versus actual results, source revision, fixture version, side-effect counts and cleanup. Store the module report under `docs/factory-reports/Fxx.md` and reference ignored large artifacts by hash/path. Rollback means disabling new dispatch and retaining history; it never means silently undoing an external effect.

**Working authority:** follow the main handover's [instruction and gate ownership rules](viral-video-factory-handover.md#23-working-instructions-and-acceptance-ownership), [checkpoint/data policy](viral-video-factory-handover.md#24-repository-checkpoint-and-runtime-data-policy) and [scope rules](viral-video-factory-handover.md#25-implementation-scope-and-live-authority). The assigned engineer proceeds with authorized offline implementation. Existing valid approvals retain their original scope; no new paid factory budget follows from these documents or from installed credentials.

## Build sequence

| Phase | Modules | Demonstrable exit |
| --- | --- | --- |
| P0 — Baseline | F00 | Reproducible starting state and known gaps |
| P1 — Foundations | F01–F08 | Durable, observable, budgeted fake work survives restart |
| P2 — Intelligence | F09–F14 | A source, products and approved blueprint yield four valid plans |
| P3 — Providers and audio | F15–F20 | Two fake video adapters and fitted audio share safe execution controls |
| P4 — Production | F21–F26 | Four real local fixture exports, QC, delivery and safe cleanup |
| P5 — Application | F27–F30 | A local operator can run, inspect, recover and back up the system |
| P6 — Distribution | F31–F33 | Publication records lead to coverage-aware, reproducible decisions |
| P7 — Qualification | F34–F35 | Failure drills pass and funded capabilities have scoped live evidence |

<a id="f00"></a>

## F00 — Baseline and engineer onboarding

**Prerequisites:** none. **Boundary:** establish facts and reproducibility; do not redesign existing workflows. **Deliverables:** `docs/factory-reports/F00.md`, accepted source checkpoint, classified working-tree inventory, dependency/version inventory, actual test result, frozen-file digests, runtime-data ignore/backup evidence and initial R0/R1 scope estimate.

### Build checklist

1. Read `GOAL.md`, `BUILD_PLAN.md`, `AGENTS.md`, current progress/gates and the main handover. Record the assigned offline implementation scope and single-builder workflow. Add scope banners identifying the superseded swarm ownership/branch/Wave 1 restrictions, while preserving contract/test/secret/completion rules. Preserve the working `.env` precedence and official Canvas route; do not restart the historical M1 build sequence or require duplicate implementation approval.
2. Follow the checkpoint procedure in main Section 2.4. Inventory tracked and untracked changes, including `LONGFORM_PLAN.md`'s observed deletion, runtime ledger, batch code/tests and all handover/pilot reports. Review changes before separate local code/test and documentation commits; preserve unrelated work in its checkout if using an isolated factory worktree. Inventory reusable Canvas/batch, audio, Hypit, Drive and analytics entry points.
3. Run the existing `make test` offline. Record actual count and failures; the historical 344-test result is context, not today's result. Resolve baseline failures separately before feature work.
4. Record Python, FFmpeg/ffprobe, Node, pinned Hypit and installed Canvas versions. Separate required local render tools from optional live integrations. Record credential presence/readiness only, never values.
5. Hash frozen schemas and fixtures, pin new dependencies in the project's chosen lockfiles, and document clean-machine installation. Record unsupported OS assumptions rather than promising Windows support from a macOS pilot.
6. Implement/test the exact runtime ignore policy from main Section 2.4. Keep `data/costs/.gitkeep` tracked, preserve and privately back up `ledger.json`, and ignore the factory database/media and QA workspaces. Record backup hashes, data root, available disk and recovery steps. Never reset financial state as cleanup or stage private runtime evidence.
7. Record separate G0–G12 and F00–F35 starting statuses, add reciprocal scope links, and map shared historical evidence without signing either gate implicitly. Record the accepted revision/diff manifest and estimate R0/R1 from component reuse and implementation uncertainty; document the first four-fixture-export demonstration before the full application scope.

### Automated validation

Existing suite stays green; configuration loading uses a temporary environment and preserves nonempty environment > `.env` > TOML; frozen inventory matches; ignore checks cover ledger/QA/SQLite paths and the tracked `.gitkeep` exception. Verify no private runtime file is staged. Subsequent F01 registration must retain this module's baseline evidence.

### Manual tests

| Case | Actions | Expected result |
| --- | --- | --- |
| F00-M01 | Follow the documented setup in a clean environment; run the existing offline suite and render-tool version checks. | Another engineer can reproduce the baseline; missing dependencies have exact installation steps. |
| F00-M02 | Use temporary configuration with all live credentials absent; inspect baseline readiness. | Offline development remains available; each live service is shown as unavailable without attempting login or generation. |
| F00-M03 | Compare the classified Git inventory, accepted checkpoint and frozen hashes before/after orientation. Inspect the deleted-plan disposition, separate commit contents, ignore checks, ledger hash and report redaction. | Every intended change is explained; unresolved/unrelated work is preserved; frozen files and ledger contents are unchanged; runtime data is not staged. |
| F00-M04 | Restore the baseline backup, including spending records and required untracked material, into a new ignored directory. Check source/artifact hashes and read the G/F scope links. | Restore preserves spending history without overwriting current work; evidence names the accepted source snapshot; a factory pass cannot silently sign a legacy gate. |

**Gate and rollback:** baseline report and reviewed reproducible source checkpoint are complete, tests are green, runtime records are backed up/ignored, and gate ownership is explicit. Keep factory features disabled. No live test is required. A dirty tree does not prevent initial inspection/testing, but unreviewed changes cannot be silently incorporated into the accepted baseline. A failing baseline is a recorded engineering blocker.

<a id="f01"></a>

## F01 — QA harness, deterministic fixtures and fake providers

**Prerequisites:** F00. **Boundary:** reproducible verification infrastructure; no production workflow policy. **Paths:** `qa/`, `testing/`, `tests/factory_fixtures/`, `tests/test_factory_qa.py`.

**Inputs → outputs:** case ID, isolated workspace, fixture version and fault script → actual service calls, durable fake-provider effects, assertions and evidence. Implement the [runbook's CLI contract](viral-video-factory-validation-runbook.md#3-proposed-qa-interface--implement-in-f01) first. Later modules register their cases as their services become available.

### Build checklist

1. Create a versioned fixture manifest containing expected hashes, durations, frame counts and assertions. Generate small local audio/picture fixtures with declared licenses or synthetic content.
2. Implement `init`, `cases`, `run`, `inspect` and `evidence`. Refuse occupied workspaces, unknown cases and unmet prerequisites. Return actionable nonzero exits; never return a placeholder pass.
3. Inject time, randomness, HTTP transports, subprocess runners and provider interfaces. Offline mode excludes production credentials and denies unexpected outbound traffic. Allow only explicitly selected loopback services and local render tools.
4. Persist fake remote operations independently of the application database. Record submit, poll, download, charge, upload and publish counts. Support the named failure scripts in the runbook.
5. Add worker checkpoints that allow the harness to stop its own process and restart it. Status edits in a fixture alone do not prove recovery.
6. Export sanitized evidence with hashes, assertions and outstanding human verdicts. Add a manual-result recording path requiring reviewer identity, timestamp and artifact revision.

### Automated validation

Test CLI exit codes, fixture repeatability, real service invocation, blocked unexpected network, workspace containment, persisted fake effects after application restart, evidence redaction and missing-prerequisite behavior. Keep all subsequent fixtures additive outside frozen directories.

### Manual tests

| Case | Actions | Expected result |
| --- | --- | --- |
| F01-M01 | Initialize `core-30s`, list implemented cases, execute the harness self-check and inspect its effect log. Repeat with the same run identity. | Deterministic data and stable identity; repeat invocation does not duplicate external effects. |
| F01-M02 | Run a case whose module is absent, then use an unknown fault name and an occupied initialization path. | Three explicit errors; existing files survive; no synthetic pass or arbitrary fault execution. |
| F01-M03 | Trigger fake acceptance followed by a lost response, stop the owned QA process and restart it. | Fake provider retains the operation; evidence distinguishes provider acceptance from application acknowledgement. |
| F01-M04 | Inspect an exported report before and after entering the human visual verdict. | Automated checks can pass while manual status is pending; final report includes reviewer and exact artifact hash. |

**Gate and rollback:** harness and fixtures are usable with zero external calls. Missing future cases remain `not_implemented`. Disable live mode until authorization services exist; retain fixture versions so older evidence remains reproducible.

<a id="f02"></a>

## F02 — Factory contracts and immutable revisions

**Prerequisites:** F01. **Paths:** `contracts/v1/`, `domain/`, `tests/test_factory_contracts.py`. **Boundary:** meaning and validation of records, independent of storage and providers.

**Records:** Seed, MetricObservation, ProductSnapshot, ReferenceBlueprint, FormatTemplate, ExperimentRevision, VariantPlan, GenerationRequest, PriceAssessment, Authorization, Job/Attempt, Artifact, Review, Delivery, Publication, Readback and Decision. Use the main handover's entity model; add explicit IDs/revisions where examples are abbreviated.

### Build checklist

1. Define schemas, typed constructors and validation errors. Specify required, optional and nullable fields separately; missing views are not zero views.
2. Use integer frame boundaries and rational frame rates. Define end-exclusive intervals and conversions from source time to target frames. Permit 20+ takes and long references.
3. Make accepted plans immutable. Editing yields a new revision with parent, reason, content hash and invalidated downstream records. Represent artifact selection separately from the immutable artifact.
4. Freeze provider policy, products, voice, music and permitted changed regions in each experiment revision. Store both the declared treatment and its allowed dependency changes.
5. Define provider-neutral generation/provenance fields, typed money and job transition errors. Keep raw provider receipts in referenced artifacts rather than unbounded public records.
6. Add an explicit legacy conversion validator. Return a compatibility report for unsupported durations, take counts or provenance. Vertex artifacts cannot be mislabeled `manual` or `jimeng` to fit a legacy enum.

### Automated validation

Validate positive/negative fixtures for every public record; unknown schema versions; rational clocks; overlapping/gapped intervals; immutable updates; malformed IDs; NaN/negative money; null observations; legacy conversion refusal. Snapshot canonical serialization and hashes.

### Manual tests

| Case | Actions | Expected result |
| --- | --- | --- |
| F02-M01 | Validate the 30-second six-beat experiment and the 169.7-second 20-take plan; inspect frame totals. | Both accepted; totals are 900 and 5,091 at 30 fps. No legacy 4–7-shot limit leaks into factory validation. |
| F02-M02 | Introduce one overlapping frame, unknown provenance and a zero denominator represented as a computed ratio. | Field-specific errors identify each problem; invalid records do not enter the accepted plan. |
| F02-M03 | Accept A, then edit one hook and attempt to overwrite the accepted revision. | In-place edit fails; an explicit child revision records the change and invalidates dependent pricing/reviews. |
| F02-M04 | Convert a compatible Jimeng example and an incompatible Vertex/long-haul example to legacy contracts. | Compatible output validates; incompatible conversion returns reasons without changing frozen schemas. |

**Gate and rollback:** every downstream record has a documented validator and fixture. New schema versions require explicit migrations; retain readers for stored versions or provide an audited upgrade tool. No live qualification applies.

<a id="f03"></a>

## F03 — SQLite store and migrations

**Prerequisites:** F02. **Paths:** `store/`, `migrations/`, `tests/test_factory_store.py`. **Boundary:** atomic persistence, transaction boundaries and query interfaces; no remote work inside transactions.

### Build checklist

1. Map immutable entities/revisions and mutable execution projections to tables. Add foreign keys, unique revision keys, job-attempt uniqueness and indexes for ready jobs, unfinished operations and event cursors.
2. Use WAL, bounded busy handling and short transactions. Store creation/update timestamps and monotonic version fields for optimistic concurrency.
3. Expose repositories through a unit-of-work interface. An accepted state transition and its event must commit together. Write external intents to a transactional outbox before dispatch.
4. Implement ordered migrations, schema-version checks, pre-migration backup and forward compatibility refusal. An older binary must not reinterpret a newer database silently.
5. Register file metadata only after atomic file promotion. Detect an interrupted promotion and distinguish an unreferenced temporary file from a referenced missing artifact.
6. Provide safe read-only inspection/export and SQLite-aware backup/restore verification. Do not copy only the main database while ignoring live WAL contents.

### Automated validation

Exercise transaction rollback, concurrent writers, unique constraints, compare-and-swap conflicts, outbox/event atomicity, migration from every supported version and restore into a separate path. Inject failure at each transaction boundary.

### Manual tests

| Case | Actions | Expected result |
| --- | --- | --- |
| F03-M01 | Create an experiment, restart the service, inspect revisions and events. | Stable IDs, counts and input links survive; projections match durable history. |
| F03-M02 | Launch two writers against the same expected revision. | One succeeds; the other receives a stale-revision conflict, never an unnoticed overwrite. |
| F03-M03 | Stop the owned process between intent creation and dispatch, then restart. | Committed intent is visible for reconciliation; rolled-back data has no partial child records. |
| F03-M04 | Back up an active fixture database, restore elsewhere and try an unsupported schema version. | Consistent restore passes integrity checks; unsupported versions fail before writes. |

**Gate and rollback:** crash-consistent storage, verified restore and migration evidence. Disable writes before rolling back application code; restore a database only after reconciling external effects created after the backup. Never drop operation history to make a migration pass.

<a id="f04"></a>

## F04 — Artifact registry, media intake and provenance

**Prerequisites:** F03. **Paths:** `artifacts/`, `media/probe.py`, `tests/test_factory_artifacts.py`. **Reuse:** existing `modules/common/video_reference.py` and media validation helpers after checking their contracts.

**Input → output:** local file or downloaded bytes plus source context → registered Artifact with SHA-256, byte count, true media type, stream properties, provenance and safe storage path.

### Build checklist

1. Stage imports in an owned temporary directory, stream hashes while copying, probe with bounded timeouts and atomically promote valid files. Treat extension and HTTP MIME as hints.
2. Record native width/height, frame rate, picture frame count, video/audio durations, codecs, sample rate and channels separately. Preserve VFR/source timing metadata.
3. Store original bytes and derived versions separately with transformation metadata. An upscale must retain native generation resolution in provenance.
4. Check requested type, minimum resolution and usable duration before asset selection. Return missing/invalid shot lists for empty folders instead of exceptions.
5. Deduplicate bytes without erasing distinct source attributions. Signed URLs may expire; retain their source identifier and safe refresh route, not tokens in reports.
6. Serve media only by registered artifact ID with containment checks. Reject symlink escapes, traversal and arbitrary filesystem URLs. Add reference counts for later retention rules.

### Automated validation

Use `reference-defects`: image renamed MP4, corrupt/zero files, short clips, mismatched streams, VFR, duplicate bytes, missing audio, interrupted downloads and unsafe paths. Verify failed files never become accepted assets.

### Manual tests

| Case | Actions | Expected result |
| --- | --- | --- |
| F04-M01 | Import valid portrait footage twice from different source records; inspect bytes and provenance. | One reusable blob may exist, with both source records preserved and measured stream facts visible. |
| F04-M02 | Import a thumbnail as video, corrupt media and a clip shorter than its allocation. | Each is rejected with an actionable reason; no playable-video badge appears for a still. |
| F04-M03 | Interrupt file transfer, restart intake and inspect registry/temp files. | No half-written accepted artifact; recovery reuses verified bytes or retries download without regeneration. |
| F04-M04 | Request an unknown artifact, traversal path and symlink outside the QA root. | Access is refused; registered media still streams successfully and secrets remain inaccessible. |

**Gate and rollback:** all accepted media has measured properties and provenance; invalid inputs remain reviewable without entering rendering. Delete only unreferenced owned temporary files. No live provider call is needed.

<a id="f05"></a>

## F05 — Prices, budgets, approvals and reservations

**Prerequisites:** F03. **Paths:** `budget/`, `tests/test_factory_budget.py`. **Reuse:** inspect `modules/orchestrate/ledger.py` and approval helpers; add factory accounting without rewriting historical dollar records.

**Input → output:** exact immutable work plan, dated PriceAssessments and Authorization → atomic reservations, settlement records and remaining authority in each original unit.

### Build checklist

1. Model Jimeng credits, other native credits and integer USD microdollars independently. Distinguish native quote, calculated estimate, provider-reported usage and invoice-confirmed charge.
2. Bind authorization to plan hash, providers/models, input modes, maximum units, validity and allowed repair/fallback scope. Credentials and old exhausted approvals confer no new allowance.
3. Reserve all applicable caps atomically: job category, provider sublimit and aggregate USD ceiling. Include unresolved attempts and commitments by all workers. Count reusable work once.
4. Recheck quote freshness, plan revision, authorized headroom and provider credit requirements immediately before dispatch. Explain which cap blocked a job.
5. Keep reservations for ambiguous submissions. Reconcile terminal outcomes using provider evidence; failed generation does not automatically mean free generation.
6. Expose read-only spend breakdown and approval-ready itemization. A local Vertex reservation is a control in this application, not a Google billing hard cap. Define conservative estimate bounds and variance handling before enabling a route.
7. Define legacy-ledger migration/reconciliation with source hash and stable import identities. Preserve original scope/period and distinguish settled history from unresolved commitments; do not count one entry twice or invent unused authority from an old ceiling. Keep the original ledger intact and make repeated import/restore idempotent.

### Automated validation

Test concurrent reservation races, integer boundaries, zero/unset caps, revoked/expired approvals, stale quotes, body/hash changes, cross-unit isolation, nested USD caps, refunds/unknown charges, repair limits, idempotent settlement and repeat legacy-ledger import/restore without restored spend headroom.

### Manual tests

| Case | Actions | Expected result |
| --- | --- | --- |
| F05-M01 | With a 100-credit authorization, concurrently reserve 60 and 50 credits; inspect reservations and provider calls. | Only one compatible reservation commits; total never exceeds 100; blocked work has zero submissions. |
| F05-M02 | Set $1 aggregate, $0.80 Vertex sublimit and $0.30 already committed elsewhere; request $0.75 Vertex. | Aggregate cap blocks it despite fitting the Vertex sublimit; credit balance does not pay the USD cost. |
| F05-M03 | Lose an acknowledgement after fake acceptance, restart and try another reservation consuming the same funds. | Original commitment remains held; restart cannot create spend headroom by forgetting the attempt. |
| F05-M04 | Approve a plan, change a prompt/model or expire its quote, then execute. Reprice and attach a valid revised authorization. | First execution blocks; only the exact newly authorized revision can proceed; history remains visible. |

**Gate and rollback:** reservation/settlement audit reconciles with fake effects under concurrency. No paid tests are required here. Disable dispatch on accounting uncertainty; preserve balances and receipts rather than deleting failed jobs.

<a id="f06"></a>

## F06 — Dependency scheduler, capacities and leases

**Prerequisites:** F05. **Paths:** `scheduler/`, `worker/`, `tests/test_factory_scheduler.py`. **Boundary:** select eligible work and own its lease; protocol-specific polling stays in adapters.

### Build checklist

1. Store a DAG of jobs with exact artifact/revision prerequisites. Detect cycles and unmet dependencies before accepting a plan. Mark blocked descendants with a useful reason.
2. Claim ready work transactionally with worker ID, lease expiry and fencing token. Every consequential completion/update verifies current ownership.
3. Enforce five global Jimeng slots, one initial Vertex slot per configured quota scope and one local render slot. Share capacities across experiments and variants; retain or conservatively account for unresolved accepted remote operations after worker lease expiry.
4. Separate dispatch, observation and download queues. A slow first submission must not prevent collecting later completed work. Prioritize recovery and collection without starving eligible new jobs.
5. Implement pause, drain and resume semantics. Pausing stops new submissions while accepted work can still be polled, downloaded and accounted for.
6. Gate new heavy local work on disk/memory policy. Use bounded poll/backoff and provider-specific throttle state. Browser presence and agent turns have no scheduling role.

### Automated validation

Test graph ordering/cycles, global capacities across multiple workers, stale-lease fencing, independent provider throttles, pause collection, fairness, low-resource conditions and queue progress after API/browser disconnection.

### Manual tests

| Case | Actions | Expected result |
| --- | --- | --- |
| F06-M01 | Queue 12 fake Jimeng, three Vertex and two render jobs across four variants; inspect active counts over time. | Limits are 5/1/1 globally; completion releases the correct slot and prerequisites release automatically. |
| F06-M02 | Make the first Jimeng job slow and the next four fast; pause dispatch. | Fast results are collected promptly; no new generation starts; slow accepted work remains observed. |
| F06-M03 | Stop one leased worker, start a replacement, then let the old worker attempt a completion update. | Replacement reconciles work; stale fencing token is rejected; no duplicate accepted operation. |
| F06-M04 | Simulate disk pressure and a Vertex-only quota throttle while Jimeng observation is healthy. | Heavy local starts/Vertex dispatch block with reasons; collection and unrelated healthy work continue. |

**Gate and rollback:** progress is independent of chat/browser activity and capacity is correct under restart. Disable scheduler dispatch to roll back; keep observation/reconciliation running for accepted jobs.

<a id="f07"></a>

## F07 — Submission recovery and retry policy

**Prerequisites:** F06. **Paths:** `execution/`, `recovery/`, `tests/test_factory_recovery.py`. **Boundary:** effect safety shared by video, TTS, music, upload and publishing adapters.

### Build checklist

1. Persist an intent with canonical request hash, attempt ID, authorization/reservation, target provider/account and recovery fields before crossing the network/process boundary.
2. Distinguish prepared, dispatching, accepted, running, succeeded, failed, unknown and downloaded states. Keep provider state and local collection state separate.
3. Classify failures: definitely before acceptance, confirmed terminal, ambiguous response, and retryable read/download. Only replay a write when non-acceptance is established or provider-supported idempotency is verified for that route.
4. Save operation IDs as soon as received; recover by the same ID. If response loss hides the ID and no reliable lookup exists, require explicit reconciliation. A local attempt ID alone does not make a provider idempotent.
5. Treat cancellation acknowledgement and terminal cancellation separately. Suppress competing fallback while original acceptance, charge or cancellation is unresolved.
6. Implement bounded retry policies with backoff, cause, next action and audit events. Human resolution attaches evidence; it cannot simply reset an ambiguous attempt to ready.

### Automated validation

Inject faults before dispatch, after remote acceptance, during acknowledgement persistence, polling, download and settlement. Validate effect counts, reservation continuity, monotonic attempts and original-ID resume. Test expired auth during observation separately from generation failure.

### Manual tests

| Case | Actions | Expected result |
| --- | --- | --- |
| F07-M01 | Accept fake generation, interrupt the worker before it stores the response, then restart. | One remote effect; state reconciles by supported lookup or remains explicitly unknown without resubmission. |
| F07-M02 | Save an operation ID, interrupt polling and resume twice. | Both resumes query the original ID; a new generation is never created. |
| F07-M03 | Complete generation but fail download, then retry collection. | Provider submit count stays one; only transfer repeats, with verified final bytes. |
| F07-M04 | Request fallback while original cancellation is pending, then provide terminal evidence and re-evaluate authorization. | Early fallback is blocked; later action follows explicit policy and preserves all prior costs. |

**Gate and rollback:** restart drill proves no blind duplicate effects. Every unresolved state has a documented operator action. Keep recovery readers compatible across code rollback; unresolved paid work cannot be discarded.

<a id="f08"></a>

## F08 — Events, timing and observability

**Prerequisites:** F06, F07. **Paths:** `events/`, `telemetry/`, `tests/test_factory_events.py`.

**Input → output:** committed job transitions and observations → ordered durable events, safe logs, timing breakdowns and resumable subscriptions. Observability must explain multi-hour gaps without reading an agent conversation.

### Build checklist

1. Assign monotonically increasing event IDs in the same transaction as state changes. Include experiment/variant/job/attempt/revision links and safe structured payloads.
2. Record planned, ready, claimed, dispatch-started, accepted, provider-finished-if-known, downloaded, review-started/finished, render-started/finished, uploaded, verified and cleaned timestamps.
3. Derive queue wait, provider-observed elapsed time, collection delay, review time, render time and total wall clock separately. Record observation uncertainty; do not invent a provider completion timestamp from the first poll that sees success.
4. Add redaction for credentials, confirmation tokens, OAuth codes, signed URLs and request bodies containing secrets. Logs contain artifact/receipt references rather than raw payload dumps.
5. Provide event replay from a cursor, gap detection, retention policy and a snapshot resynchronization route. SSE transport arrives in F27.
6. Add health signals for stale leases, unattended unknown attempts, prolonged ready waits, storage pressure and unresolved approvals. Alerts must identify an actionable owner/state.

### Automated validation

Check transition/event atomicity, monotonic order, duplicate delivery tolerance, cursor replay, retention gaps, simulated clock shifts, redaction and measured timing calculations. Use fake time instead of sleeping through minute-long tests.

### Manual tests

| Case | Actions | Expected result |
| --- | --- | --- |
| F08-M01 | Run a fixture with deliberate queue, provider, collection and review delays; inspect the timeline. | Each delay is attributed to its actual stage; totals reconcile without double counting overlapping jobs. |
| F08-M02 | Disconnect an observer, let work advance, reconnect with its last cursor. | Missing events replay once logically; snapshot and history agree. |
| F08-M03 | Include secret-shaped values in fake provider errors and signed URLs; export evidence. | Credentials/tokens are absent from logs, API payloads and reports; safe diagnostic references remain. |
| F08-M04 | Expire an event cursor and create a stale lease/unknown attempt. | Client gets explicit resynchronization instructions; health identifies the unresolved work and next action. |

**Gate and rollback:** every major step has useful timing and recovery evidence. Logs cannot be the only source of job truth. Retain durable events when replacing an observer or dashboard implementation.

<a id="f09"></a>

## F09 — Seed registry and source acquisition

**Prerequisites:** F04, F05. **Paths:** `seeds/`, `integrations/viral_outliers.py`, `tests/test_factory_seeds.py`. **Reuse:** `modules/common/video_reference.py`, `modules/radar/viral_client.py` and saved pilot source acquisition evidence.

**Input → output:** supported platform URL or manual media import → canonical Seed record, observed metadata, source Artifact and acquisition status. Metadata-only records remain useful for discovery but cannot pass audiovisual analysis readiness.

### Build checklist

1. Parse supported URLs into platform and post ID; normalize tracking parameters without conflating different posts. Keep original URL and attribution.
2. Separate resolution, metadata acquisition and media acquisition jobs with individual costs/cache policies. Follow each external call's authorization and reservation.
3. Validate returned content through F04. The Viral Outliers YouTube download route may return a thumbnail; report `needs_source_media` rather than silently analyzing it as a video.
4. Offer manual upload/local import and record source URL, user-supplied provenance and hash. A manual import resumes the same seed's blocked analysis dependencies.
5. Bound downloads, redirects and file sizes. Restrict automatic URL fetches to supported adapters; block private-network/metadata endpoints and unsafe redirects to prevent server-side request forgery.
6. Refresh expiring media links through the original acquisition adapter; preserve existing verified bytes. Resolve duplicate URLs/media without losing metric observation history.

### Automated validation

Canonicalization and deduplication; unsupported/private URLs; unavailable posts; metadata-only responses; thumbnail detection; expired links; interrupted transfer; paid lookup cache; manual replacement and stale downstream analysis invalidation.

### Manual tests

| Case | Actions | Expected result |
| --- | --- | --- |
| F09-M01 | Submit two URL forms for the same fake post; import its valid video and inspect the seed. | One canonical seed with both provenance observations and a usable source artifact. |
| F09-M02 | Resolve a YouTube seed whose download returns an image; open its readiness report. | Metadata remains available; analysis blocks with a clear video-import action. |
| F09-M03 | Supply a manual video for that seed, interrupt transfer once and resume. | Only verified media becomes the source; waiting analysis becomes eligible without another paid lookup. |
| F09-M04 | Try a private-network URL, unsupported redirect and expired signed source URL. | Unsafe fetches are refused; expiry uses the approved refresh path and redacts the token. |

**Gate and rollback:** actual source media is distinguishable from metadata everywhere. Live qualification is one authorized lookup/download or manual source import; zero API credits must yield a usable manual path. Preserve source snapshots when disabling an acquisition adapter.

<a id="f10"></a>

## F10 — Outlier discovery and baseline evidence

**Prerequisites:** F09, F05. **Paths:** `discovery/`, `tests/test_factory_discovery.py`. **Reuse:** `modules/radar/viral_scan.py`, `viral_records.py`, metrics/scanner helpers; inspect their fixed thresholds before reuse.

**Input → output:** niche/profile/search policy and research budget → ranked candidates with raw observations, denominator cohorts, confidence and reasons for inclusion/exclusion.

**Confirmed starting point:** legacy `modules/radar/metrics.py` and `scanner.py` already compute median baselines. The active Viral Outliers `viral_records.py` path uses the follower threshold and explicitly marks baseline unavailable; `viral_scan.py` retains follower-specific assumptions. Extend that active path and its persisted-plan validation. A `system.toml` switch alone cannot provide cohort evidence or implement all selection modes.

### Build checklist

1. Store views/followers and views/profile-baseline as independent metrics. Preserve provider-supplied outlier scores separately; do not relabel them as our computed ratio.
2. Build the preceding comparable-video cohort, excluding the seed, future posts and mixed formats where inappropriate. Default to 20–50 comparable posts; save every included/excluded ID, reason, observation time, mean and median.
3. Implement strict `views / followers > 2` and the separate configurable baseline threshold (recommended initial value 5). Define selection modes explicitly: follower, baseline, either or both.
4. Handle hidden/zero counts as unavailable, not infinity. Flag small samples, stale snapshots, mixed periods and unavailable engagement data. Do not call a historical ratio a current measurement.
5. Preflight research call costs and paginate within the authorized scan limit. Cache by query/observation age; record incomplete scans when credits run out.
6. Produce explainable rankings and export candidate IDs into F09. Selection does not automatically authorize generation.

### Automated validation

Exact threshold boundaries; 100× follower/50× baseline example; mean/median; seed exclusion; comparable-format filtering; null/zero; stale counts; partial pagination; cache invalidation; budget exhaustion and selection-mode persistence. Exercise follower/baseline/either/both through the actual Viral Outliers service with a fake transport and saved plan, not only the standalone math helper. Preserve the older scanner's documented behavior through regression tests.

### Manual tests

| Case | Actions | Expected result |
| --- | --- | --- |
| F10-M01 | Run `outlier-math` and inspect cohort rows and calculation inputs. | 1,000,000 / 10,000 = 100× followers; mean and median baseline ratios are 50×; seed excluded. |
| F10-M02 | Run 19,999, 20,000 and 20,001 views against 10,000 followers in follower-only mode. Then replay saved plans through the active Viral Outliers path using all four selection modes and contrasting baseline/follower results. | Only 20,001 passes strict >2; every mode applies its declared denominators and persists correctly; no hidden follower-only gate overrides it. |
| F10-M03 | Remove followers, shrink the cohort and mix stale/short-form observations. | Missing ratios stay null; confidence and exclusions explain why a strong-looking result may be unqualified. |
| F10-M04 | Exhaust fake research credits halfway through pagination, restart and inspect cached results. | Partial coverage is explicit; no automatic top-up or duplicate charged calls; manual seed intake still works. |

**Gate and rollback:** an engineer can recompute every ratio from stored evidence. Live API validation requires available research credits and an explicit ceiling; previous balance-zero evidence is not a funded plan. Roll back ranking policy by revision, retaining observations.

<a id="f11"></a>

## F11 — Shopify product and media snapshots

**Prerequisites:** F04, F05. **Paths:** `products/`, `integrations/shopify.py`, `tests/test_factory_products.py`. **Reference:** [existing Shopify investigation](shopify-product-assets.md). Existing pilot queries are examples, not a finished reusable importer.

**Input → output:** authorized shop reference plus product IDs/URLs or selection query → immutable ProductSnapshots, variant/media records, downloaded references and available factual claims.

### Build checklist

1. Implement read-only Admin GraphQL access through an injectable transport, with pinned API version verified at implementation. Keep the token in existing private configuration and avoid shop mutations.
2. Resolve storefront URLs to exact product/variant IDs. Paginate products and each nested media/variant connection; distinguish a completed inventory from a truncated page.
3. Store title, selected variant, options, current availability, description, observed price/currency, images, video sources and snapshot time. Sanitize HTML and retain source text separately.
4. Register downloadable media through F04, refreshing expired URLs as needed. Record actual views/angles supplied; a single image is not proof of a garment's back or hidden construction.
5. Separate popularity evidence from selection preference. Use only available, authorized metrics; if no sales/popularity metric exists, label a manual/merchandising choice rather than inventing best-seller status.
6. Build multi-product selection with deduplication, compatibility and availability warnings. Freeze product/variant snapshots in an experiment; catalog refresh creates new snapshots without altering a running video.

### Automated validation

All pagination paths; missing read scopes; image/video unions; expiring URLs; unavailable variants; duplicate products; rich text; missing angles; popularity provenance; no-write transport assertions; stale snapshot behavior.

### Manual tests

| Case | Actions | Expected result |
| --- | --- | --- |
| F11-M01 | Import the paginated fake catalog and select three products with specific variants. | All pages and media are accounted for; IDs, options and reference images match the selection. |
| F11-M02 | Select the image-only tank fixture and request a back-detail reference. | The missing angle is explicit; the system requests another asset or revises the shot instead of inventing a source. |
| F11-M03 | Expire one media URL and remove one read permission during refresh. | Existing snapshots remain usable; only affected refresh jobs block with safe reconnect/permission guidance. |
| F11-M04 | Update a product's price/availability after plan freeze and inspect both revisions. | Running plan remains bound to its snapshot; new claims require a revision and review. No Shopify mutation occurs. |

**Gate and rollback:** product identity, reference coverage and claims are traceable. Live qualification is a read-only authorized import and visual match; access to sales data is optional. Disabling Shopify preserves already imported snapshots and manual assets.

<a id="f12"></a>

## F12 — Reference analysis and blueprint review

**Prerequisites:** F09, F05, F06. **Paths:** `analysis/`, `blueprints/`, `tests/test_factory_blueprints.py`. **Boundary:** understand the actual source; template abstraction and new copy belong to later modules.

### Build checklist

1. Require verified source video and probe its picture/audio clocks. Extract review proxies, scene candidates, transcript/word timings, audio characteristics and representative frames without changing the source.
2. Run a bounded analysis job through an explicit worker interface. If using a multimodal service, record exact supported input mode, model/version, cost bound and artifact inputs. A chat turn is not a durable worker.
3. Produce a timed blueprint: hook, product reveals, shots, transitions, camera/framing, spoken pace/style, caption placement, music role, payoff/CTA and uncertainty. Link every observation to source time/frame evidence.
4. Distinguish observed source text from new copy to be authored. Describe speaking style using attributes; use a new selected voice and fictional/authorized presenter for the adaptation.
5. Add timeline review with accept/reject/edit by blueprint hash. Flag overlapping/gapped beats, untranscribed speech, unclear product actions and low-confidence scene changes.
6. Persist analysis attempts and partial outputs. On provider timeout, recover by F07; on manual correction, invalidate only dependent template/planning work.

### Automated validation

Transcript alignment; 20-take support; exact target-frame mapping; malformed analysis output; missing audio; thumbnail source refusal; time-bound evidence links; review revision mismatch and interrupted analysis recovery.

### Manual tests

| Case | Actions | Expected result |
| --- | --- | --- |
| F12-M01 | Analyze `core-30s`; watch/listen to source and compare all six beats, transcript and proposed boundaries. | Every beat has supporting timestamps; reviewer can correct and accept the exact blueprint revision. |
| F12-M02 | Analyze `long-haul-1697`, including first/last frame and each product transition. | Full 169.7-second structure survives; no forced short template or omitted final CTA. |
| F12-M03 | Supply a missing-audio/uncertain-scene fixture and inspect review status. | Unknown speech/music facts remain unknown; mandatory review is not auto-passed by a generic model verdict. |
| F12-M04 | Interrupt analysis, resume, then edit one boundary after acceptance. | Existing attempt is recovered safely; edited blueprint receives a new revision and dependent plans become stale. |

**Gate and rollback:** accepted blueprint is supported by watched/listened evidence. Live model qualification verifies actual audiovisual input handling on an authorized seed; text metadata analysis alone cannot satisfy it. Manual blueprint editing remains a usable fallback.

<a id="f13"></a>

## F13 — Reusable format and template authoring

**Prerequisites:** F12. **Paths:** `templates/`, `tests/test_factory_templates.py`. **Reuse:** legacy format-library functions only through explicit compatibility adapters.

**Input → output:** accepted blueprint → versioned FormatTemplate with timed slots, product/voice/caption constraints, transition rules and supported rendering capabilities.

### Build checklist

1. Separate reusable structure from source-specific names, transcript, presenter identity and imagery. Keep source attribution/evidence links.
2. Define slots for hook, product sections, proof/payoff and CTA, including minimum/maximum durations and required reference types. Preserve long-form slot counts when needed.
3. Add constraints for caption regions, safe zones, font assets, shot transitions, music timing and motion/effects. Use declarative parameters that the compiler can validate.
4. Define a renderer capability manifest. Mark the static haul subset eligible for the FFmpeg fast path; unsupported animation must route to Hypit or fail with a clear explanation.
5. Version template changes and run compatibility checks against existing plans. Keep candidate/proven/retired lifecycle separate from technical validity; F33 owns promotion evidence.
6. Provide a fixture preview/export and a readable template inspection view before building the full dashboard.

### Automated validation

Slot duration bounds; missing required references/fonts; total coverage; transition handles; unsupported effects; source-content leakage checks; version changes and legacy export refusal where richer structure cannot fit.

### Manual tests

| Case | Actions | Expected result |
| --- | --- | --- |
| F13-M01 | Build a template from the accepted haul blueprint and substitute synthetic product/copy slots. | Overall rhythm and structure remain; source names, presenter and exact copy are not embedded defaults. |
| F13-M02 | Try a slot allocation shorter than required speech and a transition without handles. | Validation identifies the offending slot and required adjustment before generation. |
| F13-M03 | Preview a static composition and an animated overlay composition. | Capability report routes each correctly; unsupported animation is never silently discarded. |
| F13-M04 | Revise caption placement, then reopen a plan bound to the previous template revision. | Historical plan retains its original appearance; migration requires an explicit revision. |

**Gate and rollback:** first haul template can be instantiated without manual source-code edits. Template quality remains candidate until measured evidence exists. Roll back by selecting an older valid version, preserving already rendered artifacts.

<a id="f14"></a>

## F14 — Experiment, control and treatment planning

**Prerequisites:** F11, F12, F13, F05. **Paths:** `experiments/`, `planning/`, `tests/test_factory_experiments.py`.

**Input → output:** accepted blueprint/template, product snapshots and research policy → immutable A/B/C/D ExperimentRevision, scripts, timing allocations, treatment declarations and approval-ready preview.

### Build checklist

1. Author original product-grounded copy and a close structural adaptation A. Freeze total picture duration, selected products, presenter, voice, music, provider policy and template revision.
2. Branch B, C and D independently from A: one hook, one body benefit/copy segment and one ending/CTA respectively. Each declares a hypothesis, primary metric and exact end-exclusive changed frame intervals.
3. Include dependency changes in the treatment: speech, captions, lip-synced picture and transition handles. If a crossfade affects extra frames, enlarge the declared interval before approval.
4. Keep unchanged script/media selections identical. Reject undeclared product, voice, music or provider/model changes. If control needs repair, revise it and rebase all affected variants explicitly.
5. Produce a semantic and timing diff for operator review, cost impact of unique work, uncertainty/claim flags and decision policy. Incomplete analysis or unsupported shot requirements block acceptance.
6. Freeze the accepted revision and authorization link. Copy edits after freeze create a new plan and invalidate affected quotes/reviews; they do not silently replace accepted work.

### Automated validation

Four branches with the same parent; interval coverage; immutable locks; original-copy/product-claim constraints; zero/multiple treatments; transitive audio/picture dependencies; baseline rebase; plan hash/price invalidation and 20-take planning.

### Manual tests

| Case | Actions | Expected result |
| --- | --- | --- |
| F14-M01 | Build the canonical 30-second experiment and inspect all scripts and frame diffs. | A is 900 frames; B changes 0–120, C 360–510, D 780–900 only; all branch from A. |
| F14-M02 | Change music in B and product selection in C without declaring them. | Both plans fail the one-variable policy; the UI/service explains the extra change. |
| F14-M03 | Replace C's narration in a lip-synced shot and inspect dependencies. | Caption/alignment/picture changes are included inside C's declared region; stale mouth motion cannot be reused. |
| F14-M04 | Accept all variants, revise A's product claim and attempt execution using old approval. | Affected branches/prices/reviews become stale; execution waits for the revised accepted plan. |

**Gate and rollback:** a reviewer can identify the single intended change in each branch and every locked control variable. Live generation is unnecessary. Restore an earlier accepted revision by selection, never by rewriting history.

<a id="f15"></a>

## F15 — Shared generation contract and provider routing

**Prerequisites:** F14, F05, F07. **Paths:** `providers/base.py`, `providers/router.py`, `providers/catalog.py`, `tests/test_factory_routing.py`.

**Adapter interface:** `readiness`, `capabilities`, `validate`, `price`, `prepare`, `submit`, `observe`, `download`, `reconcile`; optional `cancel` declares its semantics. Separate side-effect-free validation from remote node preparation, which may itself need recovery. Return typed results including native IDs and pricing kind.

### Build checklist

1. Define a neutral GenerationRequest with prompt, reference artifact IDs/roles, desired output, requested duration, audio policy and immutable plan identity. Keep provider payloads inside adapters.
2. Store dated capability snapshots by provider/account or project/model/location/input mode. Distinguish advertised, observed and production-qualified support.
3. Validate aspect, native resolution, duration choices, reference count/types and audio support before pricing. Round duration upward only where a supported choice covers the allocation; otherwise split/replan explicitly.
4. Implement explicit Jimeng, explicit Vertex and prefer-Jimeng-with-approved-Vertex-fallback policies. The plan must name allowed routes, ceilings and confound handling.
5. Block unsupported/unqualified routes and fallback from accepted/running/unknown/cancellation-pending work. Reuse F05/F07 rather than adding adapter-local approval/retry policies.
6. Include provider/model/location/input mode/settings/reference hashes in cache identity and audit. Return explanatory routing decisions for the dashboard, including why a cheaper or faster route was not eligible.

### Automated validation

Same request against two fake adapters; different duration catalogs; unsupported image/video reference modes; exact versus rounded allocation; stale catalogs; provider/model lock; fallback eligibility; independent credits/USD and no implicit upgrade.

### Manual tests

| Case | Actions | Expected result |
| --- | --- | --- |
| F15-M01 | Route supported requests explicitly to each fake provider and inspect validated payload summaries. | Provider-specific settings are correct; both return the same factory artifact/provenance contract. |
| F15-M02 | Request an unsupported duration/reference combination or an unqualified Veo mode. | Submission count is zero; required replan/qualification is explained. |
| F15-M03 | Exhaust Jimeng balance with Vertex allowed in policy but no USD authority, then add a valid scoped authorization. | First route blocks; second may reserve and proceed only if all qualification/treatment rules pass. |
| F15-M04 | Make the original attempt unknown and offer an otherwise eligible fallback. | Fallback remains blocked; no two providers generate competing paid replacements. |

**Gate and rollback:** routing is deterministic from saved plan, capability evidence and authorization. Both fake adapters must pass before attaching live calls. Disable a route without invalidating already accepted operations; keep its observation path available.

<a id="f16"></a>

## F16 — Official Jimeng Canvas adapter

**Prerequisites:** F15. **Paths:** `providers/canvas.py`, `tests/test_factory_canvas.py`. **Reuse:** `modules/assets/canvas_cli.py`, `canvas_models.py`, `canvas_state.py`, `canvas.py` and `modules/batch/canvas.py`. Read the installed Canvas Skill and live CLI schema during implementation; preserve native login storage.

### Build checklist

1. Wrap the official CLI with an injectable command runner, bounded timeouts, structured JSON parsing and redaction. Report CLI version, region/account and authentication readiness safely.
2. Discover live models/parameters; the historical fast option is `seedance_2.0_fast_vip`, not a promise of permanent availability. Pin the accepted model/settings per plan.
3. Create/reuse the planned canvas and nodes, persisting their IDs and request hashes before running paid jobs. Map variant/shot references explicitly and avoid accidental duplicate nodes on restart.
4. Obtain native quotes and use Canvas credit controls for authorized dispatch. Keep transient credit-confirmation tokens out of project state/logs. Serialize sensitive CLI preparation if required while allowing the approved five remote generations globally.
5. Observe/wait by saved IDs; distinguish acceptance, terminal failure, downloaded and validated. Download through the CLI and register/probe resulting media. A CLI timeout is not proof generation failed.
6. Support manual asset import for blocked shots. Prompt/settings changes require a new explicit attempt; select valid completed artifacts for reuse. Preserve the independent `dreamina` diagnostic installation.

### Automated validation

CLI missing, expired login, malformed JSON, wrong region, unsupported model, quote changes, partial batch acceptance, lost response, restart, credit rejection, download failure, corrupt media and CLI log redaction. Assert no real CLI execution in offline tests.

### Manual tests

| Case | Actions | Expected result |
| --- | --- | --- |
| F16-M01 | Run readiness and prepare/quote through the fake runner; inspect canvas/node IDs, pricing and safe output. | Preparation is recoverable; no generation occurs before valid authority; credit units remain native. |
| F16-M02 | Accept only two jobs from a five-job fixture, then interrupt the runner. | Accepted IDs are preserved; remaining jobs are not mislabeled running; recovery creates no duplicate submissions. |
| F16-M03 | Expire login during observation, reconnect the fake account and resume a failed download. | Original operation IDs are observed; download retry does not regenerate; wrong-account reconnection is rejected. |
| F16-M04 | Complete the scoped live readiness/one-shot qualification when funded, then watch/probe/download the result and verify its quote/receipt. | Exact model/mode is qualified with evidence, or live status remains blocked; offline success alone never qualifies it. |

**Gate and rollback:** offline adapter contract and recovery pass. Live gate uses an existing valid authorization with available balance; previous spent ceilings are not reusable. Disabling dispatch leaves accepted Canvas work recoverable and manual import available.

<a id="f17"></a>

## F17 — Google Vertex video adapter

**Prerequisites:** F15. **Paths:** `providers/vertex.py`, `providers/vertex_auth.py`, `tests/test_factory_vertex.py`. **Required reference:** [recorded Vertex pilot](vertex-video-test.md).

### Build checklist

1. Implement native OAuth credential loading/refresh through the configured Cloud identity and project; redact tokens. Distinguish API-key-only configuration, expired login, wrong project, missing permission and quota failures. `GEMINI_TTS_VERTEX_API_KEY` is not proven authentication for this video route.
2. Start with the recorded Omni route: `gemini-omni-1.1-flash-preview`, `global`, asynchronous Interactions. Recheck its current schema before live use and pin the tested adapter route. Veo requires a separate protocol implementation and qualification; catalog listing is insufficient.
3. Persist intent before POST and the interaction ID immediately after acknowledgement. Treat HTTP 200 as acceptance only. Poll the same ID; parse terminal errors even when the HTTP request succeeded.
4. Implement validated inline video decoding and optional explicitly configured Cloud Storage output. The pilot's URI-delivery request without a bucket failed; do not reintroduce that default.
5. Bound estimated input/output/reasoning cost from a dated rate snapshot and request limits, reserve the Vertex sublimit and aggregate USD ceiling, then record reported usage separately from invoice evidence.
6. Probe native media; preserve the pilot's 24 fps/native-resolution provenance and normalize only downstream. Strip/select generated audio according to plan so ElevenLabs speech is not doubled.
7. Qualify text-only, product-image, presenter/reference and seed-video modes separately. A generic tank prompt in the smoke test did not validate real Shopify fidelity or seed imitation.

### Automated validation

OAuth expiry; wrong project; API-key-only rejection; exact payload shape; HTTP-200 terminal error; missing output; malformed/oversized base64; usage absence; same-ID polling; ambiguous POST; quota backoff; estimate variance and native-audio policy.

### Manual tests

| Case | Actions | Expected result |
| --- | --- | --- |
| F17-M01 | Replay the sanitized successful and failed pilot response shapes through fake transport. | Accepted/error/completed states differ; only valid media becomes an artifact; usage remains labeled an estimate. |
| F17-M02 | Expire OAuth after acceptance, reconnect the same configured identity and restart observation. | Same interaction ID resumes; no new POST; project/model/location remain visible and unchanged. |
| F17-M03 | Lose the POST response and request a retry/fallback; separately fail only the download. | Ambiguous POST remains unresolved without duplicate generation; known-success download can safely retry. |
| F17-M04 | Under a valid live ceiling, run one exact intended product-reference mode, inspect product/presenter fidelity, audio and native media, and attach receipts. | Only that tested model/location/mode becomes qualified; unsupported or unsuccessful modes stay disabled. |

**Gate and rollback:** both fake success and failure paths pass and price/auth limitations are visible. Existing text-only pilot may support that narrow readiness claim; it does not complete F17's new production adapter tests. Keep polling existing interactions after disabling new Vertex dispatch.

<a id="f18"></a>

## F18 — Product, presenter and outfit references

**Prerequisites:** F11, F14, F16. **Paths:** `references/`, `tests/test_factory_references.py`. **Boundary:** prepare accepted visual references before video work. Manual/reused references can complete offline while Canvas live generation is unavailable.

### Build checklist

1. Build a reference pack per selected product/variant and presenter, with source artifacts, permitted transformations and evidence for visible details. Keep product images separate from style/scene references.
2. Support manual import and reuse first; integrate authorized Canvas image generation where necessary using F16/F05/F07. No Vertex image-generation capability is implied by its video pilot.
3. Define a fictional or otherwise authorized presenter identity and continuity guide: appearance, setting, framing and wardrobe. Avoid embedding the seed presenter or source overlays into new references.
4. Validate garment color, pattern, silhouette, selected variant and visible construction against source images. Missing views remain uncertainty; request assets or revise the framing.
5. Store acceptance/rejection by exact artifact hash with reviewer, reasons and limits. Rejected references cannot feed paid picture jobs; replacements are new attempts within repair authority.
6. Reuse accepted references across A/B/C/D and shots where the locked variables are unchanged. Changing presenter/product reference invalidates downstream generation and relevant reviews.

### Automated validation

Reference-role/type checks; source/variant mapping; cache identity; stale review hashes; rejected-reference dependencies; image-generation credit reservation; manual-import parity and repair-attempt limits.

### Manual tests

| Case | Actions | Expected result |
| --- | --- | --- |
| F18-M01 | Assemble a three-product pack from fixture images and one presenter reference; compare each selected variant visually. | Every usable reference has a source and explicit acceptance; unchanged variants share its hash. |
| F18-M02 | Introduce wrong checkerboard geometry, an invented back detail and copied source overlay. | Reviewer rejects the affected references with specific reasons; dependent picture jobs cannot dispatch. |
| F18-M03 | Interrupt one fake image request, recover it and select a corrected accepted artifact. | Original attempt/cost remains recorded; the selected reference changes explicitly without duplicate submission. |
| F18-M04 | Replace the presenter reference after some shots are accepted. | System lists affected shots/reviews and requires an explicit plan revision; it cannot silently mix identities. |

**Gate and rollback:** accepted reference pack supports the intended framing. Live image qualification is scoped to the exact model/route and budget; manual references are a valid implementation path. Restore prior accepted selections while retaining rejected evidence.

<a id="f19"></a>

## F19 — TTS, speech fitting and alignment

**Prerequisites:** F14, F07. **Paths:** `audio/speech.py`, `audio/alignment.py`, `tests/test_factory_speech.py`. **Reuse:** `modules/voice/tts.py`, `modules/batch/audio.py`, `modules/script/voicetext.py` after checking segmentation and recovery behavior.

### Build checklist

1. Normalize the new script without exposing markup as speech. Bind voice ID, model, language, style settings and normalization version to each segment's identity. Use ElevenLabs v3 as the selected primary route; qualify any alternate separately.
2. Submit through shared budget/intent/recovery controls. Record native credit estimates/usage where available; missing acknowledgements must not trigger blind TTS regeneration.
3. Measure speech and align words to the exact returned waveform. Store word timing, spoken text, original audio hash and confidence. If an alignment service is used, it has its own budget and retry rules.
4. Fit each segment to its target frame interval using documented limits for silence trimming, padding and modest time adjustment. If speech cannot fit intelligibly, revise copy or regenerate within authorization; never truncate words to force duration.
5. Derive captions from the final approved wording/alignment. Create an explicit mapping after speed/padding transforms. Lip-synced picture requests must reference this same approved speech version.
6. Cache unchanged segments across variants. Preserve voice and processing outside changed regions; a full-track stochastic reread is not an acceptable way to change only a hook.

### Automated validation

Entity/markup normalization; segment cache keys; timing transforms; too-long/short speech; word-boundary joins; ambiguous request; missing alignment; voice/model locks; native credit accounting and exact unchanged PCM/provenance.

### Manual tests

| Case | Actions | Expected result |
| --- | --- | --- |
| F19-M01 | Build A's fixture speech, listen through all joins and compare word highlighting with audio. | Clear wording, complete sentences and aligned captions; final timeline matches the allocated picture frames. |
| F19-M02 | Supply speech too long for the hook and a segment with excessive silence. | Small allowed adjustments are documented; excessive fitting blocks for copy revision rather than clipping words. |
| F19-M03 | Replace B's hook and compare all other narration segments by hash and listening. | Only declared hook speech/alignment changes; voice settings and other segments are identical. |
| F19-M04 | Accept fake TTS but lose its response, restart, then separately test download failure. | Unknown submission is reconciled or blocked; known audio transfer retries without another paid synthesis. |

**Gate and rollback:** speech is intelligible and timings are evidenced. Live voice/style qualification requires a scoped synthesis authorization; the historical voice choice is a starting configuration, not blanket permission. Select earlier approved speech explicitly when rolling back.

<a id="f20"></a>

## F20 — Music, sound and shared mix

**Prerequisites:** F19. **Paths:** `audio/music.py`, `audio/mix.py`, `tests/test_factory_music.py`. **Reuse:** existing music/audio preparation only after checking exact-duration and shared-region behavior.

### Build checklist

1. Support imported/licensed local music and authorized existing music-generation routes. Preserve source/license or generated-model provenance. Describe the seed's energy, rhythm and arrangement to create a suitable original bed.
2. Submit generation through F05/F07 with its own service/model/credential requirements. Vertex video OAuth setup does not automatically qualify every Google music route.
3. Measure BPM/structure where supported and construct an exact-duration bed using declared trims, loops and crossfades. Inspect loop boundaries rather than masking gaps with excessive narration.
4. Freeze one music master, placement, gain envelope, channel layout and mix profile for the experiment. Variant copy changes must not unexpectedly alter music elsewhere through whole-track normalization or ducking.
5. Mix speech/music with explicit sample rate, gain, clipping/true-peak policy and loudness target selected during fixture qualification. Record measured outputs; do not invent a universal platform loudness requirement.
6. Keep optional sound effects as separate timed assets. Changes require treatment scope and budget, and must not leak into unchanged comparison regions.

### Automated validation

Exact sample counts; duration fitting/crossfades; stereo/mono conversion; silent/missing music; clipping; deterministic frozen mix; unchanged-region audio evidence; generation recovery and route-specific authentication errors.

### Manual tests

| Case | Actions | Expected result |
| --- | --- | --- |
| F20-M01 | Build a 30-second and 169.7-second bed; listen at every loop, start and end. | Exact intended duration, smooth joins and an intelligible speech/music balance with measured levels. |
| F20-M02 | Mix an over-loud fixture and missing-audio fixture. | QC reports the actual issue; repair uses documented gain/asset selection, not a silent arbitrary fallback. |
| F20-M03 | Render A/B with different hook speech and compare music/unchanged audio regions. | Same music asset/envelope; any treatment-related ducking change is confined to the declared interval. |
| F20-M04 | Interrupt fake music generation and resume collection; repeat with an imported bed. | No duplicate paid request; imported path completes with explicit provenance and no generation charge. |

**Gate and rollback:** a frozen, reviewed mix profile and original/licensed soundtrack are available. Live music tests are separate from video qualification. Reuse a prior music master by revision; do not overwrite soundtracks already used in delivered files.

<a id="f21"></a>

## F21 — Unique-work production plan and asset graph

**Prerequisites:** F06, F15, F18, F19, F20. **Paths:** `production/`, `planning/asset_graph.py`, `tests/test_factory_production.py`.

**Input → output:** accepted experiment, qualified routing policy and accepted reference/audio assets → a priced DAG of unique picture/review/composition/render/delivery work with explicit reuse links.

### Build checklist

1. Expand takes into provider-supported durations, preserving required coverage and transition handles. A long take may require an explicitly reviewed split, not an unannounced speed stretch.
2. Identify genuinely shared requests from canonical prompt/settings/reference/audio hashes. For the canonical fixture, six control picture segments plus three changed replacements yield nine unique picture jobs, not 24.
3. Separate shared jobs from per-variant selections. Failure of one replacement should not discard valid control assets or regenerate unrelated variants.
4. Validate budget for the full unique graph plus declared repair allowance. Shared costs appear once in actual ledger and may be allocated analytically without multiplying charges.
5. Add dependencies from references and fitted speech into lip-synced picture generation, then downloads, targeted review, composition and delivery. Schedule through F06 instead of looping through a whole video in a chat turn.
6. Resume from durable graph/artifacts. Expose missing, rejected, uncertain and ready assets; support manual replacement with the same coverage/provenance checks.

### Automated validation

Canonical nine-job graph; cache invalidation by each generation input; branch isolation; duration rounding/splitting; shared cost accounting; provider fallback confounds; rejected-asset dependencies; graph resume and actual five-slot concurrency.

### Manual tests

| Case | Actions | Expected result |
| --- | --- | --- |
| F21-M01 | Prepare and run the canonical experiment with fake providers; inspect graph, calls and costs. | Nine unique picture requests in this fixture; four complete selections; shared work billed once. |
| F21-M02 | Reject C's changed shot after A/B are valid. | Only C's dependent work blocks; accepted shared shots and delivered variants remain intact. |
| F21-M03 | Restart after several downloads and before reviews finish. | Saved assets feed remaining jobs automatically; no multi-hour dependency on an agent's next turn. |
| F21-M04 | Make one allocation exceed the chosen provider's duration limit and offer a manual clip. | Plan requires an explicit supported split or validated manual coverage; no under-length footage is submitted for assembly. |

**Gate and rollback:** unique-work count, price and graph are explainable; completed outputs survive restart. Live throughput measurement is deferred to F34/F35. Disable new graph dispatch while preserving collection and accepted selections.

<a id="f22"></a>

## F22 — Hypit composition compiler and asset binding

**Prerequisites:** F13, F14, F21. **Paths:** `composition/`, `tests/test_factory_composition.py`. **Reuse:** `modules/assemble/hypit_markup.py`, `scripts/hypit.sh` and pinned Hypit runtime.

### Build checklist

1. Compile accepted plans into SVML/SVS/SVRun plus an asset binding manifest. Explicitly bind every picture/audio/font/caption artifact and target frame interval; avoid discovery by folder order.
2. Express all A/B/C/D dependencies and source revisions in generated metadata. Make compilation deterministic for identical inputs and preserve explicit reuse of existing accepted media.
3. Use the existing caption escaping helper. Hypit 0.1.8 historically rendered numeric apostrophe entities as text; test parser output and final pixels with the caption fixture.
4. Validate Hypit `check` and `plan` results through the repository launcher. Reject unexpected hosted generation/provider calls in a supposedly local composition plan.
5. Apply the declared renderer capability manifest. Use stable segment boundaries and shared sources so unchanged frames can be proved, including transition handles.
6. Produce readable compile diagnostics for missing assets, stale selections, unsupported effects and insufficient duration. Compile errors create no provider or publishing calls.

### Automated validation

Golden semantic composition outputs; exact asset IDs/order/timing; escaped text; source workspace containment; no hidden hosted calls; unsupported effect routing; deterministic output; stale review/asset detection and legacy manifests untouched.

### Manual tests

| Case | Actions | Expected result |
| --- | --- | --- |
| F22-M01 | Compile all four canonical variants, inspect the timeline and run Hypit check/plan. | Each is 900 frames; all assets are explicitly bound; only intended variant regions differ. |
| F22-M02 | Compile captions containing apostrophes, quotes, ampersands, angle brackets and Unicode; inspect rendered samples. | Visible characters match intended text; no `&#x27;` or other entity fragments remain. |
| F22-M03 | Remove a required clip and inject an unexpected hosted-generation component. | Compilation/plan gate blocks with exact locations; no automatic paid asset generation. |
| F22-M04 | Recompile unchanged inputs, then change a single accepted shot selection. | First output is semantically identical; second creates a traceable composition revision affecting only dependencies. |

**Gate and rollback:** pinned Hypit accepts the composition and its plan contains only intended work. Source markup validation alone is insufficient for captions. Preserve old compositions/build references when selecting an earlier revision.

<a id="f23"></a>

## F23 — Render execution and output retrieval

**Prerequisites:** F22. **Paths:** `rendering/`, `tests/test_factory_rendering.py`. **Reuse:** `modules/batch/fast_render.py`, `render.py`, `modules/assemble/runner.py` and actual-output retrieval behavior.

### Build checklist

1. Register an owned render process/build before execution; persist build ID/workspace/output names. Use `scripts/hypit.sh` so the pinned runtime's bootstrap is applied.
2. Select the verified static-composition FFmpeg path or Hypit according to capabilities. Record renderer/version/options; qualify visual parity before switching an existing template's renderer.
3. Normalize native media to the target clock and prepare segments in exact shot order. Allocate from accepted speech/timeline; trim only with coverage evidence and declared transforms.
4. Distinguish observer timeout from failed build. Resume status observation of the same build; a new Hypit build is a new execution requiring explicit reuse/repair policy.
5. Retrieve the actual returned final file, probe it and atomically register it. Do not assume output lives in the production directory; this also applies to any retained MoneyPrinterTurbo route.
6. Cache verified render intermediates by complete input/settings hash. Serialize local renders initially; write progress per section and finalization step so “6 of 20” has timestamps and recovery context.

### Automated validation

Ordered sections; exact 900/5,091-frame totals; 24→30 fps timing preservation; short-footage refusal; output-path parsing; failed/malformed results; render observer interruption; cache invalidation; caption pixels and unsupported-effect behavior.

### Manual tests

| Case | Actions | Expected result |
| --- | --- | --- |
| F23-M01 | Render `core-30s` through the actual local renderer, watch it and inspect returned file/probe. | Correct order, audio and caption timing; 900 picture frames; final retrieved from its real output path. |
| F23-M02 | Render the 20-section long fixture; stop only the owned observer at section six, then resume. | Build/progress survives or resumes under explicit recovery rules; no duplicate generation or unexplained idle gap. |
| F23-M03 | Feed a 24 fps native clip and a too-short clip. | First normalizes without timeline drift; second blocks instead of repeating/freezing frames without authorization. |
| F23-M04 | Compare qualified static fast-path output with Hypit and run an unsupported animated effect. | Static parity evidence is recorded; animation routes to Hypit or blocks visibly rather than disappearing. |

**Gate and rollback:** real local render succeeds; fake providers alone cannot prove assembly. Retain known-good renderer selection and intermediates; renderer rollback never substitutes a stale final file for the requested composition.

<a id="f24"></a>

## F24 — Technical, creative and changed-region QC

**Prerequisites:** F23, F14. **Paths:** `quality/`, `reviews/`, `tests/test_factory_quality.py`. **Reuse:** existing QC, review-pack and speech-check utilities, with explicit coverage limitations.

### Build checklist

1. Probe final streams and verify picture frame count, aspect, dimensions, decodeability, expected audio, silence/clipping policy and actual coverage. Distinguish container padding from picture duration.
2. Generate review evidence for every product reveal, detail shot, motion extreme, transition, first/last frame and caption join. Validate captions against final spoken text, not source transcript.
3. Review product/presenter continuity and speech/lip timing. A broad positive model review does not override a specific failed frame or word-level check. Record uncertain details for operator judgment.
4. Compare A against each variant outside declared changed intervals using composition provenance and decoded media. Use exact deterministic intermediate comparisons where available and calibrated codec tolerance for separately encoded finals.
5. Apply frozen audio mix transforms; verify shared soundtrack/unchanged speech regions. Document any allowed transition handles so they cannot hide undeclared widespread changes.
6. Bind all reviews to final/composition hashes. Reject stale acceptance. Repairs are new bounded jobs within authorized scope; a failed QC result cannot trigger unlimited regeneration.

### Automated validation

Wrong frame counts; short clips; black/frozen/corrupt sections; entity captions; alignment drift; missing review coverage; stale hashes; changed-region leaks; audio normalization leaks; major product mismatch flags and bounded repair behavior.

### Manual tests

| Case | Actions | Expected result |
| --- | --- | --- |
| F24-M01 | Review/watch/listen to all four fixture finals using the generated review pack and checks. | Every required section has evidence and a reviewer verdict; technical and creative statuses remain separate. |
| F24-M02 | Inject the historical apostrophe entity defect, one wrong product and a shifted caption join. | Specific defects are found with time/frame locations; final cannot be accepted on a generic overall score. |
| F24-M03 | Change one frame and a music gain segment outside B's hook interval. | Changed-region gate fails and identifies both undeclared deviations. |
| F24-M04 | Accept a final, alter its bytes or repair a segment, then reuse the old review. | Old review is stale; affected checks and final acceptance must run against the new hashes. |

**Gate and rollback:** accepted finals pass technical and declared treatment checks with human-visible evidence. Live creative qualification must use real generated products/presenter/speech. Previous accepted revisions remain selectable and clearly labeled.

<a id="f25"></a>

## F25 — Verified Google Drive delivery

**Prerequisites:** F24. **Paths:** `delivery/`, `integrations/drive.py`, `tests/test_factory_delivery.py`. **Required reference:** [standing completion workflow](google-drive-uploads.md#required-completion-workflow).

### Build checklist

1. Build descriptive names containing experiment/seed label, variant, treatment and revision; bind delivery to final artifact hash and the authorized Drive folder reference.
2. Upload using the existing authorized credential mechanism and resumable transfers where supported. Persist upload intent/session/file ID promptly; never log credentials/session secrets.
3. Verify parent folder, name, byte size and remote MD5 for binary MP4; retain local SHA-256 in the receipt. Handle unavailable checksum evidence explicitly rather than calling an unverified upload complete.
4. Reconcile lost acknowledgements through saved session/file metadata and content evidence. Duplicate filenames with different content are not proof of success and must not be overwritten silently.
5. Store verified delivery receipt, safe share link and completion timestamp. Keep ACL/sharing unchanged unless separately authorized; a folder authorization does not imply public sharing.
6. Emit `upload_verified` immediately after verification so F26 can finish cleanup. The final becomes fully delivered/complete only after QC, upload and required cleanup all pass. Delivery failures retain the local final and retry only transfer; they do not regenerate/render the video.

### Automated validation

Correct/wrong parent; name collisions; partial upload; lost acknowledgement; size/MD5 mismatch; invalid final hash; authentication expiry; repeat delivery and redacted resumable sessions. Fake Drive effect count must remain correct.

### Manual tests

| Case | Actions | Expected result |
| --- | --- | --- |
| F25-M01 | Deliver a QC-passed fixture, verify metadata and reopen its saved link through the fake delivery view. | Receipt contains correct file/hash/parent/bytes; repeated delivery reuses the verified result. |
| F25-M02 | Lose the upload acknowledgement after remote creation, restart and resume. | Existing remote file is reconciled; no duplicate upload or false failure-induced rerender. |
| F25-M03 | Introduce a same-name different-content file and an MD5 mismatch. | Neither is accepted as delivery; conflict/mismatch is explicit and local final is preserved. |
| F25-M04 | Upload one authorized test final to the actual destination, inspect its name/size/parent and play it from the returned link. | Real receipt verifies the exact local final; if access is unavailable, live delivery status remains blocked. |

**Gate and rollback:** delivery success requires remote verification. Standing user authorization covers finished-video delivery to the designated folder; it does not fund new generation. Preserve uploaded files/receipts on application rollback and follow F26 cleanup after each final.

<a id="f26"></a>

## F26 — Process ownership and resource cleanup

**Prerequisites:** F25. **Paths:** `resources/`, `tests/test_factory_resources.py`. **Reuse:** `modules/batch/local.py`; extend its ownership model for shared services and simultaneous variants.

### Build checklist

1. Register processes/resources when created with PID, start identity, command signature, owner job/experiment, workspace, listening ports and shared lease holders. PID alone is insufficient because it can be reused.
2. Classify resources as per-job, shared active, application-wide or unrelated. Stop only owned idle resources; keep active variants, dashboard/API and the durable worker running.
3. On each verified final/revised export, close its unused preview/render sessions, terminate gracefully then escalate only against the same verified owned process, and recheck ports. Record final completion only when QC, upload verification and required cleanup are all satisfied; an accessible Drive link can appear earlier with cleanup still pending.
4. Handle upload failure too: clean idle rendering resources while retaining the local final and resumable delivery state. Do not wait forever with large render processes alive for a network retry.
5. Reap stale owned processes after a crash using identity evidence. Report an unrelated listener occupying a requested port; never kill it merely to satisfy a port-free check.
6. Record before/after resource observations and cleanup receipts. Release owned buffers/temp work under retention policy; do not claim all system RAM is freed or purge unrelated caches.

### Automated validation

PID reuse; changed process signatures; shared lease references; reparented child; stubborn owned process; unrelated port listener; delivery failure; multiple variants and protected application services.

### Manual tests

| Case | Actions | Expected result |
| --- | --- | --- |
| F26-M01 | Finish A while B still uses a shared runtime; run completion cleanup. | A-only resources stop and ports free; B and dashboard continue without interruption. |
| F26-M02 | Replace a recorded PID with an unrelated fixture process and occupy a requested port independently. | Neither unrelated process is killed; cleanup reports the ownership/port conflict. |
| F26-M03 | Fail upload after rendering, restart the worker and inspect resources. | Idle render processes are cleaned; final/transfer state remains; later upload resumes without rerendering. |
| F26-M04 | Complete all variants, inspect owned process tree/ports and memory observations. | No idle per-video worker/listener remains; shared app services are listed intentionally; cleanup receipt supports the claim. |

**Gate and rollback:** every completion has delivery and cleanup evidence with no collateral process termination. Disable automatic cleanup if identity validation fails and provide a precise manual resource list; never substitute blanket process killing.

<a id="f27"></a>

## F27 — Application API and local security

**Prerequisites:** F08, F14, F21, F24, F25, F26. **Paths:** `api/`, `services/`, `tests/test_factory_api.py`. **Boundary:** transport for existing services; route handlers do not implement another scheduler, ledger or provider adapter.

### Build checklist

1. Implement the main handover's proposed endpoints and generate a versioned OpenAPI document with real request/response/error examples. Add missing read/query endpoints required by the UI through the same review process.
2. Require idempotency keys and expected revisions for mutations. Persist request hash/result; identical replay returns the original job/result, changed payload/key reuse conflicts, and stale revision returns 409.
3. Return 202 for durable asynchronous work and expose truthful state/readiness. Distinguish installed/authenticated/catalog-visible/tested/qualified rather than one green provider flag.
4. Expose ordered SSE with cursor replay, keepalive, filters and snapshot recovery. Handle disconnects without cancelling jobs; authorize event/media access using the same local session.
5. Bind loopback by default, validate Host/Origin, establish local session and CSRF protection, restrict upload size/type and serve bounded media Range requests by artifact ID. Protect against browser-origin attacks and path/URL injection.
6. Sanitize errors and sensitive payloads; separate operational authorization records from login credentials. A quote endpoint may prepare provider nodes but cannot start generation outside its stated semantics.

### Automated validation

Contract tests for each route; same/different idempotency payload; stale revision; authentication/CSRF/Origin/Host failures; upload limits; media containment/ranges; SSE reconnect/gap; redaction; async job persistence and shutdown scope.

### Manual tests

| Case | Actions | Expected result |
| --- | --- | --- |
| F27-M01 | Create, quote, authorize and run a fixture through API calls; replay run with the same key and then a changed body. | One logical run; stable original response; changed-body conflict; no extra paid effects. |
| F27-M02 | Disconnect SSE, allow work to finish and reconnect using the last event ID. | All missed state becomes visible; reconnect submits no jobs. |
| F27-M03 | Attempt mutation from an unapproved origin/session, traverse a media path and request an invalid range. | Correct safe errors; no state change or private-file disclosure; valid playback still works. |
| F27-M04 | Restart API while worker runs and query an ambiguous provider attempt afterward. | Durable work continues; health/recovery state is accurate and contains no credentials. |

**Gate and rollback:** API is documented and independently usable before UI acceptance. Disable mutations for maintenance while leaving safe history/readiness available; never couple worker lifetime to a browser request.

<a id="f28"></a>

## F28 — Dashboard seed, planner and budget screens

**Prerequisites:** F27. **Paths:** `apps/factory-dashboard/` with feature directories `seeds`, `products`, `blueprints`, `experiments`, `providers`, `budgets`; UI tests alongside those features.

### Build checklist

1. Create the local React/TypeScript app with pinned dependencies and a shared API client generated or checked against F27. Provide loading, empty, blocked, stale and error states for each screen.
2. Add seed URL/import and discovery views displaying the two outlier ratios, observation age, cohort/confidence and unavailable-video guidance. Display actual source playback before blueprint acceptance.
3. Add multi-product/variant selection with available angles/media and snapshot dates. Show supported factual copy and unavailable assets without exposing Shopify credentials.
4. Add blueprint timeline and A/B/C/D planner with synchronized script/timing comparison, immutable revision badges, locked fields and a readable “what changes” summary.
5. Show provider selection/readiness, allowed fallback, model/input-mode limitations and required qualification. Explain “Google budget not set” and “Reconnect Jimeng” in operator language.
6. Present unique-work line items and independent credit/USD ceilings, including Vertex and total USD, reserves/usage/unknown charges and repair/fallback scope. Approval records bind exactly the reviewed revision; changing it removes the run-ready state.

### Automated validation

Component states; accessible labels/keyboard navigation; schema/client consistency; stale edits; double-click idempotency; missing/zero metrics; fake provider readiness; quote units and revision-bound approval. Browser tests use fake backend transports.

### Manual tests

| Case | Actions | Expected result |
| --- | --- | --- |
| F28-M01 | Starting with an empty workspace, import a fixture, select three products, review blueprint and create four plans through the UI. | A nontechnical operator can see source, products, timing and exact treatment without editing JSON. |
| F28-M02 | Toggle Jimeng/Vertex policy and inspect insufficient-credit/unqualified-mode states. | Costs and limitations update; unsupported choices cannot reach a runnable approved plan. |
| F28-M03 | Approve a quote, edit copy in another tab and press Run in the first tab. | Stale revision conflict is understandable; no old approval funds the changed plan. |
| F28-M04 | Navigate by keyboard at a narrow window size; inspect empty/error/reconnect screens and displayed secrets. | Essential actions remain reachable; currency/credits are distinct; no token or raw CLI output is required to operate. |

**Gate and rollback:** operator can prepare a valid fixture experiment entirely in the UI with honest cost/readiness states. A disabled live provider must remain visibly disabled. API/service tooling remains available if a UI revision is rolled back.

<a id="f29"></a>

## F29 — Queue, comparison, review and Studio feedback UI

**Prerequisites:** F28. **Paths:** dashboard features `queue`, `compare`, `reviews`, `delivery`, `studio`; backend `studio/` for owned preview sessions.

### Build checklist

1. Display stage/variant progress from durable jobs/events, not guessed percentages. Show ready/queued/provider-running/downloaded/review/render/upload/cleanup distinctly with elapsed-time breakdowns.
2. Add pause/resume/reconcile actions with their actual semantics. Resume recovers existing work; regeneration is a separately scoped revision/repair action with cost impact.
3. Build source/A/B/C/D synchronized playback and changed-region overlays. Label source, preview, selected final and delivered revision clearly, including exact media identity.
4. Show QC failures with affected frames/words/product references and stale-review warnings. Accept/reject actions name the exact artifact revision and retain reviewer notes.
5. Open Hypit Studio as an owned local preview session using the pinned launcher. Map comments/feedback to timeline/revision; importing a comment creates a proposed change, not immediate paid regeneration.
6. Show verified Drive links, cleanup receipts and blocked actions. Keep optional IDs/technical diagnostics behind details while preserving actionable status for the operator.

### Automated validation

Event reducer replay; job-state labels; completed-count correctness; synchronized clocks; changed-region overlays; review hash binding; Studio feedback revision mapping; owned preview leases; inaccessible media and reconnect handling.

### Manual tests

| Case | Actions | Expected result |
| --- | --- | --- |
| F29-M01 | Run the fixture with staggered completions, close the browser and reopen after rendering. | Progress resumes from saved state; completed work did not wait for the browser or another agent turn. |
| F29-M02 | Compare all four finals against source, seek across treatment boundaries and inspect captions/audio. | Correct revisions play in sync; allowed changes are visibly marked and unchanged content is comparable. |
| F29-M03 | Leave a Studio comment on C, import it, then replace C's final before accepting the old review. | Feedback stays linked to its source revision; stale acceptance blocks; repair has an explicit proposed diff/cost. |
| F29-M04 | Complete A and inspect its Drive/cleanup status while B is active. | A's verified link appears promptly; B remains running; dashboard survives per-video cleanup. |

**Gate and rollback:** operator can diagnose a stuck stage and distinguish acceptance, completion and delivery without reading logs. Stop unused Studio sessions safely; rolling back the UI preserves feedback and review history.

<a id="f30"></a>

## F30 — Local installation, services and backup/restore

**Prerequisites:** F29. **Paths:** `cli.py`, `operations/`, proposed `scripts/factory.sh`, configuration example and `docs/factory-operations.md`. The exact launcher is a deliverable of this module, not an existing command.

### Build checklist

1. Provide reproducible setup/doctor/start/status/pause/resume/drain/stop operations with pinned Python/Node dependencies and clear required/optional tools. Keep the existing batch workflow runnable.
2. Load nonempty environment variables over `.env` over private TOML as the existing loader does. Separate safe configuration from native OAuth/Canvas credential storage; never put secret values into frontend build variables.
3. Start API/worker as separately owned services with health checks and restart policy. Bind loopback, detect occupied ports and choose/report configured alternatives without killing unrelated listeners.
4. On startup, validate migrations/storage and reconcile unresolved operations before new paid dispatch. Report per-provider readiness without generating media.
5. Implement drain versus immediate shutdown and resource retention. Cleanup after a video affects that video's idle services; full app shutdown is a separate deliberate operation.
6. Back up database consistently, configuration references and artifact manifest/retained media. Restore into a new root, verify hashes, reconcile external effects and require explicit activation before dispatch from restored state.

Include the preserved legacy cost ledger and unresolved authority/receipt records from F00/F05 in the backup manifest. Git history is not the backup for ignored financial state. Restore must reconcile work accepted since the backup before exposing any spend headroom or enabling dispatch.

### Automated validation

Config precedence; absent credentials; port conflicts; service start failure/partial rollback; restart health; schema compatibility; disk pressure; backup integrity; restore isolation and duplicate-effect prevention after restore.

### Manual tests

| Case | Actions | Expected result |
| --- | --- | --- |
| F30-M01 | Follow the operations guide from a clean environment through doctor/start/status and a fixture run. | App/worker are independently healthy; missing live services are explained; no undocumented manual command is required. |
| F30-M02 | Occupy the chosen port with an unrelated process and start the factory. | Start fails clearly or uses an explicitly configured alternative; unrelated process remains untouched. |
| F30-M03 | Drain while fake remote work is running, restart and then test immediate shutdown at another checkpoint. | Saved IDs and reservations survive; new dispatch follows startup reconciliation; no duplicate effect. |
| F30-M04 | Restore a live-WAL backup into a fresh QA root, verify assets and try dispatch before reconciliation. | Integrity passes; dispatch remains gated until external history is reconciled; original workspace is unchanged. |

**Gate and rollback:** another engineer can operate and restore the app using only the guide. Native logins may require user interaction; document exact reconnect actions without embedding credentials. Roll back binaries only against supported database versions.

<a id="f31"></a>

## F31 — Manual and authorized automated publishing

**Prerequisites:** F27, F25. **Paths:** `publishing/`, `integrations/publisher.py`, `tests/test_factory_publishing.py`. **Reuse:** `modules/publish/uploader.py`, record/metadata helpers after correcting transport and actual-post confirmation.

**Confirmed defect:** the current optional adapter sends `str(video_path)` in JSON with no required `user`, upload body, durable async status or idempotency identity. Fix this adapter or expose a new validated implementation behind its documented boundary before enabling automated posting; keep the manual lane usable throughout.

### Build checklist

1. Model publication separately from generation/delivery: selected final/hash, platform/account, metadata, visibility, schedule/timezone and explicit publishing authorization.
2. Implement manual posting instructions and verified post-ID/link registration first. Validate platform/account and associate each post with its exact experiment variant/final.
3. Implement one automated platform route, initially YouTube, against current primary documentation. Transfer the file through the supported upload body or an actually accessible media URL; a local filesystem path is neither. For Upload Post, validate the required `user` and `platform[]` fields, use the documented `Idempotency-Key` header and stable request identity, and observe asynchronous completion. Confirm current provider semantics before live enablement; a metadata `external_id` is not a deduplication guarantee.
4. Distinguish request accepted, uploading/processing, scheduled, draft/inbox, public, failed and unknown. An upload request ID or draft is not proof of a public post.
5. Persist publication intent before side effect, reconcile timeouts/status by provider identity, and enforce account cadence/timezone. Replay must not create duplicate public posts.
6. Attach the predeclared comparison horizon/metric/exposure policy. Public metadata changes and deletion are separate explicit actions; application rollback does not silently remove posts.

### Automated validation

Missing permission/account; fake transport inspects actual file bytes or supported accessible URL, account/platform fields and stable idempotency header; same/different idempotency payload; async progression including a synchronous request becoming async; visibility; manual mapping conflicts; timezone/DST cadence; ambiguous publish; expired OAuth and actual post verification.

### Manual tests

| Case | Actions | Expected result |
| --- | --- | --- |
| F31-M01 | Register four fake manual post links with account, time and final hashes; try assigning one post to two variants. | Correct mappings persist; conflicting identity is rejected rather than counted twice. |
| F31-M02 | Inspect the fake transport's upload bytes/URL, required account/platform fields and idempotency identity; run accepted→processing→public and separately draft-only. | Request cannot contain only a local path; only confirmed public state gets a public-post timestamp; draft remains clearly unpublished. |
| F31-M03 | Lose publish acknowledgement and restart; test a cadence conflict in the configured timezone. | Existing request is reconciled without duplicate post; schedule conflict blocks before submission. |
| F31-M04 | When separately authorized, publish or verify one real manually posted final and inspect its actual account/visibility/media. | Exact live mapping is evidenced; without posting scope, live gate stays pending while engineering can pass. |

**Gate and rollback:** fake publication and manual registration are complete. Live publishing is independently authorized even when video generation/upload was approved. Keep uncertain publication attempts visible and reconcile before any repost.

<a id="f32"></a>

## F32 — Analytics readback and coverage

**Prerequisites:** F31. **Paths:** `analytics/`, `integrations/youtube_analytics.py`, `tests/test_factory_analytics.py`. **Reuse:** existing pull/windows/readback functions only after fixing unsupported metrics, window handling and refresh behavior.

**Confirmed defects:** `analytics_rows()` requests generic `impressions,ctr` in an Analytics API report; these do not implement thumbnail reach. `channel_median_views()` returns `0.0` when unavailable. Correct these paths at the factory boundary while preserving frozen legacy compatibility.

### Build checklist

1. Create due readback jobs at 48 hours, seven days and 28 days using actual publication times. Store platform/account/post IDs, query version, metric definition and timezone.
2. Query only currently supported endpoints/metrics with proper OAuth refresh. Separate Data API observations, Analytics reports and thumbnail reach. The reviewed Reporting API reach route uses `channel_reach_basic_a1` with `video_thumbnail_impressions` and `video_thumbnail_impressions_ctr`; recheck report availability, schema, permissions and coverage before live use. Do not substitute ad impressions or retain unsupported generic `ctr` in the per-video Analytics query.
3. Store raw snapshots and normalized observations with coverage start/end, freshness, availability reason and query method. Daily aggregates are not automatically exact rolling-age windows.
4. Distinguish zero, missing, delayed, unsupported and failed metrics. New factory baseline records use nullable values and availability reasons; an unavailable legacy `0.0` is not a measured zero. Implement an explicit legacy compatibility adapter rather than altering frozen schemas or changing every old numeric field to null. Preserve native retention above 1 when the metric permits rewatches; do not clamp it to fabricate a percentage.
5. Reconcile account/post mapping and cohort comparability before presenting comparisons. Use matched horizons; retry delayed coverage without turning each retry into a new independent sample.
6. Provide manual metric import with explicit source/period and confidence for platforms lacking qualified connectors. Never invent TikTok/Reels metrics from YouTube schema assumptions.

### Automated validation

Due-window arithmetic; fake query transport asserts supported endpoint/metric combinations and separate reach collection; OAuth expiry; missing rows versus measured zero; unavailable baseline adapter; unchanged frozen contracts; delayed data; incompatible metric periods; retention >1; duplicate snapshots; mixed cohorts; manual imports and fixed-clock deterministic scheduling.

### Manual tests

| Case | Actions | Expected result |
| --- | --- | --- |
| F32-M01 | Advance the fake clock through 48h/7d/28d, collecting fixture readbacks. | Each horizon links the correct post/time coverage and shows complete/pending status accurately. |
| F32-M02 | Inspect actual fake queries; return no rows, measured zero views, unavailable legacy baseline and retention 1.2 in separate fixtures. Validate legacy and factory outputs. | Thumbnail reach uses its supported report; missing stays unknown, measured zero stays zero, retention remains 1.2, and frozen contracts still validate through the compatibility boundary. |
| F32-M03 | Expire OAuth and delay one variant's coverage; refresh and repeat collection. | Safe recovery preserves snapshots; incomplete comparison stays pending; repeated reads do not add samples. |
| F32-M04 | At a real due horizon, inspect a qualified live account report and compare saved query/coverage with the dashboard. | Actual coverage and supported metrics match; unavailable future horizons remain pending, never simulated as live evidence. |

**Gate and rollback:** engineering proves correct missingness/coverage behavior. Live analytics needs real publication identity, permission and elapsed observation time. Preserve raw snapshots when changing normalization/query versions.

<a id="f33"></a>

## F33 — Experiment decisions and learning library

**Prerequisites:** F32. **Paths:** `learning/`, `tests/test_factory_learning.py`. **Reuse:** verdict/format-promotion helpers through experiment-aware adapters.

### Build checklist

1. Require a decision policy frozen before publication: primary metric/horizon, minimum exposure, practical lift, guardrails and how three A-versus-variant comparisons are treated.
2. Verify complete comparable coverage and quality gates before ranking. A=0 or insufficient exposure yields defined handling, usually inconclusive, not infinite lift.
3. Treat organic posting as observational evidence with account/time/topic differences. Label descriptive comparisons accordingly; do not promise causal A/B significance from four unmatched posts.
4. Store decisions as immutable, reproducible records referencing metric snapshots, policy version and calculation inputs. Re-running identical data is idempotent; later data creates a revised decision.
5. Separate a promising treatment from a proven reusable format. Sibling variants share a seed/control and are not four independent confirmations. Count independent experiments explicitly.
6. Feed accepted lessons into searchable hypotheses/template recommendations with evidence and uncertainty. Keep operator overrides attributed; do not silently change future generation defaults from one noisy winner.

### Automated validation

Complete/incomplete data; A=0; minimum exposure; practical lift; guardrails; multiple comparisons; idempotent recompute; revised evidence; independent-seed counting and unsupported causal claims in generated summaries.

### Manual tests

| Case | Actions | Expected result |
| --- | --- | --- |
| F33-M01 | Evaluate the fixed complete fixture policy and recompute from its saved inputs. | Same decision and explanation; reviewer can reproduce every comparison. |
| F33-M02 | Remove B's horizon data, set A to zero and reduce total exposure in separate runs. | Each yields explicit pending/inconclusive or defined zero-baseline handling, not an automatic winner. |
| F33-M03 | Re-read the same four posts repeatedly and request format promotion. | Sample count stays one experiment; sibling variants cannot manufacture independent confirmations. |
| F33-M04 | Add a second independent seed experiment, revise the policy and inspect history. | Evidence lineage and policy revisions remain distinct; promotion follows the declared rule with limitations. |

**Gate and rollback:** learning is auditable, conservative about evidence and idempotent. A valid inconclusive outcome passes system validation. Retire/revise recommendations without erasing the experiments that produced them.

<a id="f34"></a>

## F34 — Failure drills and performance qualification

**Prerequisites:** F30, F33. **Paths:** `tests/test_factory_e2e.py`, `qa/scenarios/`, `docs/factory-reports/F34.md`. **Boundary:** qualify the assembled system, not isolated mocks or a promotional speed estimate.

### Build checklist

1. Implement J01–J04/J08 from the runbook using real application services, real local renderer and fake remote transports. Include both canonical and long-haul inputs.
2. Run checkpoint-driven crashes around submission, acknowledgement persistence, download, render finalization, upload and publication. Keep fake remote effects independent of the restarted application.
3. Exercise concurrent experiments with five global Jimeng slots, one initial Vertex slot and one local render; test independent provider throttles, low disk, stale leases and browser disconnects.
4. Measure ready-to-start, provider-observed latency, completion-to-collection, review, render, upload and cleanup separately. Set target scheduler/observation intervals in configuration and report results against them.
5. Compare eligible existing versus optimized render paths on the same local fixture/settings, reporting hardware, sample size, cache state and output parity. Do not compare unrelated Jimeng and Vertex pilots as a model speed benchmark.
6. Package a defect list, recovery instructions and release scope. Engineering release requires no unresolved duplicate-effect, budget-overrun, silent-quality-loss or unrelated-process-kill failure.

### Automated validation

Full offline suite plus deterministic integrated failure matrix; actual child-process restarts; durable DB/effect assertions; no-network audit; repeated render/output integrity; resource leak checks and compatibility with legacy entry points.

### Manual tests

| Case | Actions | Expected result |
| --- | --- | --- |
| F34-M01 | Run J01/J02/J04 through the operator UI and inspect all four outputs and fake call ledger. | Correct lengths/treatments, both adapter paths and bounded costs; no external calls. |
| F34-M02 | Run J03 checkpoint crashes and inspect remote-effect counts, reservations and delivered artifacts after each restart. | One effect per permitted intent; unknowns are explicit; completed assets are not recreated. |
| F34-M03 | Run concurrency/throttle/resource-pressure scenarios while closing/reopening the browser. | Capacities remain global; healthy work progresses; no wait depends on chat turns or a UI connection. |
| F34-M04 | Review stage timing evidence and same-fixture render comparisons with cache states disclosed. | Long delays have attributable causes; local targets pass or have concrete defects; no unsupported provider SLA is claimed. |

**Gate and rollback:** integrated engineering gate passes with traceable evidence. Paid speed tests are optional separately authorized measurements, not required to finish offline development. Roll back the affected feature and rerun relevant drills after fixes.

<a id="f35"></a>

## F35 — Funded pilot, release and engineer handoff

**Prerequisites:** F34. **Paths:** `docs/factory-reports/F35.md`, release checklist, finalized operations/API guides and updated module tracker. **Boundary:** establish what works live, with exact scope; do not equate one successful generation with the whole product being complete.

### Build checklist

1. Select one real seed and own-product set; verify actual source media, outlier evidence, available references and accepted blueprint. Freeze A/B/C/D and the decision policy.
2. Refresh provider catalogs/prices/readiness and reuse historical evidence only within its tested scope. Qualify each enabled product/reference mode with a bounded J05 test before full production.
3. Present complete unique-work pricing and scope. Use existing valid authorization where applicable or obtain the exact missing live scope; never revive spent historical budgets or purchase credits automatically.
4. Run J06 on the qualified selected provider(s), observing cost, reference fidelity, unchanged-region proof and each final's Drive verification/cleanup. Resolve defects through explicit bounded repairs.
5. Complete J07 only with publishing permission and real due horizons. A release can be labeled production-ready with learning qualification pending; it cannot be labeled fully validated end-to-end while that gate is incomplete.
6. Have a second operator/engineer follow setup, seed-to-final, pause/resume/reconnect and restore instructions without chat history. Record documentation gaps and fix them before handoff.
7. Finalize release manifest: code/runtime versions, enabled provider modes, configured limits, evidence, known limitations, disabled features, backup/restore procedure and responsibility for pending horizons.

### Automated validation

Final full offline suite; contracts/frozen-file integrity; release configuration validation; sanitized evidence/link checks; regression cases for every live defect. Live scripts remain opt-in and excluded from `make test`.

### Manual tests

| Case | Actions | Expected result |
| --- | --- | --- |
| F35-M01 | Complete J05 for each mode to be enabled; inspect footage, identity/product details and price/usage receipts. | Qualification matrix names exact provider/model/location/input mode; untested routes remain disabled. |
| F35-M02 | Complete J06 and watch/listen to all four full-length finals; verify Drive files and cleanup after each. | Own products/copy, fixed length, approved differences, within-ceiling execution and four verified deliveries. |
| F35-M03 | Complete authorized J07 as horizons become due, or record the exact pending gate and owner. | Live learning evidence is truthful; manual/automated post IDs and coverage are verifiable; pending is not pass. |
| F35-M04 | Give a new operator only this document pack and release setup; observe a fixture run and recovery/restore exercise. | Operator completes the workflow without hidden commands or credentials in chat; remaining gaps are fixed or explicitly scoped. |

**Gate and rollback:** record separate engineering, live production and learning-loop verdicts. Full-system completion requires the relevant live gates; lack of funds or elapsed analytics time is a named limitation, not an implementation success. Preserve delivered files and remote operation history during rollback; disable affected routes until requalified.

## Completion checklist for every module report

Use this report outline; fill it with actual results rather than copying expected results into the pass column:

```text
Module / owner / source revision / completion date:
Scope implemented and intentionally deferred:
Public interfaces and files changed:
Prerequisite versions and migration impact:
Targeted automated commands and results:
Full offline suite command, actual result and skips:
Manual cases: case ID, mode, expected, actual, verdict, reviewer, evidence link:
Live qualification: exact capability, authority, cost evidence, result or pending reason:
Frozen-contract and legacy-entry-point compatibility:
Timing and external-effect counts:
Rollout switch, rollback procedure and unresolved-operation handling:
Known limitations, follow-up owner and next gate:
```

Acceptance belongs to a particular source revision and capability scope. A changed provider protocol, renderer, budget policy or schema invalidates the affected evidence and requires targeted revalidation. A documentation update alone never moves a module from planned to complete.
