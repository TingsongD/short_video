# Viral Video Factory — Validation Runbook

**Version:** 2.1 · **Status:** proposed implementation and acceptance specification, including the reviewed checkpoint, financial-state and independent-gate requirements.

Read this with the [main handover](</Users/tingsongdai/Kimi-cursor/Short Form AI YouTube/docs/viral-video-factory-handover.md>) and [module guide](</Users/tingsongdai/Kimi-cursor/Short Form AI YouTube/docs/viral-video-factory-implementation-modules.md>). The commands under “Proposed QA interface” must be implemented in F01. They do not exist yet. This document does not record completed tests, authorize paid calls, or authorize social publication.

## 1. How the engineer uses this pack

1. Establish the baseline in F00 using main Sections 2.3–2.5: reviewed source checkpoint, classified tracked/untracked work, preserved ledger/private backup, tested ignore rules and independent G/F gate ownership. A dirty checkout can be inspected/tested; unresolved changes cannot be silently included in the accepted baseline.
2. Build F01's isolated test harness, then implement modules in the dependency order in the guide. Each module owns its named case definitions; the harness must call real application services with injected external transports.
3. For each module, run automated validation and its applicable offline manual cases, inspect actual outputs and save evidence. Perform explicitly live-only manual cases at their separate connected/funded gate. Follow the module's rollback instructions when a check fails.
4. Mark engineering completion only after its offline checks pass. Record live/manual qualification independently; missing cloud access must not prevent fixture-based engineering work or convert a pending live case into a pass.
5. Integrate completed modules through the real service and worker boundaries. A mocked leaf API is appropriate; a mock that replaces the workflow being accepted is insufficient.
6. Execute each applicable journey in Section 9 when its dependencies are integrated. J01/J03/J04 support the early R1 fixture milestone; repeat relevant integrated checks for F34 release qualification. Update the [module tracker](</Users/tingsongdai/Kimi-cursor/Short Form AI YouTube/docs/viral-video-factory-module-tracker.md>) with links to evidence, leaving partial modules open.

**Reading precedence:** applicable user/repository constraints → main handover's product and safety invariants → module-specific implementation contracts → this shared test procedure. Main Section 2.3 explicitly identifies the superseded swarm rules for this single-builder assignment. If a module exposes another conflict, record a proposed document/contract correction before building around it. F00–F35 identify new factory work and do not silently sign legacy G0–G12. Historical successful production is scoped evidence, even when a legacy summary gate remains pending.

## 1.1 Baseline and review-specific evidence

- Capture HEAD, branch, tracked diff digest, relevant untracked-file manifest and each changed path's intended disposition. Include the observed `LONGFORM_PLAN.md` deletion in review; a clean status is not a reason to commit an unexplained removal.
- Link the reviewed batch-code/test checkpoint separately from handover/evidence changes. Record the factory worktree and accepted revision; preserve unrelated original-checkout work. A stash is not the default backup for untracked runtime data.
- Verify ignore coverage for `data/costs/ledger.json`, `data/factory/` and `data/factory-qa/`, while preserving tracked `data/costs/.gitkeep` and new deterministic fixtures. Inspect staging without printing financial/credential contents.
- Back up ledger bytes and unresolved authorization/receipt state privately. F00 restore checks preserve history; F05/F30 additionally prove repeated migration/restore does not double count or reinstate spent authority. Runtime financial records are durable, even though ignored by Git.
- Snapshot gate ownership through links to the authoritative G and F records. Shared evidence names exact criteria; it cannot silently convert either system's pending status to passed.
- At F10, test selection modes through the active Viral Outliers path, not merely the already-existing baseline math helper. At F31, inspect the actual upload transport. At F32, inspect query/report fields and the missing-baseline compatibility adapter.
- Record scope independently from credentials and dated balances. The assigned engineer can execute authorized offline tests without another confirmation; a historical zero or positive balance proves neither present funds nor new spending permission.

## 2. Three validation levels

| Level | Allowed effects | What a pass proves |
|---|---|---|
| Offline engineering | Local fixture files, real local renders, test database, fake providers and fake Drive/publication; no external network or production credentials | Application logic and failure handling work under controlled inputs |
| Connected read-only | Selected existing account authentication, capabilities and explicitly identified read-only checks; API-credit-billed research still needs budget | Current identity, permissions and returned capabilities for that check |
| Funded live | Exact approved provider/account/model/input-mode/quantity and ceiling; verified delivery; publication only under its own scope | The recorded scenario works on the real provider within the observed limitations |

