# Remaining issues — follow-up review, 2026-09-19

Reviewed source: `44db0fa`, including repair commits `695c326` and `b2118b4`.
Scope: current factory implementation, dashboard, operations scripts, mission/
build specifications, operator documentation, DEV_LOG, acceptance trackers,
and the previously recorded legacy backlog. This is a current issue inventory,
not a claim that an offline review can prove the absence of every other bug.
No production code, operational database, credentials or live jobs were changed.

The recent repairs are substantial, but the assertion that all 16 prior issues
are closed is too strong. Final-review binding, authority renewal and visual
uncertainty remain incomplete; additional integration defects are below.

## Remaining code and operator-interface defects

P1 = address before another unattended paid production; P2 = functional defect;
P3 = lower-impact usability defect. Reproduction labels refer to the saved
[offline diagnostic probes](probes/review_2026_09_19_followup.py). These assert
the **bad behavior**: passing confirms the defect, not correctness.

| ID | Priority | Remaining issue, trigger and consequence | Evidence / required change |
| --- | --- | --- | --- |
| F01 | P1 | **Creative approval can still follow replacement finals.** When a final changes after its first verdict has been recorded, resubmission removes the job/plan/auth but retains `qc_verdict_A` etc. The new result is then overwritten by that cached verdict: a new `fail` becomes the old `pass`. Human acceptance likewise sets one unbound `qc_human_accepted` boolean and subsequently skips creative verification for all current finals. Replacement finals with passing mandatory technical/region checks can therefore finish without current creative approval. | Reproduced both paths. [autorun/service.py:2054](../../modules/factory/autorun/service.py#L2054), [2088](../../modules/factory/autorun/service.py#L2088), [2145](../../modules/factory/autorun/service.py#L2145), [466](../../modules/factory/autorun/service.py#L466). Invalidate cached verdicts on replacement and verify each human/machine verdict against the current artifact and composition, not a run-level flag. Prior C03 is only partially closed. |
| F02 | P2 | **Resuming an edited production retains the old dispatch job.** `_rebind_current_revision` clears the quote/plan but leaves `run_job`. After the new revision is quoted and authorized, `_stage_run` sees the old succeeded job and skips `run_experiment`; footage waits for jobs that were never created. The other rewind helper does clear this field, so recovery behavior differs by entry path. | Reproduced no new dispatch after revision 1→2. [autorun/service.py:332](../../modules/factory/autorun/service.py#L332), [1803](../../modules/factory/autorun/service.py#L1803). Clear revision-bound dispatch state together with the plan. |
| F03 | P1 | **The revision-change guard does not inspect actual production work or held money.** It reads `state.production_jobs`, which is never populated anywhere in the current source. Production jobs instead use `plan_id:node_key`. An edit can therefore discard the old plan references while its paid jobs/attempts remain active. The method also does not check reservation settlement, despite the dev-log claim. This does not itself bypass a budget ceiling, but permits overlapping obsolete work and breaks recovery ownership. | Probe confirms no job/attempt lookup for ordinary production state; source search confirms no assignment to `production_jobs`. [autorun/service.py:294](../../modules/factory/autorun/service.py#L294), [1830](../../modules/factory/autorun/service.py#L1830), [DEV_LOG.md:1532](../../DEV_LOG.md#L1532). Derive active work from the persisted plan/attempt ledger and check associated holds before replacing it. |
| F04 | P1 | **Source-frame timestamps are interpreted using the output frame rate.** Blueprint construction stores source intervals at the source rate, but script adaptation divides those indices by `bp.clock` (the output rate). A 10-second, 24fps source becomes an 8-second source interval on a 30fps output clock; a passage at 9–10s becomes unplaced. The stage then notes that unplaced passages are excluded and continues. Other rate mismatches misassign narration to beats. | Reproduced 24→30fps with the last passage lost. [analysis/service.py:153](../../modules/factory/analysis/service.py#L153), [183](../../modules/factory/analysis/service.py#L183), [autorun/service.py:1031](../../modules/factory/autorun/service.py#L1031), [1100](../../modules/factory/autorun/service.py#L1100). Preserve/use the source clock or authoritative passage ownership; pause on unexpected unplaced narration. |
| F05 | P1 | **Unchanged-region audio QC no longer verifies exported audio.** The renderer passes deterministic mix WAVs to `check_regions`; the check compares those instead of either final's audio. Consequently a wrong, shifted or substituted soundtrack in an export can pass with correct source mixes. Avoiding sample-exact AAC comparison is reasonable, but the replacement needs a final-to-mix audio-content/alignment check. | Reproduced with two real local MP4s carrying 440Hz versus 880Hz audio: the changed-region verdict is `pass` when supplied the same mix. [quality/service.py:84](../../modules/factory/quality/service.py#L84), [services/worker.py:519](../../modules/factory/services/worker.py#L519). Keep exact mix checks and add codec-tolerant verification of the actual exports. |
| F06 | P2 | **Renewing run expiry does not renew its cached authority.** Resume updates `params.valid_until`, but `_run_effect` reuses a stored authorization whenever its plan binding matches, without checking expiry. Queueing then raises `authorization_expired`. If jobs already exist, the early return preserves them; terminal expiry failures are not among the reset handler's supported pause codes. A renewed run can keep pausing on the same expired authority. | Reproduced a 2099 run expiry reusing an authorization expired in 2000. [autorun/service.py:246](../../modules/factory/autorun/service.py#L246), [708](../../modules/factory/autorun/service.py#L708), [736](../../modules/factory/autorun/service.py#L736), [358](../../modules/factory/autorun/service.py#L358). Renew only safely undispatched scope and preserve/reconcile any existing attempt identities. Prior C08 is partially closed. |
| F07 | P2 | **Translation pauses advertise recovery actions that do not work.** Missing translation capability tells the operator to resume with `set_params language=...`, but `language` is rejected as `param_not_resumable`. Incomplete translation says Resume will retry; reset handling neither recognizes translation failure/incompleteness nor clears the `translate` tag at the script stage. Resume reads the same result/job indefinitely, including after a translation budget failure. | Reproduced rejected language update and retained incomplete-translation references. [autorun/service.py:246](../../modules/factory/autorun/service.py#L246), [358](../../modules/factory/autorun/service.py#L358), [1046](../../modules/factory/autorun/service.py#L1046), [1080](../../modules/factory/autorun/service.py#L1080). Implement an audited language change and bounded, reconciled translation retry, or give a supported recovery action. |
| F08 | P2 | **The analysis-proxy choice is discarded by the autorun API.** Analysis checks `run.params.analysis_asset_id` to select a registered derivative, but `create` omits that input and `resume` does not allow it. Attaching a proxy succeeds while autorun keeps submitting the production master; the intended smaller-input path cannot be selected through the public run interface. | Reproduced create silently dropping `analysis_asset_id`. [autorun/service.py:100](../../modules/factory/autorun/service.py#L100), [831](../../modules/factory/autorun/service.py#L831). Validate and persist the explicit derivative selection without replacing the master. |
| F09 | P2 | **Manual-post verification labels failed/unprocessed uploads public.** The new verifier computes a processing-aware `public` boolean, then on false falls back to `privacyStatus`; a public-visibility upload with `uploadStatus=failed`, `rejected` or `uploaded` still returns `status=public`. `register_manual` trusts that status and records verified publication. | Reproduced all three statuses. [integrations/publisher.py:184](../../modules/factory/integrations/publisher.py#L184), [publishing/service.py:421](../../modules/factory/publishing/service.py#L421). Preserve processing/failure status and require a fully verified public post. The previously absent verifier is now wired, but not correct for these responses. |
| F10 | P2 | **Explicit visual uncertainty still becomes “reviewed” without being resolved.** The new anchor check accepts any beat starting at the media head, any truthy evidence IDs, or a nearby cut. These establish timing, not whether an obscured product detail is identifiable. A provider's explicitly uncertain garment detail at time zero is still promoted using description/transcript overlap alone. | Reproduced with no supplied visual evidence. [autorun/review.py:26](../../modules/factory/autorun/review.py#L26). Preserve substantive uncertainty until evidence actually resolves the claim. Prior C15 remains open for anchored beats. |
| F11 | P2 | **Stack scripts miss processes started by the documented launcher.** `factory.sh worker` executes `... modules.factory.cli --root . worker`, while up/down orphan matching expects `... modules.factory.cli worker` with no intervening options. With no `.run/worker.pid`, down does not stop that worker and up attempts another start, which the new worker lock rejects. Relative-Python manual launches also escape the absolute-path matcher. | Offline pattern probe confirms the documented launcher mismatch. [factory.sh:10](../../scripts/factory.sh#L10), [factory-up.sh:26](../../scripts/factory-up.sh#L26), [factory-down.sh:29](../../scripts/factory-down.sh#L29), [operations guide:56](../factory-operations.md#L56). Use verified process ownership records consistently across launch paths; no processes were stopped in this review. |
| F12 | P3 | **The dashboard still misrepresents spending limits and lacks their advertised recovery controls.** It labels them “per-operation” although `_ceilings` compares the sum of the entire effect plan. Its Resume action sends budgets only; there are no limit/expiry editors in the pause block, despite DEV_LOG saying it exposes those updates. An operator following “raise the limit, then Resume” must leave the dashboard and use the API. | [AutoRunScreen.tsx:145](../../apps/factory-dashboard/src/features/autorun/AutoRunScreen.tsx#L145), [239](../../apps/factory-dashboard/src/features/autorun/AutoRunScreen.tsx#L239), [autorun/service.py:651](../../modules/factory/autorun/service.py#L651), [DEV_LOG.md:60](../../DEV_LOG.md#L60). Label the actual scope and expose the supported audited update fields. |

## Remaining workflow, qualification and documentation work

These are not all code defects and are not permission to run paid work or revive
an operator-aborted delivery. Current provider balances and private financial
records were not inspected.

| ID | Remaining work | Current evidence and boundary |
| --- | --- | --- |
| W01 | **Connect accepted autorun completion to verified Drive delivery and cleanup.** | `_finish` still advances to done with a delivery-pending note. The standing completion rule also requires verified upload, stopping the video's services, free-port verification and a Drive link. Represent render completion separately and complete the authorized delivery workflow when appropriate. [autorun/service.py:1953](../../modules/factory/autorun/service.py#L1953), [completion rule](../google-drive-uploads.md). Existing aborted delivery stays aborted. |
| W02 | **Resolve the original-copy requirement versus close-copy behavior.** | Deterministic control A remains verbatim source narration and fit repair may restore source text. Operator docs now disclose this correctly, but PROGRESS explicitly retains the need for a run-level provenance exception/choice. Decide and encode that scope against the handover's new-copy requirement. [scripts.py:1](../../modules/factory/autorun/scripts.py#L1), [PROGRESS.md:23](../../PROGRESS.md#L23), [handover](../viral-video-factory-handover.md). |
| W03 | **Reconcile actual charges and the historical overrun.** | The log records 40 reservations settled at their reserved amounts as estimates and about 2.54M microdollars over an 18.37M cap. Adjustment and audited overrun-resolution endpoints now exist; their existence does not reconcile those records or establish the incident's cause. Match provider evidence to attempt/reservation identities and document the outcome. [DEV_LOG.md:1442](../../DEV_LOG.md#L1442), [budget/service.py:235](../../modules/factory/budget/service.py#L235). |
| W04 | **Qualify the complete live production/publication/learning journey.** | Offline fixes and a locally rendered quartet do not establish corrected real-run outputs, human product/voice/creative acceptance, verified delivery, exact native publication/account/cancellation behavior, elapsed analytics horizons and a grounded next-round decision. The incident artifacts remain unchanged. Qualify only missing route/model/input scopes; scoped analysis/music/Vertex evidence must not be discarded. [current status](../../PROGRESS.md), [investigation](INVESTIGATION-auto-cd98a5cf5308471b.md), [publishing-learning handover](../factory-publishing-learning-handover.md). |
| W05 | **Complete F-module checklists and independent legacy gate sign-offs.** | F00–F34 remain engineering/manual `in_progress`; F35 remains blocked. G1–G12 remain independently pending. Reconcile specific checklist evidence and missing criteria rather than treating a green test count as acceptance. [factory tracker](../viral-video-factory-module-tracker.md), [G-gates](../gates.md). |
| W06 | **Correct status claims and link current evidence consistently.** | PROGRESS now has a useful current index and the legacy review has a scope banner—those earlier problems improved. However, “all 16 patched” conflicts with F01/F06/F10; the revision/hold guard claim conflicts with F03; the dashboard claim conflicts with F12. The tracker still says all live qualification is pending despite scoped pilots. New incident entries are appended beneath older entries while DEV_LOG claims newest-first ordering. Its historical shutdown note also contradicts today's combined stop script. Preserve history, annotate its scope, and use this follow-up to update current dispositions. [DEV_LOG.md:10](../../DEV_LOG.md#L10), [1477](../../DEV_LOG.md#L1477), [tracker:15](../viral-video-factory-module-tracker.md#L15). |

## Legacy backlog still present

These are separate from factory acceptance and are not newly reopened factory
failures. No changes to these implementations appear in the repair commits.

- **L01 (P3):** positional `zip` labels readback windows incorrectly if configured
  hours are reordered, shortened or extended. [windows.py:13](../../modules/analytics/windows.py#L13).
- **L02 (P3):** `write_task`'s fallback path trusts the subject/video ID; absolute
  paths or traversal can escape the production root. The usual caller supplies
  a directory, limiting exposure. [task_builder.py:48](../../modules/assemble/task_builder.py#L48).
- **L03 (P3):** very short scripts can produce fewer than four shots and fail
  schema validation later; give a direct stage error or a valid splitting policy.
  [shots.py:43](../../modules/script/shots.py#L43).
- **L04 (qualification/setup):** authentic hook curation, radar-derived format
  refresh, legacy voice selection, live cron verification, full MPT subtitle/
  Whisper validation and first-live analytics metric/unit verification remain
  documented. The legacy produce flow also asks for spend approval before its
  missing-key/voice preflight. Working factory routes do not close these legacy
  tasks; historical key/balance statements are not current account evidence.
  [legacy remaining issues](../REMAINING_ISSUES.md), [G-gates](../gates.md).

Retired Viral Outliers research is an explicit scope decision, not an outstanding
instruction to reactivate it or buy credits.

## Repair disposition and verification

- Prior C01/C02/C04–C07/C09–C14/C16 have relevant repair implementations;
  C03/C08/C15 retain the specific gaps above. The new C13 verifier has F09.
  This is not a claim that every possible edge case of the other repairs is proved.
- Saved diagnostic probes: **14 scenarios reproduce remaining defects**, using
  mocks, temporary files and two tiny locally generated MP4s. No provider calls.
- Dashboard: **30 tests passed**, and TypeScript/Vite production build passed.
- Full backend suite: **1,128 passed**, two dependency deprecation warnings,
  **751.01 seconds**. Run offline with local process-inspection permissions;
  provider calls remained mocked. These existing regressions do not cover the
  separately reproduced defects above.
- Review changes are limited to this report and its diagnostic probe file.
  Frozen contracts, production source and runtime records were left unchanged.

Prioritize F01/F03/F04/F05, then repair revision/expiry/translation recovery,
proxy selection and publication verification. Complete financial and acceptance
work against the corrected, identified source revision.

## 2026-09-20 live-run dispositions (nFfa1wMBruo)

Browser-driven production of `https://www.youtube.com/shorts/nFfa1wMBruo` on
`feat/factory`, autorun `auto-22d6ceaed2f2433c`, experiment
`exp-auto-22d6ceaed2f2433c` rev 2. This does **not** close the inventory
above unless a finding actually reproduced and was fixed. Human creative
acceptance was not invented.

| ID | Disposition after this run |
| --- | --- |
| F01 | Not reproduced (no replacement finals after a cached creative verdict). Still open. |
| F02 | Not reproduced. Still open. |
| F03 | Not reproduced as an edit-while-paid-jobs-active case. Still open. |
| F04 | Not reproduced (source was 30fps). Still open for 24→30. |
| F05 | **Partially closed.** Unchanged-region mix QC smeared a 22,050 Hz beat boundary when forced through 48 kHz; native-rate compare now passes C/D without regenerating Vertex clips. Export-vs-mix audio content/alignment check is still open. |
| F06–F12 | Not the blocking path of this seed. Still open as recorded. |
| W01 | **This video's authorized Drive workflow is done** (verified parent/name/bytes/MD5, ports 5184–5188 free). Autorun `_finish` still marks done with a delivery-pending note — the code gap remains. |
| W02 | Unchanged: control A is still source-derived narration. |
| W03 | Unchanged: historical overrun not reconciled. This run's VG/TTS holds are recorded in `DEV_LOG.md` (Vertex 7,134,640 usd_micros held on 8 downloaded clips; 765,130 released pre-acceptance; TTS 222 credits). Not invoice-confirmed. |
| W04 | This run is one scoped live production + Drive delivery. It is not native publication, elapsed analytics horizons, or a grounded next-round decision. |
| W05–W06, L01–L04 | Unchanged. |

Offline suites after the live-run repairs: backend **1139 passed** (703.44s),
dashboard **35 passed**, dashboard production build green. Frozen schemas and
fixtures were not changed.
