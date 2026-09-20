# Dev Log — Short-Form AI Video System

Running record of coordinator work on this repo. Newest session on top.
Builder context: modules M1–M12 were implemented by the K3 builder from my
/goal prompt; everything else below (planning, Wave 0, reviews, patches,
decisions) is my direct work.

---

## 2026-09-19 — Review-finding patch: all 16 items (REVIEW-2026-09-19)

Second independent review found 16 code/recovery issues; all verified
against source and patched in dependency order, each with regression
coverage. Offline only — no paid calls in tests.

### Paid-work atomicity (C01, C02)

- Effect plans are now content-keyed (`plan_hash` → stable id) with
  get-or-create semantics; `_run_effect` persists plan id, authorization
  id and job ids **between** commits, and reuses an existing
  authorization when `scope_hash` matches — a crash after queue commit
  no longer mints a second plan/auth/job set. Explicit budget-blocked
  resets bump `{tag}_plan_seq` so a deliberate re-plan never reuses dead
  job identities.
- Music adapter no longer maps `x-credits-remaining` (a balance) to
  `actual_credits`; missing actuals stay unknown instead of becoming
  false spend.

### Fail-closed review (C03, C04, C15, C16)

- Final QC dispatch records `{artifact_id, sha256}` per variant; a final
  replaced after submission discards the stale verdict, reviews the new
  bytes once, then pauses — an old review can never stamp new bytes.
- `inspect_asset` fails closed: missing ffmpeg, timeout and nonzero exit
  now produce `uncertain` verdicts with explicit notes — a scan that did
  not run cannot pass.
- `auto_review_beats` promotes provider-declared `uncertain`/`unresolved`
  beats only when local evidence anchors the start edge (detected scene
  cut or media head); transcript overlap alone no longer manufactures
  "reviewed".
- Timeline coverage checks the full interval — union of segment ranges
  must cover `[0, duration]` without gaps or overlaps, replacing the
  three-point probe.

### Speech correctness (C05, C06, C14)

- TTS synthesis is bought once per normalized text while fit/attach run
  per segment occurrence — repeated lines across A–D each get their own
  speech record, target interval and captions off one paid synthesis.
- Fresh TTS requests are chunked into ≤20-op plans (`tts`, `tts_1`, …),
  each persisted under its own tag for clean restart/repair.
- ElevenLabs alignment accepts `normalized_alignment` equivalent to the
  request ("two" vs "2") — paid successes are no longer rejected for
  provider-side normalization.

### Honest pause/resume (C07, C08, C09)

- Flagged final QC: plain resume re-reads recorded verdicts (no
  duplicates); `resolve_qc=accept` writes a named human verdict and
  finishes; `resolve_qc=recheck` buys exactly one fresh paid review.
- `set_params` on resume audits changes to `limits`, `valid_until`,
  `visual_reviews`, `generate_music` — the pause's stated recovery is
  now actually actionable; the dashboard pause block exposes them.
- Requested-but-unavailable music or visual QC pauses with
  `capability_unavailable` and an explicit declared-fallback path
  instead of a silent note.

### Ops/accounting escape hatches (C10–C13)

- `POST /api/reservations/{id}/adjust` upgrades a settlement up the
  confirmation ladder (estimate → reported → invoice); the prior entry
  is preserved in a `settlement_adjusted` event. Downgrades refused.
- `POST /api/budgets/resolve-overrun` lifts the `spend_overrun` dispatch
  block with operator + evidence + resolution recorded; the overrun
  event stays in the ledger.
- `factory-up.sh`/`factory-down.sh` now launch via the checkout's
  absolute `.venv` path, record `.run/*.pid`, and match only this
  checkout's processes — a sibling repo's workers can no longer be
  killed by a stray `pkill -f "modules.factory.cli"`.
- `UploadPostPublisher` gains a real `youtube_post_verifier` (Data API
  `videos.list` over the qualified analytics transport, wired in
  `configured.py`); a missing verifier is reported by `readiness()` and
  rejected as `platform_verifier_unavailable` — a capability error, not
  a mid-flow transport crash.

### Docs (W02, W06)