All ordinary `make test` runs remain offline. Live tests are separately selected, visibly labeled and disabled by default. Tests that need the installed Hypit renderer may declare a missing dependency, but a skipped required render test cannot count as release acceptance.

Case registration declares its allowed level. Implement CLI modes `offline`, `connected` and `live`: `connected` permits only the registered read-only account/capability checks; a credit-billed research request belongs in `live` even though it reads data. A live-only case requested in offline mode must report the wrong mode, not silently substitute a mock and award live qualification.

One provider's completed live test does not qualify the other provider. An Omni text prompt does not qualify product-reference input, source-video editing, external-audio lip sync, or five-way concurrency.

## 3. Proposed QA interface — implement in F01

Run from the repository root. Names and flags below are an implementation contract for the new engineer, not currently available commands.

```bash
# Existing baseline command; currently available.
make test

# PROPOSED: isolated workspace containing only generated QA data.
.venv/bin/python -m modules.factory.qa init \
  --workspace data/factory-qa/engineer-001 --fixture core-30s

# PROPOSED: discover actual registered cases and prerequisites.
.venv/bin/python -m modules.factory.qa cases --module F05

# PROPOSED: run one module-owned manual scenario through real services.
.venv/bin/python -m modules.factory.qa run \
  --workspace data/factory-qa/engineer-001 --case F05-M01 --mode offline

# PROPOSED: inspect durable state and the external-call audit.
.venv/bin/python -m modules.factory.qa inspect \
  --workspace data/factory-qa/engineer-001 --view budgets --json
.venv/bin/python -m modules.factory.qa inspect \
  --workspace data/factory-qa/engineer-001 --view provider-calls --json

# PROPOSED: package sanitized evidence, retaining output file hashes.
.venv/bin/python -m modules.factory.qa evidence \
  --workspace data/factory-qa/engineer-001 --module F05
```

Required interface behavior:

- `init` creates a new workspace and refuses an occupied root. A rerun uses a new workspace or an explicit safe resume; it never deletes arbitrary files. F01 can stage fixtures before F03 exists; F03 initializes that workspace's database when available.
- `cases` reports `implemented`, `missing_prerequisite` or `not_implemented`. An unavailable case exits nonzero with its exact prerequisite. It must never return canned success.
- `run` defaults to offline. A case owns its input changes, fault injection and service calls. It saves a run ID, expected outcomes and actual results. Manual visual/listening steps remain `awaiting_manual_review` until the reviewer records a verdict.
- Offline provider construction must neither load production secrets nor instantiate live CLIs/transports. Reject unexpected outbound requests; allow only the selected loopback services and local binaries needed for rendering.
- Fake provider state persists separately from the application database, allowing a worker crash after remote acceptance to be tested honestly. Record each billable submission, request hash, fake operation ID, poll and download.
- Each case gets an isolated database/artifact namespace. Repeating a case with its existing run ID tests idempotency; creating a new run is explicit.
- `inspect` supports at least `contracts`, `assets`, `seeds`, `products`, `blueprints`, `experiments`, `jobs`, `events`, `budgets`, `provider-calls`, `reviews`, `deliveries`, `publications`, `metrics`, `resources` and `health` as those modules are built. Unsupported views fail clearly.
- Implement positive integer microdollar arithmetic, fixed fake clocks, deterministic IDs and file hashes in the harness. Do not use real waiting for multi-day analytics horizons.
- Case injection has a finite registry. It must not accept arbitrary shell commands, SQL, Python expressions or filesystem targets from the browser.
- Live execution uses a separate explicit `--mode live --authorization-id <existing-record>` and provider-specific case allowlist. The harness cannot create spending authority from a flag. F00/F01 have no live cases.
- Automated pytest tests live under `tests/test_factory_*.py`; UI tests live under the dashboard's test configuration. F00 records exact supported commands after implementation. Run targeted tests during development and the complete offline suite at each module gate.

### Fault registry

Provide fake-transport or owned-test-process failures for: reject-before-accept, accept-then-timeout, malformed acknowledgement, accepted-then-failed, stalled operation, auth expiry, quota rejection, download failure, corrupt bytes, insufficient duration, storage-full, event disconnect, stale lease, stale review hash, duplicate upload and ambiguous publish response.

A simulated network fault must occur at the actual adapter boundary. Crash cases must terminate an owned QA worker at a named checkpoint, restart it and observe recovery. They must not merely edit the final status to `unknown` and assert that value.

## 4. Fixture catalog and expected outcomes

Create these under `tests/factory_fixtures/` or generate large media into the QA workspace from tracked deterministic recipes. Do not modify frozen `tests/fixtures/` or `schemas/`. Use synthetic or explicitly reusable media, never copied production credentials or private customer data.

| Fixture | Required contents | Reference expectation |
|---|---|---|
| `core-30s` | Portrait source, 30 seconds of picture at 24 fps; six beats; three synthetic product snapshots; fixed transcript/word times; local picture/audio assets | Output clock is 30 fps and exactly 900 frames; A/B/C/D exist |
| `long-haul-1697` | 169.7-second picture timeline, 20 takes, 10 product snapshots | Exactly 5,091 output frames; stays in factory contracts and never truncates to the legacy seven-shot maximum |
| `reference-defects` | Thumbnail labeled as video, zero-byte clip, wrong container, missing audio, variable frame rate, short footage, duplicate source URL, expiring URL | Accurate rejection or labeled normalization; no paid dispatch to repair an intake defect |
| `outlier-math` | Seed 1,000,000 views; 10,000 followers; 20 comparable baseline videos at 20,000 views each; separate mixed-format/zero/missing cases | Seed has follower multiple 100 and mean/median multiple 50; seed excluded from cohort |
| `outlier-boundaries` | 19,999, 20,000 and 20,001 views against 10,000 followers; baseline multiplier exactly 5; fewer than 20 samples | Strict follower `>2` rejects the first two and accepts the third; baseline threshold and confidence remain separate |
| `shopify-catalog` | Paginated products/media, color variants, image-only product, attached video, unavailable variant, HTML description, stale URL | Complete counted snapshot; claims and variant/media identity traceable; unavailable angle remains unknown |
| `provider-catalogs` | Canvas and Vertex capabilities, distinct duration/input-mode limits, expired snapshots and unqualified Veo entries | Router validates the chosen route/mode and refuses unsupported substitutions |
| `provider-failures` | Persisted fake operations for each fault from Section 3, including Omni HTTP 200 then `errors` | Exactly one accepted paid intent is recovered; every unknown effect retains its hold |
| `money-boundaries` | 100-credit cap and competing reservations of 60 and 50; 1,000,000-microdollar overall cap, 800,000 Vertex sublimit, existing 300,000 other usage | Only the 60-credit reservation succeeds; a 750,000 Vertex reservation fails the aggregate cap despite fitting its sublimit |
| `caption-entities` | Apostrophes, quotes, `&`, `<`, `>`, Unicode and join-boundary cues | Intended literal text survives parser and pixels; numeric entity artifacts fail review |
| `composition-effects` | Static haul plus one moving overlay/transition unsupported by the fast exporter | Supported static export is equivalent; unsupported effect routes to Hypit or blocks visibly |
| `delivery-recovery` | Fake Drive folders, matching checksum, same-name/different-hash file, lost upload acknowledgement | Identical delivery is reused; conflicting file is never silently replaced |
| `process-ownership` | Owned server/child, shared lease, unrelated port owner and simulated PID reuse | Only current owned idle resources stop; the factory and active consumers remain running |
| `analytics-windows` | Fixed publication times, delayed rows, empty results, mismatched periods, retention above 1, three comparisons | Coverage and unknowns remain visible; no unsupported metric or invalid winner |

### Canonical four-version fixture

Use half-open output-frame intervals. `core-30s` beats are 0–4, 4–8, 8–12, 12–17, 17–26 and 26–30 seconds. Its baseline template uses hard cuts so acceptance does not depend on unspecified transition handles.

| Variant | Permitted change | Output frames |
|---|---|---|
| A | Original adapted control | 0–900 |
| B | Hook copy, corresponding picture and captions | 0–120 only |
| C | One benefit passage, corresponding picture and captions | 360–510 only |
| D | Ending/CTA, corresponding picture and captions | 780–900 only |

All four outputs have 900 frames. Products, presenter, voice, music, output clock and selected provider policy remain locked. Changed speech may change corresponding lip movement inside the declared interval. Unchanged picture source IDs, trims and transforms remain the same. Later transition fixtures must declare any expanded handles before approval.

The minimal dependency example has six accepted A picture segments plus three replacements, not four complete sets of six generations. Shared references and narration are also deduplicated by identity. A provider may need longer generation durations; record generated and used intervals separately. Do not hardcode this fixture's price or job count into arbitrary real experiments.

## 5. Data and API contracts the tests must inspect

F02 defines additive factory schemas; F03 persists them. At minimum validate the following families:

| Contract family | Fields that must be inspectable | Critical rule |
|---|---|---|
| Source/seed observation | Identity, URL, observed time, counts, method/cohort, unknown reason, source hash | Observation data cannot mutate prior accepted evidence |
| Product snapshot | Store/product/variant/media IDs, selected attributes, retrieval time, copy facts, asset hashes | No complete-media claim before pagination completes |
| Blueprint/template | Source and target clock, beats, transcript, audiovisual systems, evidence, accepted hash, template version | Accepted revision is immutable |
| Experiment/variant | A/B/C/D, shared control hash, treatment intervals, locked fields, provider policy, budget scope | Every derived asset use is attributable to a revision |
| Generation/price | Provider/model/route/scope, references, prompt, settings, supported duration, typed price and reserve, freshness | A request change invalidates the price and applicable approval |
| Job/attempt | Dependency keys, lease/fence, timestamps, retry class, local/remote identity, native status/error | Lease expiry never proves a remote job did not happen |
| Asset/use | Hash, real media kind, dimensions/fps/duration, source/target interval, provenance, transforms | Registration follows validated bytes; complete lineage survives restart |
| Review/delivery | Target hash, checks, reviewer, limitations, final selection, remote file/checksum, resource receipt | An upload ID alone is not verified delivery |
| Publication/readback/decision | Selected final, approved account, actual post ID/time, coverage, metric definition, comparison policy | Uploaded, public, measured and winning are distinct states |

F03 must provide transactional migrations, foreign keys and uniqueness for logical job keys, effect intents, immutable revision numbers, idempotency keys and publication mappings. Test successful rollback on migration failure and backup/restore while WAL contains recent writes. On conflict, prefer a typed domain error to an unstructured database traceback.

F27's API serves application services; handlers must not duplicate budget/state rules. Generate a checked OpenAPI contract with request examples and error envelopes. Every mutating route tests the same key/body replay, same key/different body conflict, stale expected revision and rejected unauthenticated/invalid-origin access. Media responses test bounded Range requests, valid asset IDs and path containment. SSE reconnect tests replay once by event ID, without treating it as a new job command.

## 6. Manual evidence template

Save runtime evidence to `data/factory-qa/<workspace>/evidence/<module>/<run-id>/`. Commit a sanitized module report under a documentation reports directory selected in F00; large media and private provider receipts stay in ignored data storage. The tracker links the report and identifies where an authorized engineer can find the full bundle.

```json
{
  "schema_version": "factory.validation.v1",
  "module_id": "F17",
  "case_id": "F17-M01",
  "mode": "offline",
  "status": "not_run",
  "source_revision": null,
  "dirty_diff_sha256": null,
  "untracked_manifest_sha256": null,
  "checkpoint_report": null,
  "fixture_version": "core-30s-v1",
  "started_at": null,
  "finished_at": null,
  "reviewer": null,
  "expected": "One saved operation reaches a validated downloaded artifact.",
  "actual": null,
  "assertions": [],
  "artifacts": [],
  "provider_submission_count": 0,
  "budget_evidence": null,
  "limitations": [],
  "cleanup_receipt": null
}
```

Required evidence for a completed case:

- Exact code revision plus dirty-diff hash and relevant untracked-file manifest when applicable, checkpoint report, dependency/tool versions, fixture identity and selected configuration. Do not hash secrets into a public manifest; keep private backup details in access-controlled evidence.
- UTC start/end and monotonic elapsed time, with retries/restarts individually timestamped.
- Expected and observed result for every check, including actual error code on negative tests.
- Relevant screenshots, decoded frame samples, listening notes, database/event excerpts and asset hashes. A screenshot of a toast does not substitute for durable-state evidence.
- Fake or live provider submission counts and IDs, with secrets and signed download URLs redacted.
- Price/reservation/usage reconciliation and the qualification scope for connected/live checks.
- Owned-process/port cleanup status and any retained source/output paths.
- Reviewer name, unresolved deviations and a final `pass`, `fail`, `blocked` or `not_applicable` verdict. A required unrun case remains pending.

## 7. Per-module acceptance and rollback

Every module card defines its own manual cases and live requirements. Apply this shared gate in addition:

1. Public interfaces and owned paths are documented; no hidden dependency on mutable globals or chat state.
2. Targeted automated cases pass, followed by the complete offline suite for the integrated repository. Record skips with reasons.
3. All required manual cases for the selected validation level pass on actual services/artifacts. Visual/audio review records its inspected scope. Live-only cases can remain pending alongside passed engineering/offline manual status, but block enabling the corresponding live capability.
4. Fault recovery proves the intended effect count and unchanged accepted output, not just a status label.
5. Compatibility checks show frozen legacy schemas/fixtures unchanged and existing entry points usable, including an explicit boundary for legacy numeric sentinels versus nullable factory observations.
6. A module report names implementation files, exact validation commands, evidence paths, unresolved limitations, rollout switch and rollback/recovery procedure.
7. The tracker distinguishes engineering completion from pending live qualification and partial milestone scope; no F acceptance silently signs a G gate.