- Operator guide documents the declared copy provenance (control A is
  verbatim source-derived close adaptation; fit fallback reverts to
  source copy, never invented words), the resume resolutions
  (`resolve_qc` accept/recheck, `set_params` for limits/validity/
  visual QC/music), capability-fallback pauses, per-unique-line TTS
  billing, the checkout-scoped pidfile lifecycle, and the settlement
  upgrade + overrun-resolution routes; the safety-rules and
  troubleshooting sections list the new enforcement points
  (QC-binds-to-bytes, scan-can't-pass, preserved uncertainty,
  crash-can't-double-charge) and recovery rows for
  `final_qc_flagged`, `capability_unavailable`, `spend_overrun` and
  `platform_verifier_unavailable`.
- `docs/factory-operations.md` updated to match: pidfile +
  absolute-path process scoping, the YouTube Data API manual-post
  verifier (`platform_verifier_unavailable` when absent), and the
  `adjust` / `resolve-overrun` accounting routes.
- DEV_LOG order restored to newest-on-top; PROGRESS header is now a
  current-status index pointing here. W01/W03–W05 and L01–L04 remain
  recorded follow-ups.

### Verification

- New regression tests: C01 crash-resume dedupe, C02 balance≠charge,
  C03 stale-final resubmit, C04 scan failures, C05 repeated-line
  attachment, C06 two-batch dispatch, C07 flag→recheck→accept,
  C08 limit/param updates, C09 both capability pauses, C10 adjustment
  ladder, C11 overrun resolve, C13 verifier surface, C14 normalization,
  C15 evidence anchoring, C16 interval coverage.
- Backend: **1105 passed, 0 failed** (full suite, ~15min).
- Dashboard: 30 tests passed; `npm run build` clean.

---

## 2026-09-19 — Automatic seed → A–D pipeline ("Auto" tab)

### What was built

- `modules/factory/autorun/` — durable orchestrator: an `autorun` record
  plus one self-deferring `auto_step` worker job drives intake → evidence →
  video_analysis → sections → analysis_review → blueprint → template →
  script → music → draft → tts → quote → authorize → run → footage →
  compose → final_qc → done. Waits defer through the scheduler (survives
  worker restarts, no busy loop); failures pause with code/detail/action.
- `autorun/scripts.py` — deterministic adaptation: A close control, B hook,
  C body, D ending; each declares changed factor, hypothesis, primary
  metric and changed region. Optional qualified `adapt_script` LLM route;
  failure pauses (`script_llm_failed`) and resume falls back to
  deterministic scripts instead of re-dispatching a dead job.
- `autorun/review.py` — automated asset/final inspection (streams, duration,
  resolution, black/frozen frames) written as `reviewer_type="automated"`
  Review records bound to artifact id+sha and plan hash; the production
  selector resolves awaiting_review nodes from these records.
- Vertex adapter gained `adapt_script` and `review_final` tasks;
  `generated_music` added to the Authorization provider whitelist;
  `QualityService.record_verdict` accepts `reviewer_type`.
- Finals stamped with `plan_id`/`experiment_revision`; `experiment_results`
  exposes only current-plan finals — older renders can never be relabelled
  as a new revision.
- Budget semantics fixed: authority caps cover unit totals; exhausted
  budgets pause as `budget_exhausted`; resume accepts `budget_ids`
  (replace) / `add_budget_ids` (add), validated and audited.
- Dashboard: Auto tab (seed link + media attach, voice, budget checks,
  per-operation limits, music/visual-QC toggles, stage bar, pause card
  with resume-including-budgets); Compare shows pending states and
  per-variant hypotheses, changed sections and QC checks.
- API: `POST /api/autoruns`, `GET /api/autoruns/{id}`,
  `POST /api/autoruns/{id}/resume`; `autoruns` collection.

### Verification

- `tests/test_factory_autorun.py`: 8 passed (offline, fully mocked) —
  seed→4 renders, rollback, revision scoping, receipt backup/restore,
  caller-process loss, malformed command rejection, render capacity after
  expired worker, OAuth redaction, fractional frame-rate caption clocks.
- Full backend suite: 1075 passed; the pre-existing
  `test_full_publish_learn_next_round_journey` failure at HEAD
  (expected `provisional_winner`, got `no_improvement`) deselected —
  unrelated, reproduced on a clean stash.
- Dashboard: 30 tests + production build green.
- Live smoke: `POST /api/autoruns` over the real API created a durable run;
  the worker advanced it to an honest `missing_source_media` pause with a
  resume action — zero paid calls.

### Honest boundaries

- Real paid end-to-end (live Vertex/Jimeng/TTS) not yet run — needs an
  authorized budget covering the exact run plus Drive-delivery completion.
- No paid fallback was inferred; every pause is explicit.

## 2026-09-19 — Autorun hardening: holds UI, self-repair, honest pauses

Follow-up fixes after the first real end-to-end run (`auto-5d3717e`,
which succeeded but needed 16 manual resumes).

### Spending authority

- `GET /api/reservations` lists open holds; `POST
  /api/reservations/{id}/settle|release` let an operator close a hold
  with evidence — settle at the actual charge (`invoice_confirmed`,
  `usage_estimate`), release only when the attempt verifiably never
  charged (failed/cancelled/prepared or no attempt). Both audited with
  reviewer identity.
- Budgets tab gained an **Open holds** table driving those routes.
- Resume copy and the autorun coverage check now state the real rule:
  an aggregate ceiling is held in full on every applicable operation —
  adding a second aggregate budget does not add headroom.

### Click-once reliability

- Script adaptation now word-budgets LLM copy against each beat's
  seconds; over-budget lines fall back to source-derived copy with a
  note instead of failing the measured fit downstream.
- Measured speech-fit failures trigger a bounded repair (swap that one
  segment to source-derived copy on a new draft revision); one repair
  per segment, honest pause after that.
- TTS results are reused across revisions by normalized text — editing
  one beat no longer re-buys every other line.
- Local compose timeouts (`TimeoutExpired`/`RenderTimeout` on `cmp`
  jobs) are bounded scheduler retries, not pauses; `raise_worker_errors`
  no longer re-raises handled retries.

### Observability and ops

- Pause history persists: every pause keeps code + detail + action in
  `run.progress`, shown under **Pause history** after resume.
- `done` now carries an explicit note that it is not verified Drive
  delivery; disabled visual QC is noted too.
- Worker rides through `database is locked` contention with bounded
  backoff; `factory-up.sh` verifies the worker is still alive after
  launch and prints the log tail if it died.
- `GET /api/assets/{id}/media` returns 404 `unknown_artifact` instead
  of a 500.
- `tsconfig.tsbuildinfo` untracked (generated build cache).
- Fixed two date-anchored tests: `test_q07_observe_job_defers_then_completes`
  (pinned the scheduler clock) and
  `test_full_publish_learn_next_round_journey` (the deliberate youtube
  collect must observe after the readback clock's OBS_AT or ranking
  prefers the stale auto-collected snapshot).

### Verification

- Full backend suite: 1085 passed, 0 failed (previously-failing
  time-bomb tests included).
- Dashboard: 30 tests + production build green.

## 2026-09-19 — Production DB cleanup after first live run

Operator-level maintenance on `data/factory/factory.db` following the
`auto-5d3717e` run; no code changes.

### Holds settled

- All **40 open reservations settled** at their reserved amounts with
  `kind=usage_estimate` via the new operator settle path — every linked
  attempt was `downloaded`/`succeeded`, so the paid work verifiably ran.
  Audited as `reservation_settled_by_operator` events.
- **Overspend exposed:** `syp34-vertex-approved-4590780` is over its
  18.37M µUSD cap by ~2.54M — repeated authorization rounds each held
  against the aggregate ceiling and settled usage exceeded it. The
  negative `available` is intentional honest accounting; do not
  authorize further work under that budget.
- Remaining headroom: `syp34-vertex-approved-6886170` ~522K µUSD,
  `lezys-tts-approved-2000` 325 credits.

### Aborted delivery and smoke residue

- The 4 `awaiting_review` delivery jobs for the autorun experiment's
  plan (`plan-a8d8a661`) cancelled — operator aborted Drive delivery —
  recorded via a `delivery_aborted` event. Twenty pending delivery jobs
  on other experiments (`exp-dog-ball-*`, `exp-ev-ranking-01`,
  `exp-syp34-*`) were left untouched.
- Smoke-test residue removed: autorun `auto-d91f3120c63a4f62`, its
  autostep command record and job, and seed `seed-youtube-5f6b0b4e201f2a7e`.
  The append-only event ledger was retained.

### Shutdown

- Full stack stopped: API (:8100), worker, hypit runtime worker, and
  the whisperx.local program (:8765). `media.local`/`hyperframes.local`
  keep stale "ready" records in the runtime DB but hold no ports —
  reconciled on the next `runtime up`. Logs truncated.
- Docs note added: `factory-down.sh` stops the API and worker only;
  hypit programs need `./scripts/hypit.sh programs down`.

---

## 2026-09-18 — One-command stack launch

User asked to collapse the multi-terminal startup. Added
`scripts/factory-up.sh` / `scripts/factory-down.sh`: up runs
`hypit runtime up` (whisperx.local, media.local, hyperframes.local),
then nohup's one API (:8100) + one worker to `.run/*.log`, waits for
`/api/health`, prints status. Idempotent — running services are left
alone. Down stops worker+api, then `programs down` + `runtime down`
(scoped to this project's profile; the other repo's hypit worker is
untouched). `.run/` added to .gitignore. Operator guide §1 rewritten:
one worker only, the launcher, and the manual equivalent.

Also this session: EV analysis `ra-seed-youtube-fc05ef1e33f92865`
recovered to `evidence_ready` (whisperx `fetch failed` was a transient
service outage; rerun cleared it). Explained the recurring
`database is locked` — busy_timeout is 5 s and stage work holds write
transactions for seconds, so a second worker dies at first tick;
`zsh: terminated` was external SIGTERM (cleanup kills), never a code
path. Committed all accumulated work as `ce73c30` (63 files).

---

## 2026-09-18 — Remaining providers qualified (user approved pilots)

User approved the billable qualification pilots for all three remaining
routes. Results:

**audiovisual_analysis — qualified.** Pilot
(`data/production/v-vertex-analysis-pilot-20260918/`) exercised the real
`VertexAnalyzer.submit()`: ADC identity check, artifact verification,
`generateContent` inlineData, `parse_analysis`. First attempt surfaced a
real route defect — `gemini-2.5-flash` returned `confidence:"high"`,
outside the parser enum `{reviewed,uncertain,unresolved}`, because the
prompt never enumerated the allowed values. Fixed `PROMPT` to declare
the vocabulary explicitly; attempt 02 succeeded (HTTP 200, STOP,
1 305 in / 565 out tokens, $0.0018 vs $0.10 estimate). The failed
call left an honest `unknown` receipt — no re-dispatch, no double
charge. Evidence → `data/factory/qualification/analysis-{quote,operation}.json`;
connection `gemini-2.5-flash`/`global`, pricing 100k/250k µs,
`qualified_until` 2026-10-18, enabled. Also gave `VertexAnalyzer` a
real `readiness()` (was inheriting hardcoded `authenticated:false`).

**generated_music — adapter built + qualified.** No adapter existed;
built `modules/factory/providers/music.py` (`MusicAdapter`,
SynchronousAdapter → `POST /v1/music`, `music_v1`, `force_instrumental`,
mp3_44100_128) and wired it into `configured_auxiliary`. Live pilot
(`data/production/v-elevenlabs-music-pilot-20260918/`): 200, 161 KB
MP3. Credit metering is delayed — measured the subscription
character-count delta twice: **30 credits/second** exactly
(390 for 13 s, 150 for 5 s) drawn from the shared character pool.
Connection `music_v1`, `credits_per_second:30`, evidence recorded,
enabled. New tests `tests/test_factory_music_adapter.py` (4 green).

**viral_outliers — staged, awaiting credit top-up.** Auth verified
(200 on `/api/v1/credits`), dated pricing captured (1 credit/search,
$0.01/credit). The approved search pilot returned a real 402 —
balance is 0. Recorded contract evidence + connection
(`account_id` = key fingerprint), but `live_evidence`/`qualified_until`
stay empty and the route stays disabled until a successful search
after top-up (pack_s: 1 500 credits/$15 — user action).

`/api/providers`: 5/6 fully green. Focused suite 78 passed,
`git diff --check` clean. The analyzer prompt change is a qualified-
route fix; no test pinned the old prompt.

**viral_outliers removed.** Later the same day the user retired the
route ("no longer used") before any top-up: connection entry deleted,
the readiness tuple dropped it (board now lists 5 routes, all green),
and the `configured_auxiliary` construction branch was removed. The
research feature code (`integrations/research.py`,
`radar/viral_client.py`, `DiscoveryService`, `/api/research/*`) stays
in place but has no provider — `/api/research/plans` now returns
`route_unavailable`, verified live. The dashboard budget-unit dropdown
lost `viral_outliers_credits`; the unit itself remains in
`domain/money.py` for historical budgets. Pilot receipts stay under
`data/production/v-viral-outliers-pilot-20260918/` as honest history.

---

## 2026-09-18 — google_vertex qualified from existing pilot evidence

User completed `gcloud auth application-default login`; installed
`google-auth` + `requests` into `.venv` (the live auth boundary imports
both). ADC token identity verified as `david.dai@robanka.com` via the
token-info endpoint; the ADC file's empty `account` field was corrected
to that observed identity (records truth, not new credentials).

No new billable call was needed: the documented 2026-09-17 pilot
(`docs/vertex-video-test.md`, receipts under
`data/production/v-vertex-video-pilot-20260916/`) already proves the
exact route — `gemini-omni-1.1-flash-preview`, location `global`,
text input, 4 s 720p 9:16, $0.409384 usage at dated published rates.
Copied `receipt.json`/`cost-estimate.json` into
`data/factory/qualification/vertex-operation.json` /
`vertex-quote.json`, recorded the `capabilitysnapshot`
(`cap-google_vertex-…-global-text`, support `qualified`, documented
capability surface, `valid_until` 2026-10-18), and corrected the
connection: `location` `us-central1`→`global` (must match the
qualified route), `rates` populated from the verified pilot numbers
(dated 2026-09-17, 5 792 video tokens/s, $1.50/$17.50/$9.00 per M,
1.25 reservation), `contract_evidence`/`live_evidence` set to the
receipts, `qualified_until` 2026-10-18, added to `enabled`.

`GET /api/providers` now reports all flags green for google_vertex —
installed/authenticated/catalog/contract/live. Verified: 25 QA +
19 provider/readiness tests green, `git diff --check` clean.
Reference-media input modes remain unqualified (adapter hard-rejects
them) — only `text` was piloted.

Still blocked, honestly: `audiovisual_analysis` (needs a live
`generateContent` pilot — billable, awaits authorization),
`viral_outliers` (needs `account_id` + pricing + pilot),
`generated_music` (no adapter exists; imported music only).

---

## 2026-09-18 — Local WhisperX configured; capability probe fixed

User chose the local-WhisperX route. `hypit runtime init` created the
project Runtime Profile; merged `whisperx.local`
(`@hypit/provider-whisperx-local`, bundled in the vendored
distribution) plus the required
`@hypit/whisperx@1#whisperx-alignment` binding (needed because
hypihub.default also offers alignment). `runtime up` prepared the
locked uv env (whisperx 3.8.6, torch 2.8.0) and NLTK punkt_tab;
service is warm at 127.0.0.1:8765 — model `small`, cpu/int8, "local,
no Provider charge" per the CLI. `hypit transcribe` on the reference
audio produced 31 words / 8 passages / 93.513 s end-to-end.

Second defect found: `transcribe_available()` grepped
`runtime status --json` for "whisperx" — that report carries worker/
program counts, never endpoint names, so a fully configured service
still reported unavailable. Probe now reads `programs status --json`
(declared endpoint instances, including not-yet-warm ones). Both
seed analyses were re-imported with the canonical whisperx output
(provider `whisperx`, declared provenance) and re-ran to
`evidence_ready`, `blocking: []`, transcript-linked grids rebuilt.

**Verification:** new test asserts the probe calls
`programs status` and detects declared endpoints; live `doctor`
reports zero diagnostics; factory transport returns
`transcribe_available: True`. `hypit.runtime.json` is new project
config (untracked — commit decision left open); `.hypit/` stays
gitignored machine state.

---

## 2026-09-18 — Transcript-import format fix + live recovery (seed-youtube-47a6411c25932535)

A real analysis run blocked correctly at the speech gate (speech
detected, no WhisperX endpoint, captions insufficient). Importing a
locally produced word-timed transcript surfaced a genuine defect:
`import_transcript` wrote a proprietary `{words: [...]}` file, but
`hypit media tiles --transcript` requires `hypit.transcript@1`
(passages of `text`/`start_seconds`/`end_seconds` words), so the
evidence stage re-blocked with "expected hypit.transcript@1". The
test fake wrote the same wrong shape, masking it.

Fixed: `import_transcript` now writes `hypit.transcript@1` via
`_hypit_transcript` (flat words grouped into passages at >2s gaps —
no invented data); `_transcript_words` reads `passages[].words`
(also repairs `word_count` on the real WhisperX path, which
previously always counted 0); a clean `run_machine_stages` clears
stale `blocking` entries. `FakeHypit.transcribe` now writes the real
format so the seam can't mask it again.

**Live recovery executed:** extracted 16 kHz mono audio from
`art:695a70cd86513d2d` (93.521 s), ran local faster-whisper 1.2.1
`small.en` (`word_timestamps=True`, `vad_filter=True`, fully
offline — model already in the HF cache), imported 23 word-timed
entries with declared provider+provenance through the real API
route, re-ran the durable analysis job. Result: `evidence_ready`,
`blocking: []`, 8 transcript-linked grids. Operator understanding/
timeline/treatment/review steps remain — the gate holds until a
human reviews.

**Verification:** `tests/test_factory_analysis_gate.py` +
`tests/test_factory_application.py` 26 passed including a new
regression test asserting the written file satisfies the hypit
reader contract.

---

## 2026-09-18 — Review-finding patch: all 15 items (REVIEW-2026-09-18)

Every finding in `docs/factory-reports/REVIEW-2026-09-18.md` verified
against code + spec, then patched in five waves. The seven
reproduction probes in `docs/factory-reports/probes/` were inverted
to assert repaired behavior and now pass as regression tests;
`tests/test_factory_review_fixes.py` adds permanent coverage for the
unprobed findings (Q03 worked cases, Q06 retry/backoff + complete-day
horizons, Q07 observe-job lifecycle, Q10 dispatch gates, Q14
evidence/account plumbing, Q09 honest limitation). Resolution status
is recorded in the review report itself.

**Verification:** full backend suite 1062 passed (from the 1047
post-decision-patch baseline — +15 net: the new review_fixes file),
7/7 inverted probes green, dashboard 29 Vitest green (+1 Q12 test),
`tsc --noEmit` clean, `vite build` green, `git diff --check` clean.

- **Selection correctness (Q01, Q03, Q14).** `_evaluate_seed`
  reimplemented to the frozen §9.3 contract: eligibility requires
  exposure AND guardrails on every required lane; per-platform ranks
  with averaged ties; Borda score `100×(4−rank)/3` weighted by frozen
  weights; `min_margin` enforced against the next eligible contender;
  exact top-score ties are inconclusive; A retains control when
  eligible; `weighted_lift` improvement is Σ weight·relative-lift
  (with `denominator_floor`), `min_platforms` counts named required
  lanes where the challenger beats A AND passes exposure. Inadequate
  control exposure → `insufficient_exposure` → inconclusive.
  `select_seed` gained `account`/`accounts` scoping; decision ids
  carry `-{account}` suffixes and are stored on the selection with
  snapshot `evidence_ids` in basis; per-platform `primary_metric`
  overrides apply per lane.
- **Evidence honesty (Q02, Q04, Q05, Q15).** Late lifetime-at-age
  snapshots (>1.25× requested age — the existing `actual_coverage.late`
  semantics) are ineligible for that checkpoint rather than silently
  crowning a winner; `max_late_hours`/`max_upstream_age_hours` policy
  fields add declared bounds. Complete-day windows include the
  publication day when it begins exactly at the source-day boundary
  (§8.2) and `expected_days` derives from the requested `start`, not
  the local publish day — the permanent off-by-one `partial` is gone.
  Completeness gates on required analytics coverage; optional
  thumbnail reach is recorded in availability/failed_routes but no
  longer blocks a valid Shorts comparison. `shares` joined
  `PULL_METRICS`/`NORMALIZED`; Shorts average duration/percentage
  weight by `engagedViews` with `views` fallback (same-window
  denominator, never the lifetime public counter), with the
  denominator recorded in coverage/metric definitions.
- **Durability (Q06, Q07, Q08).** Checkpoint collection inspects
  snapshot completeness — pending/partial/failed evidence leaves the
  schedule `retrying` with bounded exponential backoff
  (`next_delay`, MAX_ATTEMPTS, then honest `failed`); `7d_complete`/
  `28d_complete` ride the same durable schedule (the capability gate
  was inverted — fixed). A provider-confirmed `scheduled` post now
  enqueues a `publication_observe` job that self-defers (bounded 24h
  past the fire instant) until reconcile confirms public — only then
  do checkpoints schedule. `cancel_remote` reads the provider's
  response body: `{success:false}`/transport failure → `cancel_failed`,
  still-scheduled reconcile → `cancel_failed`, public → `already_public`;
  local `cancelled` only on provider-confirmed cancel.
- **Loop mechanics (Q09–Q13).** `propose_next` checks for an existing
  child BEFORE the round limit (replay idempotent under default
  `max_rounds=1`); the child seed carries `platform='local'` and gets
  the champion's accepted local artifact attached via
  `SeedRegistry.attach_media` — success reports `media_ready` with the
  artifact id, absence reports `no_winner_artifact` (never invented
  readiness). Loop policies now gate dispatch, not just proposals:
  `queue()` and `execute()` consult `_loop_gate` — paused → defer
  (resumable), halted/expired → block, `allowed_providers`/
  `allowed_accounts` enforced per slot. Mature supersession marks
  child `RoundLineage` basis `superseded` with an audit event.
  Dashboard can freeze a first loop for a fresh series — the id is
  derived from the selected experiment's seed group with a manual
  fallback (Q12; new Vitest covers it).
- **Fake fidelity.** `FakePublisher` scheduled jobs now fire at
  `scheduled_date` when `now_fn()` reaches it — the provider holds,
  then publishes, rather than staying scheduled forever.
- **Fixture update.** `test_factory_publishing_e2e._collect_all`
  collects at `published_at + horizon` (the instant the delayed job
  fires) — collecting at wall-clock now records an honestly-late
  snapshot that no longer represents the age.

Still human/config (not code): live provider qualification, a real
four-variant journey, F-module sign-offs, WhisperX, raw-JSON forms,
invoice settlement.

---

## 2026-09-18 — Decision-layer gap patch (findings review)

Four verified code gaps patched; full suite 1047 green (+3 new tests
in `tests/test_factory_decision_windows.py`):

- **YouTube non-midnight windows decidable.** `collect()` no longer
  downgrades fully-covered snapshots to `partial` for non-LA-midnight
  publish times — `coverage['exact_horizon']` and
  `requested_period.window_kind` carry the measurement definition, so
  `source_calendar` windows are `complete` when their days are covered.
  `_window_expect` now returns an accepted-kind set per lane:
  `{'exact_rolling','source_calendar'}` for YouTube elapsed horizons,
  `{'source_calendar_window'}` for complete-days,
  `{'observed_lifetime_at_age'}` for non-YouTube. Decisions computed on
  a source-calendar window carry an explicit limitation line.
- **Eligible snapshot pick.** `_snapshot` ranks candidates by (window
  kind/hours acceptable to the policy, completeness, observed_at,
  revision) instead of unconditional latest — a later pending retry no
  longer masks a complete earlier sample.
- **Account-aware publication key.** `_publication_for` filters
  `(variant, platform, account_id)`; `decide()`/`_evidence`/worker
  `decision`/API accept `account` and suffix decision ids
  `-{account}`. Unscoped multi-account slots still resolve to honest
  `missing` rather than guessing.
- **`engagedViews` collected.** Registered in `ANALYTICS_PER_VIDEO`,
  `PULL_METRICS` and `NORMALIZED` (`engaged_views`) so it can be frozen
  as primary/exposure metric; optional for completeness like
  `public_views` (absence doesn't downgrade the snapshot).
- **Vertex analysis cap configurable** — `audiovisual_analysis`
  connection gains optional `max_bytes` (default unchanged at 20 MiB).
- One test expectation updated (`repairs_learning`): covered
  source-calendar window now asserts `complete` + `window_kind` +
  `exact_horizon=False` instead of `partial`.

Not patched (needs humans/config, not code): WhisperX for spoken
analysis, F-module sign-offs, `connections.json` qualification review
(file exists — Canvas/ElevenLabs/Drive enabled with dated evidence;
Vertex slot lacks qualification), raw-JSON forms, invoice settlement
for unknown charges.

## 2026-09-18 — CAS convention unified on row `version`

`MetadataPackage` keeps a stable `revision` (identity); mutations are
in-place at that revision, so compare-and-swap uses the `records` row
`version` for both `select` and `freeze` (unified — previously mixed).
The API now exposes `version` on every collection row and on
`GET /api/metadata/{id}` so clients have the handle to send back;
the dashboard's metadata actions send `pkg.version`. Handover §5.1
gained the two-handle rule so future in-place records follow the same
convention. 17 targeted tests + E2E re-verified green.

## 2026-09-18 — Publishing/learning implementation complete (W0–W9)

Staged implementation of `docs/factory-publishing-learning-handover.md`
landed in nine waves, each verified before the next started. Baseline
was locked at 990 passing tests before any change; the full suite now
runs **1044 passed, zero regressions** under `make test`'s interpreter
(`.venv` Python 3.14 — note: `modules/factory/analytics/client.py` uses
PEP 701 multi-line f-strings and does not parse under system Python
3.11; always run tests via `make test` or `.venv/bin/python`).

- W1 contracts — additive `Publication`/`Seed`/`DecisionPolicy` fields
  plus five new records: `MetadataPackage`, `SeedSelection`,
  `CheckpointSchedule`, `RoundLineage`, `LoopPolicy`.
- W2 analytics capability layer — `24h`/`72h` horizons,
  `PLATFORM_METRICS` per-platform normalization,
  `WINDOW_SOURCES`/`window_capability` gate wired into
  `freeze_policy` (`window_capability_missing` on unsupplied mature
  windows), non-YouTube windows labeled `observed_lifetime_at_age`.
- W3 metadata stage — `modules/factory/metadata/service.py` with
  platform field limits, required disclosure answers, CAS via row
  version, frozen-package binding in `PublicationWork.plan` with
  `metadata_stale`/`metadata_variant_mismatch`/platform checks.
- W4 destinations — `UploadPostPublisher` gained `analytics`,
  `cancel_schedule`, `destinations` (provisional contracts);
  `PUBLISHABLE`/`MANUAL_PLATFORMS` extended to all four platforms;
  `plan_batch` fans out up to 16 slots with per-variant review +
  frozen-metadata auto-attach and per-slot errors; `cancel_remote`
  reports `cancelled`/`already_public`/`cancel_failed`/`not_scheduled`.
- W5 checkpoints — `CheckpointService` + `enqueue(not_before=)`;
  public-transition hook schedules 24h/48h/72h/7d/28d readbacks once
  per publication; late/missed labeling; worker `readback` routes via
  the checkpoint service.
- W6 learning — `decide()` accepts `platform=` and reads per-
  (variant, platform) publications; `select_seed` implements the
  six-step evaluation (validity → eligibility → ranks → weighted score
  → improvement rule → outcome) keyed by `(experiment, revision,
  horizon)` + `inputs_hash`; lineage-aware independence counting.
- W7 rounds — `modules/factory/services/rounds.py`: loop policy
  freeze/pause/cancel, bounded Round-2 proposal minting a derived seed
  (parent, round, independence group) + `RoundLineage`, idempotent on
  selection.
- W8 dashboard — Publishing and Learning screens (matrix, metadata
  freeze, authorize/run/cancel-remote, readbacks; policy, decisions,
  selections, lineage, loop controls) with the existing CSRF/
  idempotency/revision/SSE conventions; 28 Vitest + build green.
- W9 — offline E2E (`tests/test_factory_publishing_e2e.py`): 16 mocked
  destinations → public → auto checkpoints → 24h collections →
  per-platform decisions → champion-B selection → loop freeze →
  Round-2 proposal + idempotent replay. Operator guide gained a Step-7
  publishing/learning section and honest provisional caveats.

Deferred: live read-only probes (Treg/Monid/Blotato) pending explicit
credentials + qualification; Upload-Post qualification needs
`UPLOAD_POST_API_KEY`. A previously-committed `LONGFORM_PLAN.md` had
been deleted in the working tree (unrelated); restored.

## 2026-09-18 — Handover spec gaps resolved (P1×2, P2×2)

Four flagged contract gaps fixed in
`docs/factory-publishing-learning-handover.md` before implementation:

- §8.2 — mature `source_calendar_window` policy now gated on
  measurement capability at freeze time: Upload-Post's cache selects
  *when metrics were captured*, not *when views occurred*, so a
  required reporting window with no qualified source fails
  `window_capability_missing` instead of freezing an unusable policy;
  an explicitly approved `observed_lifetime_at_age` fallback freezes
  with honest labels.
- §9.2 — selection evaluation separated from child creation:
  `SeedSelection` keyed by `(experiment, revision, horizon)` +
  `inputs_hash`; retries return the same evaluation, new horizons or
  revised evidence mint `sel-…-v{N}`; one active child enforced
  independently with status flow waiting→provisional→confirmed/revised.
- §9.3 — fixed 6-step evaluation order: platform validity (unsafe
  control → `invalid_comparison` → `inconclusive`), global eligibility,
  ranks, weighted score, score-order winner evaluation under a declared
  `improvement_rule` (`weighted_lift`|`min_platforms`), explicit
  outcomes; five worked cases encoded as PL-T34.
- §10 — pause/series_cancel/authority_revoked matrix vs remotely
  scheduled provider jobs: pause changes nothing remotely, series
  cancel issues the provider's scheduled-job cancel per destination
  (`cancelled`/`already_public`/`cancel_failed`/`unknown`), revocation
  lists outstanding jobs without implying they won't publish.
- New acceptance tests PL-T31–PL-T35 covering all four.

## 2026-09-18 — Publishing/learning handover tightened + Blotato resolved

Review of the proposed four-platform publish→measure→select→reseed loop
against the live code, then gap-closing edits to the implementation
brief. No production code changed — this is documentation.

- `docs/factory-publishing-learning-handover.md` — added §3.1 "Exact
  seams": verified symbols the work must change —
  `_publication_for(variant)` returns a publication only when exactly
  one matches (16 destination posts would make every variant's coverage
  `missing`); `_snapshot` picks unconditional latest instead of
  checkpoint-eligible evidence; `decide()` enforces
  `window_kind=='exact_rolling'` + `HORIZONS[horizon]`;
  `freeze_policy` validates horizon/metric membership in
  `HORIZONS`/`NORMALIZED` (YouTube-column-shaped); worker commands are
  `publish`/`publication_observe`/`readback`/`decision` (decision
  carries no horizon/platform today); `connections.json` `publish`
  slot already reads `{user, accounts}`; loopback host allowlist means
  real provider webhooks get `403` — polling is the required path.
  Added §5.3 concrete record sketches (`MetadataPackage`,
  `SeedSelection`, `RoundLineage`/seed lineage fields, frozen
  `seed_policy` dict) and §9.2's decide-vs-select_seed separation
  (control-relative decision vs best-of-4 ranking where A can win;
  per-platform decision ids `dec-{id}-r{rev}-{horizon}-{platform}`).
- `docs/factory-publishing-provider-research.md` + handover §4.2/§15 —
  Blotato analytics conflict **resolved by direct evidence** from the
  connected MCP: `blotato_get_post_analytics`/`list_top_posts`
  descriptions state analytics cover X/IG/FB/Threads/Bluesky only —
  no YouTube, no TikTok, and background-refreshed not on-demand.
  Viable publisher, cannot power the learning loop. Upload-Post +
  native YouTube Analytics remains the primary route.
- `LearningService.independent_experiments` counts distinct `seed_id`s —
  flagged in the handover: derived Round-2 seeds must count by lineage
  root or independence is inflated (PL-T25 covers it).

---

## 2026-09-18 — Mandatory Hypit-directed reference analysis gate

Manual observations + YouTube captions could previously become an
accepted source blueprint and advance production — preliminary evidence
treated as understanding. Added a durable `ReferenceAnalysis` record
(`referenceanalysis.v1`, additive — no schema/fixture changes) and made
a reviewed deep analysis bound to the exact source bytes a prerequisite
for blueprint acceptance and every downstream production path.

- `modules/factory/analysis/deep.py` — `ReferenceAnalysisService` with
  staged machine evidence (acquire → transcript → evidence → documents)
  behind the durable `analysis_evidence` worker command; per-stage
  checkpoints make interruption safe and resume never repeats finished
  work (verified: transcript is not re-generated on retry). Transcript
  uses configured WhisperX via `hypit transcribe`; YouTube captions
  attach as `preliminary` only; no-audio → `not_applicable`; operator
  import/declare are the supported recoveries. Evidence is real hypit
  boundaries + full-duration (+ boundary close-up) frame grids intaken
  as content-addressed artifacts; hypit refuses existing `--to` dirs so
  rebuilds rmtree first. `HypitTransport` wraps `scripts/hypit.sh`.
- `analysis_gate` / `bound_gate` — shared enforcement. `analysis_gate`
  re-verifies substantive completeness (stages, transcript status,
  grids, coverage, all understanding fields, timeline, treatment), so
  a self-reported `complete` flag alone can never pass.
- Enforcement points: `BlueprintReview.accept` (gate + stamps
  `{analysis_id, revision}` binding; `analysis` excluded from blueprint
  content_hash so stamping doesn't rehash), `author_template`,
  `create_experiment_draft`, `quote_experiment`, `authorize_experiment`,
  `run_experiment`, and the worker `run` handler (`verify_run_gate`)
  for recovery/replay paths. Legacy acceptances with no binding fail
  closed with `analysis_required`.
- Revision semantics: operator edits on a `complete` analysis open a
  new revision (prior preserved, superseded); pre-approval edits stay
  in-revision. Source-sha or revision mismatch → `analysis_stale`.
- API: `POST /api/seeds/{id}/analysis`, `GET /api/analysis/{id}`,
  `PUT /api/analysis/{id}/{understanding|timeline|treatment}`,
  `POST …/transcript|declare|rerun|review`; `analyses` collection.
- Dashboard: real `AnalysisScreen` replaces the generic operations
  view — stage progress, capabilities, blocking + recovery actions,
  acquisition facts, transcript status, evidence-grid previews,
  plain-language understanding/timeline/treatment forms, review.
- Real run on `seed-youtube-47a6411c25932535`: acquisition verified
  (93.521s 1080×1920@30, audio), 12 boundary candidates, 8 grids
  covering full duration; transcript correctly `blocked` (no WhisperX
  endpoint configured) with three named recoveries. Old manual
  blueprint annotated `analysis_state: preliminary_manual`.
- Tests: `tests/test_factory_analysis_gate.py` (16) — preliminary
  blocked, stale sha/revision, bypass paths, nonverbal, resume without
  duplicate paid work, captions-can't-qualify, hand-forged `complete`
  rejected. `prepare()` in `test_factory_application.py` now completes
  a scripted-FakeHypit analysis before blueprint review; direct-accept
  tests seed a completed record. Full suite 990 passed; dashboard
  28/28 + build green.

Open: dog-and-ball transcript still needs a WhisperX endpoint (local
model prep or hosted profile — user decision, potentially a download/
spend) or an operator import/declare; understanding/timeline/treatment
forms and review are the operator's manual step in the dashboard.

## 2026-09-17 (evening) — Post-repair defect repairs N01–N20

The post-repair review at `c6ffad2` (`docs/factory-reports/REVIEW-POST-REPAIR-2026-09-17.md`)
confirmed 20 live defects against 952 green tests — proof that a green
suite did not mean unattended-production readiness. All 20 were repaired
in five staged waves per `REPAIR-PLAN-2026-09-17.md`, with zero DB
migrations (additive record fields, adapter-state files, `render.v4`
hash-material versioning).

- W0 `bab1004` — N02: `worker.tick()` classifies handler outcomes
  explicitly; unknown result states fail closed and release `local_work:`
  holds. Unsafe to revert alone.
- W1 `99bbe88` `c8dbe17` `e46bc21` — N04/N05/N06/N11/N12/N13: atomic
  Canvas quote merge-write, attempt-scoped Canvas/Vertex operation
  identity + wire-hash side index, content-bound render inputs, normalized
  aspect/resolution with conflict rejection, typed Canvas refs.
- W2 `901d09b` — N03/N09/N10: reconcile resumes remote-succeeded
  production jobs and unblocks descendants; delivery retry command +
  transfer-only service re-entry; runner attempt identity + retry_count.
- W3 `7822430` — N01/N07/N08/N16/N17/N19: publication revalidates creative
  acceptance at execution; normalized TTS fit/attach with provenance stamp
  (plus a real alignment defect fixed in audio/alignment.py — provider
  alignment was checked against normalized, not spoken, text); stale
  derived-media detection in diff + render hard-stop; pinned product
  snapshot revisions at authorize; claims validated across all variants;
  revision-scoped learning (new additive Publication experiment fields).
- W4 `c739802` — N14/N15/N18/N20: intentional_stills evidence from
  image-kind plan items (contiguous runs merged); frozen MixService
  profile per revision pre-mixes narration+music with measured loudness
  bound as final evidence; research discovery_cache consulted before
  attempts and written through, coverage counts real calls; readiness
  60s per-process cache + `?refresh=1`, run off the event loop, dashboard
  providers load on mount/manual recheck only.
- W5 `e9a7b82` `b2c64a8` — `tests/test_factory_repairs_2026_09_17.py`
  (21 regression tests asserting repaired contracts), the
  source_text-vs-normalized alignment fix surfaced by the N07 test,
  REPAIRS.md probe→test mapping, `pytest.ini` scoping default collection
  to `tests/` so bare `pytest` no longer dies on vendor/ deps, and the
  review report/plan/probes committed as the audit trail.

Verification: full backend suite **973 passed** (313.83s, offline,
no paid calls), dashboard **28 passed** + production build green. Every
original probe was rerun after its fix: all 19 fail on their old
assertions (the defect is gone), kept at
`docs/factory-reports/probes/review_post_repair_2026_09_17.py` as the
audit trail. Offline only — no publishing; live gates and
the F35 funded-pilot slice remain closed pending explicit authorization.

---

## 2026-09-17 — Factory repair program (S0–S8)

The independent review at `dae132a` found 43 issue groups. The earlier
F00–F34 end-to-end completion claim is superseded: component test passes
did not establish an integrated factory. Implementation and live gates are
reopened against `docs/factory-reports/REVIEW-2026-09-17.md`.

S0 begins with zero external effects. Existing dirty files, frozen contracts
and legacy financial state are preserved. Repair status/evidence is recorded
in `docs/factory-reports/REPAIRS.md`; prior entries remain historical.

Repair checkpoints now include S0 (`6c0f33a`), S1 (`006f274`), and the S2 shared
execution boundary (875 offline tests, 119.62s). S2 adds immutable approval
bindings, atomic effect preparation, persistent remote capacity, conservative
recovery and accurate charge variance accounting. Updated component fixtures
explicitly approve fake effects through the same boundary. Native adapter and
integrated application qualification are still pending; the factory is not yet
engineering-complete or production-qualified.

---

## 2026-09-16 → 2026-09-17 — Viral Video Factory build: F00–F34 (35 commits)

**Session outcome:** the durable factory documented in
`docs/viral-video-factory-handover.md` is implemented end to end —
F00 baseline through F34 failure drills. Suite **852 passed /
0 failed**, fully offline. All commits `feat/factory` branch. The only
remaining module is F35 (funded pilot / release handoff), whose live
parts need explicit spend authorisation.

### 1. What was built (by wave)

- **F00–F08 — foundations** (`f01` QA harness, fakes, fault injection;
  domain contracts + immutable revisions + typed money; SQLite store
  WAL/UoW/outbox/backup; artifact registry with probe + dedupe;
  prices/budgets/reservations/settlement; dependency scheduler with
  global capacities, leases, fencing; executor with submission
  recovery/retry/cancellation; events, telemetry, redaction, replay).
- **F09–F14 — intelligence** (seed registry + source acquisition;
  outlier discovery with real cohort medians; Shopify product/media
  snapshots; audiovisual reference analysis → timed blueprints;
  reusable format templates; frozen experiment control/treatment
  planning with declared change regions).
- **F15–F20 — providers + media** (shared generation contract +
  routing; Jimeng Canvas adapter with argv-level persistent fake CLI;
  Google Vertex adapter with OAuth boundary, exact pilot payload,
  HTTP-200 terminal-error parsing; reference packs; TTS/fit/alignment/
  captions; music beds + shared mix).
- **F21–F26 — production** (unique-work asset graph: shared work
  generated once, variant isolation, priced DAG; deterministic
  SVML/SVS/SVRun compiler gated by real `hypit check`/`plan`; render
  builds with section cache; technical + changed-region QC bound to
  output hashes; verified Drive delivery — intent-first, remote-first
  dedupe, content reconcile; identity-safe cleanup).
- **F27–F30 — surface** (FastAPI app: idempotent mutations, revision
  CAS, SSE replay, ranged media, local security; React/Vite dashboard
  with 15 vitest cases; monitoring/compare/review/delivery/studio
  screens; operations module: doctor/start/stop/drain/backup/restore).
- **F31–F33 — publication + learning** (manual + authorised automated
  publishing — public only on confirmed `published_at`; legacy
  `upload_post` defect fixed via new multipart adapter; analytics
  readback with coverage-aware unknown-vs-zero semantics; frozen
  decision policies, reproducible revisioned decisions, independent-
  seed promotion counting, hypothesis library).
- **F34 — failure drills** (new `tests/test_factory_e2e.py`, 14
  integrated drills).

### 2. F34 drill evidence (J01/J03/J04)

- **J01** seed→4 outputs offline: 6 shared + 3 unique picture works;
  only declared slots differ.
- **J03** crash-restart: kill after provider acceptance → reconcile
  finds the same remote id, zero duplicate submissions; kill after
  upload ack-loss → one remote upload total, verified.
- **J04** both provider routes: Jimeng totals in `jimeng_credits`,
  Vertex in `usd_micros`, 9 fake interactions.
- Plus: publication lost-ack → one post; budget cap enforced; global
  capacities across workers; stage timings attributed
  (`queue_wait_s`/`dispatch_s`); render cache parity by exact frame
  count; urllib hard-blocked through the whole flow; owned cleanup
  leaves unrelated processes; legacy entry points intact.

### 3. Defects the drills caught (fixed)

- **Vertex route never ran**: `GenerationAdapter` lacked the
  executor-facing `poll` — added as an `observe` alias on the base so
  both routes share one remote-lifecycle surface.
- **`remote_unfinished` deadlock**: a still-running remote op failed
  the download job permanently, stranding the capacity-1 Vertex hold —
  now retryable (job returns to `ready`, re-polled).
- **Vertex requests missed `model`**: plan-level model was priced but
  not injected into takes — fake correctly returned `model_not_found`.

### 4. Context day: 2026-09-15 (live pilots, pre-factory)

Recorded for continuity (commit-subject level): Vertex OAuth + Lyria/
narration verified; ElevenLabs API verified; Jimeng Canvas node-identity
+ timeout fixes with approved pilot results; Shopify intake + Jimeng
product-reference pilot; Viral Outliers integration with approved
credit batch; Drive access + delivered assets. These pilots produced
the wire contracts F16/F17/F25 later encoded as fakes.

### Verification (at log time)

- `pytest tests -q` → **852 passed, 2 warnings** (~106s), no network.
- Per-module reports: `docs/factory-reports/F00…F34.md`; tracker:
  `docs/viral-video-factory-module-tracker.md`.

### Open items handed forward

| # | Item | Needs |
|---|---|---|
| F35 | Funded pilot, release scope, engineer handoff | explicit spend authorisation for live slices; offline packaging can proceed without it |
| F34-M01/M03 | Operator UI journey + browser-disconnect pressure | human review |
| F31-M04 | Live post verification | authorised real publish |
| F32-M04 | Live analytics horizons | real post + 48h/7d/28d coverage |
| Prior S3–S5/V1–V3 | Keys, cron fire, verify-at-live | unchanged from 09-14 |

---

## 2026-09-14 — Planning → Wave 0 → K3 build → 2 review passes → 2 patch rounds

**Session outcome:** full system built and reviewed; 4 real bugs found and
fixed; suite **194 passed / 0 failed**; zero open bugs. Remaining open items
are all key- or live-run-dependent (see bottom).

### 1. Research & build plan (morning)
- Reviewed `github.com/harry0703/MoneyPrinterTurbo` for short-form generation
  fit; conclusion: usable as the local assembly engine (vendored, pinned),
  not as the intelligence layer.
- Folded the owner's stack choices into the design: Jimeng (Seedance) for
  video/image generation, ElevenLabs as the TTS upgrade, viralhooks.org
  patterns for the hook bank, outlier.so + `ericosiu/ai-marketing-skills`
  for early niche detection.
- Incorporated the two requested extra success steps as first-class modules:
  `shortform-format-library` → M3 Format Library (hook, 3 talking prompts,
  visual payoff, CTA — structure only, never copied wording) and
  `shortform-idea-grill` → M2 Idea Grill (kill weak ideas before spend).
- Produced `BUILD_PLAN.md`: 12 modules (M0–M12), each with its own unit
  tests and a signed validation gate (G0–G12), 9 frozen JSON contracts,
  cost ledger + hard weekly cap, exactly two human approvals per video.

### 2. Wave 0 foundation (commit `5b376f5`)
- Folder tree, `config/system.toml` + secrets templates, 9 frozen contract
  schemas + fixtures, vendored skill/MPT pins, G0 test set green.

### 3. K3 handoff (commit `94579c8`)
- Wrote the `/goal` build prompt for K3 — first a parallel-swarm edition,
  then (owner's call) the regular sequential edition in `GOAL.md`, with
  per-module build → unit-test → validate instructions.
- K3 then built M1–M12 sequentially (12:03–12:37), tests green at every
  commit. Not my code — recorded here for continuity.

### 4. Review pass 1 (commit `743d822`)
- Audited the fresh build. Found:
  - **B1** — weekly shortlist crashed with KeyError on contract-shaped
    ideas (sorted by nonexistent score field).
  - **B2** — verdicts compared AVD against a phantom hard-coded 30 s length.
- Listed plan deviations and the pre-live setup list (S1–S5).

### 5. Decision D1 (commit `559272c`)
- Owner chose macOS crontab over a Kimi Work Blueprint Automation for weekly
  scheduling. Recorded the decision, amended `BUILD_PLAN.md` §M11. Cron
  fires Monday 06:37 local (off-peak), shortlist lands in `data/weekly/`.

### 6. Patch round 1 (commit `322ddb3`)
- B1: sort shortlist by real score fields; corrected the drill fixture;
  added weekly shortlist tests.
- B2: QC stage now measures real duration via ffprobe → `video_len_s`
  stored in the publish record (the one approved additive contract
  exception) → verdicts compare against reality; added verdict-length tests.
- Partially addressed S1/S2: seeded format library with 10 pattern-based
  candidates; hook bank to 5/niche (curated entries ranked above
  `original-pattern` fillers by date).

### 7. Review pass 2 (commit `78ceb54`)
- Full line-by-line audit of all 67 module files. Found:
  - **B3** — `baseline_median_views` never populated: verdict views-leg
    always passed (over-reporting "win") and `promote._mult` divided by
    zero, so **no format could ever be proven** — the M3 learning loop was
    dead.
  - **B4** — live weekly wiring passed raw `scan()` output
    (`{"clusters": …}`) to `grill.run()`, which expects the contract shape
    (`{"niches": …}`) → silently empty shortlist every week, and the
    `data/radar/<date>.json` evidence artifact never written.
- Documented 6 minor notes (M1–M6) and 3 verify-at-live items (V1–V3) in
  `docs/REMAINING_ISSUES.md`.

### 8. Patch round 2 (commit `1ca66df`)
- B3: new `AnalyticsClient.channel_median_views()` (Data API key auth:
  channels `forHandle` → uploads playlist → videos statistics → median via
  `radar.metrics.channel_median`); `readback_stages.record` computes the
  baseline once per run and stamps it before scoring; new
  `YT_CHANNEL_HANDLE` secrets key added to both secrets files (parity test
  preserved). Fail-loud on API errors; `hasattr` guard keeps legacy fakes
  green.
- B4: `_live_weekly_clients.radar_scan` now composes
  `scan → build_report → write_report(data/radar/<date>) → return report`
  — the grill gets the contract shape and the G1 artifact is written every
  run.
- New `tests/test_readback_baseline.py` (5 regression tests): median math,
  loss/win verdicts vs a real baseline, 3-win promotion reaching "proven",
  and the full scan→report→grill composition.
- Suite: 189 → **194 passed**.

### Verification (re-run at log time)
- `make test` → 194 passed, fully offline (no network, no paid calls).
- `git status` clean apart from this log; secrets values never tracked.

### Open items handed forward (none are code bugs)
| # | Item | Needs |
|---|---|---|
| S3 | `voice_id` empty in `config/system.toml` | ElevenLabs key → 3-voice audition per `docs/voice-selection.md` (gate G7) |
| S4 | API keys | `YOUTUBE_API_KEY`, `YT_CHANNEL_HANDLE`, `PEXELS_API_KEY`, `ELEVENLABS_API_KEY`, LLM key, YT Analytics OAuth |
| S5 | Live cron fire verification | run `install-cron`, observe first Monday 06:37 fire |
| V1–V3 | Verify-at-live | CTR units at first pull; Lane A bridge shape; MPT field compat at G8 |

## Repair checkpoint S3 — native provider protocols (2026-09-17)

This repair continues the S0–S8 program; historical F-module completion claims
remain subject to the repair ledger. No paid call, store read, Drive upload or
publication was performed.

- Canvas uses installed public CLI 1.0.1 (83aeb67): stable project/node/update/
  submit IDs saved before calls, one canvas per video, reference imports,
  exact node draft checks, fresh quote bounded by recorded approval, native
  operation/resource identity, file-integrity verification and durable recovery.
  Unknown prices block. The CLI exposes no qualified cancellation operation.
- Vertex now sends native OAuth at the transport boundary, matches the saved
  successful typed-input/response_format/steps-content protocol, preserves
  ambiguous submissions, rejects malformed or missing outputs, and reserves
  estimates with at least 25% headroom. Usage remains distinct from settled
  billing. Unqualified models/reference input modes remain unavailable.
- Hypit parses pinned 0.1.8 nested build/status/get envelopes and binds every
  command to its workspace. A durable receipt and unique title prevent automatic
  rebuild after lost acknowledgement. Strict plan validation rejects malformed,
  incomplete, hosted or unresolved work. Local qualification exposed and fixed
  incorrect source-audio wiring and nonzero-exit terminal-status handling.
- Drive sends descriptive filenames, requests full names and exact sizes,
  detects incomplete listings, and reads the actual MD5 metadata field.
- Shopify price queries and pagination queries passed schema validation. Product
  variants/media retain complete pagination evidence, downloads have size and
  redirect checks, and non-USD prices are not labeled USD.
- Synchronous research/acquisition/TTS adapters keep receipts and audio/media on
  disk. The search adapter reuses the verified legacy API route. Analysis resolves
  and verifies registered source bytes before invoking its media transport.
  ElevenLabs v3 uses the verified with-timestamps route; speech retains character
  alignment for captions without a second transcription request.

Native local evidence: Hypit build `bld_20260917T161953725Z_F9D4B5CADA`
exported 30 frames at 30 fps, 360×640. Five local requests; zero hosted requests.
Its isolated runtime was stopped and verified absent. See
`docs/factory-reports/REPAIR-S3-EVIDENCE.json` and
`tests/factory_fixtures/protocols/README.md`. This qualifies the local contract,
not the four-variant application or live provider/account routes.


## Safe repair S4 — media timing and acceptance (2026-09-17)

Parent revision: `474f676`. Implemented duration/handle-aware shared work and
native allocation pricing hashes; collected media must cover its actual
allocation. A manual replacement no longer enters generation. Missing asset
reviews wait for an operator.

Speech fitting now renders and measures new PCM bytes, divides alignment times
by speed, retains raw synthesis separately and requires a fresh fitted hash for
approval. Mixing decodes/resamples input, applies frozen offsets/ducking and
measured RMS targets, accumulates without early clipping and encodes once at
exact duration. Short music sources cannot create non-advancing crossfade loops.

Composition emits source trims, exact target positions, stills, caption fonts,
audio gains and Hypit crossfades/zoom sampling. The fast renderer supports its
explicit subset, including stills and delayed audio; unsupported effects block.
Cache identity includes media bytes, timings, effects, audio and renderer
settings. Forced keyframes isolate encoded shot boundaries.

QC checks actual clocks, multiline/EOF freeze detection, decoder/detector errors
and audio coverage. Region checks compare every frame and actual audio; missing
hashes or short evidence block. Acceptance requires automated technical evidence
and an explicit creative review bound to the current plan, composition and
registered final. Application-level delivery ownership remains S5.

Evidence: `docs/factory-reports/REPAIR-S4-EVIDENCE.json`. Eleven negative probes
failed before their repairs. Local Hypit qualification produced 48 frames at
24 fps, verifying a nonzero source offset, six-frame crossfade into an image,
new caption text, and delayed audio with an initial silent interval. It made
zero hosted requests and stopped its isolated runtime. The first full offline
suite passed 902 tests; the collected-duration regression was added afterward
and the final checkpoint passed **903 tests** in 125.61 seconds (two existing dependency warnings).

This is an offline engineering checkpoint. It does not sign the four-variant
application journey, production qualification, or legacy G-gates.


## Safe repair S5 — real application checkpoint (2026-09-17)

Parent revision `fc7fb75`. The loopback API/dashboard now use the real domain
records and a separately managed durable worker. Imported source observations,
blueprints, templates, A/B/C/D plans, approvals, asset reviews, local rendering,
QC, final reviews, registered delivery and owned cleanup all pass through the
application. Local supervisors retain process identity and survive worker loss;
unfinished local renders keep their capacity slot. Imports and range responses
are bounded; API mutations commit their domain/job/response atomically. Browser
action keys survive uncertain replies without making later pause/resume no-ops.

The native/browser qualification found two defects invisible to earlier mocked
checks: float frame rates broke ASS timestamps, and a missing ASS style column
made captions have zero height. The regression now requires four distinct actual
exports, and identical treatment/control bytes fail QC. Hypit clock values now
use its rational syntax; Studio preserves the actual printed localhost address.

The short public HTTP journey produced four 900-frame files with isolated caption
changes and sequential narration-tone fixtures, explicit fixture reviews, four
verified fake Drive receipts, and verified cleanup. The browser played all four
plus the source at 30 seconds; a second tab and refresh retained selection. Native
Studio opened the real composition and its owned port was freed on close. No
paid service, real Drive destination, Shopify account or publication was called.

Full offline suite: 916 passed, two dependency warnings, 149.84s. Dashboard: 25
tests and production build passed. Frozen contracts and legacy ledger match the
baseline. The pre-existing LONGFORM_PLAN.md deletion remains untouched; the
already-dirty dashboard build cache was regenerated by the build and remains
unstaged. Evidence: docs/factory-reports/REPAIR-S5-EVIDENCE.json.

This is the first local production checkpoint. Research, publishing/learning,
generated-audio application wiring, the long fixture and the complete interruption
matrix remain required; no live qualification or legacy G-gate is signed here.

Studio reopen was then verified through the public API and real local launcher;
its session history uses separate revisions. Nine focused Studio tests pass,
including the regression added after full-suite collection.

## Safe repair S6 — scoped research and creator baselines (2026-09-17)

Parent revision `6628500`. Search candidates no longer become one another's
baseline. Creator histories are independently acquired and exclude the seed,
other creators/platforms/formats, duplicate posts, future publication or
observation dates and missing identities. Fewer than 20 valid preceding uploads
produce an unavailable baseline; follower multiples and provider scores remain
separate. Cache identities include provider/account, settings and page size.

The public research commands now create immutable adapter-priced plans, record
explicit native-unit budget scopes and authorizations, enqueue durable effect
jobs, settle reported charges, and evaluate completed receipts. Worker recovery
reuses original attempts, and missing funding blocks before submission. Generic
audio/analysis effect-plan support is introduced for S8 application wiring.

Evidence: 32 targeted tests; full offline suite **922 passed** in 152.75 seconds
(two existing dependency warnings). Frozen contracts and the legacy ledger are
unchanged. `REPAIR-S6-EVIDENCE.json` records scope and the official search protocol.
No external research call, generation or purchase occurred. Live research remains
unqualified; this checkpoint does not sign production or legacy G-gates.

## Safe repair S7 — publication, readback and learning (2026-09-17)

Parent revision `b23790b`. Native Upload Post requests now retain asynchronous
identity and distinguish per-platform public posts from upload completion. Exact
registered bytes, destination, metadata and action bind immutable publication
authority. The application requires accepted finals and verified delivery/cleanup.

YouTube reach uses Reporting job/report discovery and bounded CSV ingestion.
Metric-specific coverage, weighted denominators, Pacific source days and exact
horizon eligibility govern comparison; lifetime counters remain separate. Learning
requires exposure for every arm, the frozen horizon and current independent
experiments. Supersession preserves original decision records. Legacy missing
baselines and pending observations cannot generate promotion evidence.

Four original negative probes reproduced before repair. 81 focused tests passed;
full offline suite: **932 passed in 175.52s**, two dependency warnings. The public
application journey produced real local exports, collected fixture reviews and
fake delivery, then four exactly authorized fake posts, source reports and a
frozen-policy decision. No real posts, account calls, paid generation or live
analytics qualification occurred. Evidence: REPAIR-S7-EVIDENCE.json.

## 2026-09-17 — S8 repair qualification and correction of earlier completion claims

**Scope:** user-authorized sequential S0–S8 repair of R01–R43 on `feat/factory`.
Parent revision: `f282bce`. This entry belongs to the focused S8 checkpoint.
The exact tested source manifest, final suite result, stage timestamps and limits
are in `docs/factory-reports/REPAIR-S8-EVIDENCE.json`.

### What changed in final integration

- Qualified routing is checked in actual production quote and dispatch commands.
  Paused experiments stop new submissions while existing remote work is collected.
  Restarted generation reconciles the original attempt; synchronous responses
  preserve immediate completion, with publication states normalized separately.
- Schema 10 preserves populated v7 history while allowing distinct explicitly
  approved operations with identical request content. Logical intent and attempt
  identity still prevent duplicate effects.
- Application routes now cover quoted ElevenLabs v3 synthesis, real waveform
  fitting/alignment, explicit listening approval and revised composition binding;
  quoted seed-bound audiovisual analysis; selected read-only Shopify imports;
  Reporting job setup; terminal manual replacement and bounded local recovery.
- Offline startup constructs no native transports. Optional live routes require
  dated qualification references and explicit connection configuration. Drive
  additionally checks its native current account against the scoped approval.
  Zero-price actions retain auditable reservations/settlements; unknown actual
  charges retain holds and reported overruns block further dispatch.
- Fresh-root restore verifies registered bytes, quarantines original process IDs,
  and requires current financial reconciliation. Activation retires historical
  funding and approvals without rewriting their records.
- Dashboard collections, generation approval, draft revisions, budgets, research,
  analysis, audio, products, publishing, learning and recovery controls call real
  domain commands. Native Studio remains an isolated, owned composition workspace.

### Evidence and honest boundaries

- Real HTTP API + independent worker produced four **900-frame** outputs and four
  **5,091-frame** outputs at 30 fps, with distinct controlled caption treatments,
  sound, explicit fixture reviews, verified durable fake Drive delivery and owned
  cleanup. The smaller 180×320 test resolution bounds test cost; it is not a
  production-quality claim. Narration fixtures are deterministic tones, not proof
  of a natural voice; actual synthesis fitting is separately exercised.
- Real worker deaths cover pre-submission, accepted remote work, download, render
  and upload. Six independent workers exercise five Jimeng/one Vertex capacity
  across death and expired leases; local render ownership survives caller loss.
- Two-tab/refresh dashboard checks show the actual experiment, four finals and
  delivery/cleanup receipts. Lost-response/idempotency and named-SSE behavior have
  permanent regression tests. No claim is made that every browser network fault
  was induced manually.
- Populated migration/restore, retired funding, malformed requests, expired routes,
  secret-output protection, no-budget effects, publication/readback/learning,
  exact source bytes in analysis and current Drive account binding are covered.
- The final report records the full backend suite plus 28 frontend tests and the
  production build. Two existing dependency deprecation warnings remain; they do
  not indicate failed checks.

**Correction:** earlier F34/F-module “done/run” and broad completion statements
were not proof of this integrated system. Their historical content is preserved,
but every report now points to the repair evidence. Full F-module checklist/human
sign-off remains explicitly `in_progress`; F35 awaits scoped live qualification.
No real provider generation, paid research, Shopify import, Drive upload, post or
analytics account request was performed. Optional generated music and unqualified
reference modes remain unavailable. No live route or legacy G-gate is signed by
these offline results. The existing operational database, credentials, assets,
legacy ledger and unrelated working-tree changes were preserved.

## 2026-09-17 — Completed repair checkpoint: work and verification record

**Implementation checkpoint:** `c6ffad2` on `feat/factory`, starting from
`dae132a`. The sequential S0–S8 repair program has passed its offline checkpoint.
All 43 review findings have recorded dispositions and regression evidence; this
does not establish live production qualification or complete the outstanding
F-module manual acceptance checklists.

### Work completed

| Package | Commit | Changes recorded |
| --- | --- | --- |
| S0 — Baseline and containment | `6c0f33a` | Default offline execution, truthful blocked states, structured redaction and deterministic approval timing. |
| S1 — Durable data and restore | `006f274` | Consistent database location, immutable revisions, forward migrations and verified self-contained backups with fresh-root restore restrictions. |
| S2 — Effects and spending | `1e3a31a` | Scoped approvals, separate native-unit budgets, atomic reservations and attempts, durable recovery, capacity holds and duplicate prevention. |
| S3 — Provider contracts | `474f676` | Canvas, Vertex, Hypit, Drive, Shopify and audio protocol corrections; durable receipts and isolated local Hypit qualification. |
| S4 — Media and acceptance | `fc7fb75` | Timeline timing and coverage, speech fitting/alignment, audio mixing, captions, cache identity and artifact-bound technical/creative acceptance. |
| S5 — Application workflow | `6628500` | Application bootstrap and independent worker, connected dashboard/domain commands, four-variant local production, verified fake delivery and owned cleanup. |
| S6 — Research | `b23790b` | Creator-specific comparable baselines, separate follower/baseline scores and scoped research budgeting/recovery. |
| S7 — Publishing and learning | `f282bce` | Exact publication authority, asynchronous posting receipts, Reporting CSV ingestion, coverage-aware metrics and evidence-bound decisions. |
| S8 — Integrated qualification | `c6ffad2` | Final route/account safeguards, audio/analysis/product/recovery controls, restore reconciliation, interruption/concurrency/browser checks and corrected acceptance records. |

### Final verification at `c6ffad2`

- Backend: **952 passed** in **268.27 seconds**, with two existing dependency
  deprecation warnings. Frontend: **28 passed**; production build passed.
- Public API plus independent worker produced four **30-second / 900-frame**
  exports and four **169.7-second / 5,091-frame** exports at 30 fps. Fixture
  reviews, verified fake Drive receipts and owned cleanup completed. These use
  180×320 test patterns and deterministic audio, not production product footage
  or natural narration.
- Real process-interruption tests covered submission, acceptance, download,
  rendering and upload; restart preserved original operations. Concurrency
  checks covered five Jimeng slots, one Vertex slot and one local renderer.
- Browser refresh/two-tab checks and populated migration/restore checks passed.
  All **29 frozen contract/fixture files** and the legacy spending ledger remained
  unchanged. Test services stopped; ports **5197, 5198, 5189 and 5202** were free.
- No native live provider/account calls, paid generation or publication were
  performed. The operational database, credentials and generated assets were
  preserved, as were the existing `LONGFORM_PLAN.md` deletion and dashboard
  build-cache modification.

### Remaining qualification and evidence

Each selected live provider/model/input mode still needs a current scoped budget
and qualification run, followed by a complete four-variant live experiment with
verified Drive delivery and cleanup. Publication and elapsed analytics horizons
have separate gates. Generated music and unqualified reference modes remain
unavailable; automatic paid cross-provider replacement requires explicit replanning
and approval. F-module manual sign-off remains open; legacy G-gates are independent.

- [Per-finding implementation and regression evidence](docs/factory-reports/REPAIR-S8-FINDINGS.md)
- [Final test results and tested source manifest](docs/factory-reports/REPAIR-S8-EVIDENCE.json)
- [Repair package status](docs/factory-reports/REPAIRS.md)
- [Operator and recovery guide](docs/factory-operations.md)
- [Module acceptance tracker](docs/viral-video-factory-module-tracker.md)

This completion record was appended after the implementation checkpoint. It
records the existing verification results; no code or tests were changed or
rerun for this documentation update. The repair summary's stale S8 “verification
in progress” label was also corrected to match the completed evidence.

## 2026-09-19 — Automatic seed → A–D pipeline ("Auto" tab)

### What was built

- `modules/factory/autorun/` — durable orchestrator: an `autorun` record
  plus one self-deferring `auto_step` worker job drives intake → evidence →
  video_analysis → sections → analysis_review → blueprint → template →
  script → music → draft → tts → quote → authorize → run → footage →
  compose → final_qc → done. Waits defer through the scheduler (survives
  worker restarts, no busy loop); failures pause with code/detail/action.
- `autorun/scripts.py` — deterministic adaptation: A close control, B hook,
  C body, D ending; each declares changed factor, hypothesis, primary
  metric and changed region. Optional qualified `adapt_script` LLM route;
  failure pauses (`script_llm_failed`) and resume falls back to
  deterministic scripts instead of re-dispatching a dead job.
- `autorun/review.py` — automated asset/final inspection (streams, duration,
  resolution, black/frozen frames) written as `reviewer_type="automated"`
  Review records bound to artifact id+sha and plan hash; the production
  selector resolves awaiting_review nodes from these records.
- Vertex adapter gained `adapt_script` and `review_final` tasks;
  `generated_music` added to the Authorization provider whitelist;
  `QualityService.record_verdict` accepts `reviewer_type`.
- Finals stamped with `plan_id`/`experiment_revision`; `experiment_results`
  exposes only current-plan finals — older renders can never be relabelled
  as a new revision.
- Budget semantics fixed: authority caps cover unit totals; exhausted
  budgets pause as `budget_exhausted`; resume accepts `budget_ids`
  (replace) / `add_budget_ids` (add), validated and audited.
- Dashboard: Auto tab (seed link + media attach, voice, budget checks,
  per-operation limits, music/visual-QC toggles, stage bar, pause card
  with resume-including-budgets); Compare shows pending states and
  per-variant hypotheses, changed sections and QC checks.
- API: `POST /api/autoruns`, `GET /api/autoruns/{id}`,
  `POST /api/autoruns/{id}/resume`; `autoruns` collection.

### Verification

- `tests/test_factory_autorun.py`: 8 passed (offline, fully mocked) —
  seed→4 renders, rollback, revision scoping, receipt backup/restore,
  caller-process loss, malformed command rejection, render capacity after
  expired worker, OAuth redaction, fractional frame-rate caption clocks.
- Full backend suite: 1075 passed; the pre-existing
  `test_full_publish_learn_next_round_journey` failure at HEAD
  (expected `provisional_winner`, got `no_improvement`) deselected —
  unrelated, reproduced on a clean stash.
- Dashboard: 30 tests + production build green.
- Live smoke: `POST /api/autoruns` over the real API created a durable run;
  the worker advanced it to an honest `missing_source_media` pause with a
  resume action — zero paid calls.

### Honest boundaries

- Real paid end-to-end (live Vertex/Jimeng/TTS) not yet run — needs an
  authorized budget covering the exact run plus Drive-delivery completion.
- No paid fallback was inferred; every pause is explicit.

## 2026-09-19 — Autorun hardening: holds UI, self-repair, honest pauses

Follow-up fixes after the first real end-to-end run (`auto-5d3717e`,
which succeeded but needed 16 manual resumes).

### Spending authority

- `GET /api/reservations` lists open holds; `POST
  /api/reservations/{id}/settle|release` let an operator close a hold
  with evidence — settle at the actual charge (`invoice_confirmed`,
  `usage_estimate`), release only when the attempt verifiably never
  charged (failed/cancelled/prepared or no attempt). Both audited with
  reviewer identity.
- Budgets tab gained an **Open holds** table driving those routes.
- Resume copy and the autorun coverage check now state the real rule:
  an aggregate ceiling is held in full on every applicable operation —
  adding a second aggregate budget does not add headroom.

### Click-once reliability

- Script adaptation now word-budgets LLM copy against each beat's
  seconds; over-budget lines fall back to source-derived copy with a
  note instead of failing the measured fit downstream.
- Measured speech-fit failures trigger a bounded repair (swap that one
  segment to source-derived copy on a new draft revision); one repair
  per segment, honest pause after that.
- TTS results are reused across revisions by normalized text — editing
  one beat no longer re-buys every other line.
- Local compose timeouts (`TimeoutExpired`/`RenderTimeout` on `cmp`
  jobs) are bounded scheduler retries, not pauses; `raise_worker_errors`
  no longer re-raises handled retries.

### Observability and ops

- Pause history persists: every pause keeps code + detail + action in
  `run.progress`, shown under **Pause history** after resume.
- `done` now carries an explicit note that it is not verified Drive
  delivery; disabled visual QC is noted too.
- Worker rides through `database is locked` contention with bounded
  backoff; `factory-up.sh` verifies the worker is still alive after
  launch and prints the log tail if it died.
- `GET /api/assets/{id}/media` returns 404 `unknown_artifact` instead
  of a 500.
- `tsconfig.tsbuildinfo` untracked (generated build cache).
- Fixed two date-anchored tests: `test_q07_observe_job_defers_then_completes`
  (pinned the scheduler clock) and
  `test_full_publish_learn_next_round_journey` (the deliberate youtube
  collect must observe after the readback clock's OBS_AT or ranking
  prefers the stale auto-collected snapshot).

### Verification

- Full backend suite: 1085 passed, 0 failed (previously-failing
  time-bomb tests included).
- Dashboard: 30 tests + production build green.

## 2026-09-19 — Production DB cleanup after first live run

Operator-level maintenance on `data/factory/factory.db` following the
`auto-5d3717e` run; no code changes.

### Holds settled

- All **40 open reservations settled** at their reserved amounts with
  `kind=usage_estimate` via the new operator settle path — every linked
  attempt was `downloaded`/`succeeded`, so the paid work verifiably ran.
  Audited as `reservation_settled_by_operator` events.
- **Overspend exposed:** `syp34-vertex-approved-4590780` is over its
  18.37M µUSD cap by ~2.54M — repeated authorization rounds each held
  against the aggregate ceiling and settled usage exceeded it. The
  negative `available` is intentional honest accounting; do not
  authorize further work under that budget.
- Remaining headroom: `syp34-vertex-approved-6886170` ~522K µUSD,
  `lezys-tts-approved-2000` 325 credits.

### Aborted delivery and smoke residue

- The 4 `awaiting_review` delivery jobs for the autorun experiment's
  plan (`plan-a8d8a661`) cancelled — operator aborted Drive delivery —
  recorded via a `delivery_aborted` event. Twenty pending delivery jobs
  on other experiments (`exp-dog-ball-*`, `exp-ev-ranking-01`,
  `exp-syp34-*`) were left untouched.
- Smoke-test residue removed: autorun `auto-d91f3120c63a4f62`, its
  autostep command record and job, and seed `seed-youtube-5f6b0b4e201f2a7e`.
  The append-only event ledger was retained.

### Shutdown

- Full stack stopped: API (:8100), worker, hypit runtime worker, and
  the whisperx.local program (:8765). `media.local`/`hyperframes.local`
  keep stale "ready" records in the runtime DB but hold no ports —
  reconciled on the next `runtime up`. Logs truncated.
- Docs note added: `factory-down.sh` stops the API and worker only;
  hypit programs need `./scripts/hypit.sh programs down`.


## 2026-09-19 — Last-run investigation patches (commit b2118b4)

Code changes from `docs/factory-reports/INVESTIGATION-auto-cd98a5cf5308471b.md`
(seed `V3OAMVA8ULo`, run `auto-cd98a5cf5308471b`). All ten defect areas
patched; 31 files, ~2.5k LOC delta including the new regression file.
The historical run's artifacts are unchanged — corrected output needs a
separately approved rerun.

### False completion closed

- `final_qc` gates on `final_problems()` — every mandatory
  technical/changed-region check must pass against the *current* bytes,
  composition, plan and experiment revision before any finish path.
  Missing, stale, failed or unbound check records block.
- Stale-only problems (superseded plan, foreign bytes) trigger a bounded
  rewind (`final_qc_rewinds` < 3) that re-arms the plan's compose nodes
  so the run re-renders its own checked output instead of looping on a
  tampered meta record. Unresolvable problems pause `final_qc_blocked`.
- `run.detail()` exposes per-variant `finals_state`
  (missing / rendered / validation_blocked / ready_for_review /
  validated / delivered / done) and `experiment_results` carries
  `validation.state` + `problems` per variant; Compare renders both.
- Disabled visual review notes "technical checks only" and still passes
  the mandatory gate; flagged-final acceptance binds artifact+sha256
  and a replaced final discards the old verdict.

### Evidence validation before spend

- `validate_temporal()` (analysis/analyzer) rejects non-finite bounds,
  ordering violations, overlaps, material gaps, sub-100 ms beats and
  coverage < 50 % of verified media duration — the incident's 0.4 s
  analysis for a 37.6 s source can no longer reach the blueprint.
  Wired into analysis service (provider + manual), `build_sections`,
  `vertex.analyze_media` and autorun `video_analysis` (`analysis_invalid`
  pause; settled holds clear the stale references on Resume).
- Transcript stage resolves the *source* language (seed metadata → CJK
  heuristic → configured default) — never the requested TTS language —
  and `transcript_problems()` rejects empty/looped/mistimed/mismatched
  output before script or TTS can consume it. Transcript reuse is
  settings-bound: changed source bytes or resolved language invalidate it.
- `assign_passages` gives each transcript passage exactly one beat;
  unplaced passages are reported, not silently dropped.
- `validate_variations` enforces one declared changed beat per B/C/D
  with copy that differs from A under case/punctuation-insensitive
  normalization; word-budget trimming preserves a bounded variation
  instead of reverting to control copy, and repair pauses
  `variation_lost` rather than shipping identical variants.

### Paid-work reliability

- TTS plans chunk at 20 ops (`tts`, `tts_1`, …); synthesis reuses only on
  exact identity match (text, voice, model, language, settings); speech
  repair patches only the failing line on a new revision and pauses
  `speech_fit_failed` when even source-derived copy cannot fit.
- `_rebind_current_revision` covers every post-draft stage and refuses
  to replace paid references while attempts are non-terminal or holds
  unreleased; resume clears stale refs only after terminal jobs +
  released/settled reservations.
- `_cover` names the blocking budget with cap / committed / available /
  needed per unit instead of a bare `budget_exhausted`.
- `attach_media(role='analysis')` records a proxy that never satisfies
  media readiness and is dropped on re-mastering; `output_profile`
  freezes at draft creation and every variant renders to it; upscaled
  inputs are recorded as limitations.
- Frame-clock: missing stream duration falls back to `nb_frames`/fps;
  one-frame tail tolerated, larger shortages fail.
- Vertex failures distinguish invalid JSON / missing fields / blocked /
  incomplete finish with bounded (300-char) redacted detail in the
  attempt event; post-dispatch `ContractError` records the real cause as
  `ack_lost`; 4xx and credential-boundary rejections classify
  `pre_acceptance` and release their hold.
- Worker takes a per-database `flock` on `worker.lock` (pid, worker_id,
  db, version written into the file); a second worker on the same DB
  exits 2 with a clean refusal — different DBs lock independently.
  Heartbeat meta carries pid/db/version.
- Credential boundary hardened: the Google identity oracle reads the
  `id_token` email claim → ADC file identity → fail closed. The
  `config_default` fallback that falsely attested `david.dai` while the
  ADC token belonged to another principal is removed.

### Verification

- `tests/test_factory_incident_fixes.py`: 21 new offline regressions.
- `tests/test_factory_autorun.py`: 26 pass, including the rewritten
  stale-final swap test (foreign bytes can never earn verdicts; the
  rewind restores the pipeline's own checked output).
- Full suite: **1107 passed**, 0 failed, all offline (fakes + local
  ffmpeg). Dashboard `tsc --noEmit` clean.