Rollback disables a new feature/route and selects an earlier accepted revision. It preserves database migrations, attempt identities, budget holds, source media and receipts until reconciled. A Git revert cannot cancel a remote job or undo a public post. No rollback script should delete existing production folders or reset user credentials.

## 8. Numerical and media acceptance

- **Picture clock:** compare decoded frame count to the exact planned count. For the two core fixtures use 900 and 5,091 frames at 30 fps; record container/audio padding separately.
- **Coverage:** every authored interval has an accepted source allocation that covers it at the declared playback rate. Unsupported holds, looping or speed changes are explicit editorial choices, not automatic repairs.
- **Frame comparison:** compare decoded frames outside treatment intervals and declared handles. Use exact equality for deterministic intermediate frame fixtures; record a calibrated tolerance for separately encoded exports. A whole-file MP4 hash is not a picture-equality test.
- **Audio comparison:** use selected PCM and recorded sample intervals as authority. Codec padding and local gain/tempo transforms are explicit. Captions follow accepted word times after those transforms.
- **Audio quality:** save measured loudness/peak/clipping and listening results. F20 establishes an accepted mix profile rather than silently imposing a new global gain on each variant. Any target profile is part of the frozen experiment.
- **Product fidelity:** inspect each featured product/variant against its accepted reference at reveal, detail and motion extremes. Reject changed category, selected color, distinctive construction or unsupported claims; record smaller print/fit differences and the owner/reviewer decision.
- **Caption fidelity:** inspect representative rendered states and every automated discrepancy, including known entity/Unicode edge cases. OCR confidence alone cannot establish correct pixels.
- **Resources:** use recorded process identity and leases. Verify each owned port after shutdown; identify an unrelated occupant rather than killing it. Record memory pressure and disk reserve without claiming all OS caches were freed.

Thresholds must be explicit configuration with units, test evidence and a policy version. Changes after review invalidate affected acceptance. Do not invent a numerical “viral similarity” score as a substitute for the source-to-blueprint and product checks.

## 9. Release journeys

| Journey | Start → result | Required proof |
|---|---|---|
| J01 Offline seed to four outputs | Local `core-30s` seed → A/B/C/D on fake providers → real local exports → fake verified delivery | Four 900-frame outputs; only declared regions differ; unique work reused; no external call |
| J02 Long reference | `long-haul-1697` → four planned/exported variants | 20 takes and 5,091 frames preserved; no frozen-contract coercion |
| J03 Recovery | Kill the QA worker after acceptance and again after local export → restart | Same remote IDs, one effect per intent, recovered artifact registration and no duplicate upload |
| J04 Both provider routes | J01 through Canvas fake and Vertex fake, plus explicit fallback scenarios | Unit-specific caps, real shared adapter contract, original unknown job never replaced blindly |
| J05 Live product/provider qualification | Exact approved product and input mode → one bounded provider clip | Reference fidelity, actual duration/fps/audio, cost evidence, recovery IDs and verified delivery where it is the finished test deliverable |
| J06 Funded experiment | One accepted real seed → close adaptation plus hook/body/ending variants | Four reviewed, delivered finals with own products, original narration, fixed duration, permitted differences, budget and cleanup |
| J07 Publication and learning | Selected finals → separately authorized posts or verified manual IDs → due readbacks | Actual public IDs and coverage-aware metrics; declared decision or honest inconclusive outcome |
| J08 Operator recovery | Close browser, reconnect SSE, restart services, restore a backup to a fresh QA root | No state loss or duplicate effect; readable status and actionable blockers |

J05 is recorded per provider/model/input mode. J06 can use one qualified provider; the other route may remain disabled with a named pending gate. J07 waits for actual observation horizons; a fake seven-day readback is an engineering test, not live analytics acceptance. Social posting and additional paid tests require their corresponding scopes. Retain completed engineering work when a live prerequisite is unavailable.

## 10. Release evidence and handoff to the next engineer

Provide a release report linking the filled module tracker, commands for installation/start/stop/backup/restore, pinned dependency inventory, current model/mode readiness, artifact/Drive receipts, acceptance journeys, outstanding decisions and known limitations. Include a reproducible offline demonstration using synthetic data and a concise operator guide using dashboard labels.

Completion of this documentation pack is distinct from completion of the application. At handover creation all F00–F35 modules are planned; recorded older production/pilot evidence is reusable only for the specific checks it demonstrates.
