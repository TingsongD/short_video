# Repair plan — post-repair review findings (N01–N20)

Base: `c6ffad2` (952 backend / 28 frontend tests green; 19 defect probes
reproduce all findings). Goal: land every fix as small, individually
revertible commits that preserve offline/no-spend guarantees.

## Global safety properties

- **Zero DB migrations.** All repairs work through additive record-body
  fields, adapter `DurableState` files, or hash-material versioning.
  `records`/`attempts`/`jobs` schemas are untouched.
- **Probe inversion discipline.** Each probe in
  `probes/review_post_repair_2026_09_17.py` asserts bad behaviour. After
  its fix lands, the probe is rewritten with inverted assertions and
  moved into `tests/` as a permanent regression test. The original file
  is preserved until every finding is patched (audit trail); the
  mapping probe → test is recorded in `REPAIRS.md`.
- **No automatic retry of ambiguous external effects.** Reconciled
  `unknown` attempts stay `unknown` until a remote op is found or an
  operator resolves them with evidence.
- **Fail-closed classification.** Any result/status the system does not
  explicitly understand becomes a failure, never a silent success.
- **One commit per fix** (a few tightly-coupled fixes share a commit).
  Revert granularity = single fix.

## Waves

Order is dependency-driven, not severity-driven:

| Wave | Issues | Why first/last |
|---|---|---|
| W0 | N02 (outcome mapping) | Everything else sits on truthful job outcomes |
| W1 | N04, N05, N06, N11, N12, N13 | Provider identity + request contracts; surgical, self-contained |
| W2 | N03, N09, N10 | Recovery completion; depends on W0+W1 semantics |
| W3 | N01, N07, N08, N16, N17, N19 | Acceptance & provenance; N08 needs N07, N17 needs N16 |
| W4 | N14, N15, N18, N20 | Media fidelity & surface; N15 is the largest change |
| W5 | Consolidation: probes moved, docs, pytest guard, final suite |

---

## W0 — N02: exhaustive result-state mapping in `worker.tick`

**Files:** `modules/factory/services/worker.py` (tick, ~L31-40)

Current: any status outside `{awaiting_review, running, observer_lost,
pending, unknown}` → `commands.finish` + `scheduler.complete`.

Fix:

1. Inventory every status literal returned by handlers/services
   (`grep -n "'status'" modules/factory/services/ modules/factory/delivery/
   modules/factory/publishing/`) and partition into:
   - `SUCCEEDED = {...}` — verified completions (`succeeded`, `rendered`,
     `verified`, `complete`, `completed`, `reconciled`, `imported`,
     `reused`, `released`, `queued`, `planned`, `done`, …).
   - `FAILED = {failed, conflict, unverified, cancelled, error}`.
2. Replace the else-branch:

   ```python
   elif outcome in FAILED or outcome not in SUCCEEDED:
       self.scheduler.fail(job['id'], outcome or 'unrecognized_result_state')
       self._release_local_marker(job)   # delete meta 'local_work:'+id
   else:
       self.s.commands.finish(job['id'], result)
       self.scheduler.complete(job['id'], job['fencing_token'])
   ```

3. `_release_local_marker`: `DELETE FROM meta WHERE key='local_work:'||?`
   — compose markers are node-scoped; deleting on any terminal outcome
   is safe and unblocks the slot.

Semantics: `failed`/`conflict`/`unverified` are terminal for the job
(non-retryable `fail` — a deterministic failure shouldn't burn retries;
transient transport issues raise `ProviderError` and classify through
the executor's own path, not this branch). Unrecognised statuses →
`unrecognized_result_state` failure. `commands.finish` is called only
for whitelisted successes.

Tests (inverted probes): failed render → job `failed`, marker gone;
`unverified` delivery → `failed`; unknown handler status →
`unrecognized_result_state`; no `local_work` residue.

---

## W1 — provider identity & request contracts

### N04 — atomic Canvas quote
**Files:** `providers/canvas.py` (`prepare_quote`, L214-220)

`DurableState.locked()` is reentrant (depth-guarded + `RLock`) and
reloads the file on acquire. Add `@receipt_locked` to `prepare_quote` —
the whole read/modify/write becomes one critical section; the nested
`prepare()`/`_save()` calls yield through the depth guard. Quoting
serializes across processes; it already does for submit/observe.

Test: concurrent receipt writer inside the quote window → receipt
survives (probe inversion, plus a two-process variant).

### N05 — attempt-keyed Canvas operations
**Files:** `providers/canvas.py` (`submit`, L222-267)

Today `ops` is keyed by `prep["submit_id"]` which lives inside the
request-hash-keyed `preps` — so identical requests share one remote op
across distinct attempts. Fix the identity layers:

```python
binding = current_effect.get()
key = binding["attempt_id"] if binding and binding.get("attempt_id") else prep["submit_id"]
previous = self.state["ops"].get(key)
if previous: return self.observe(key)
...
op = {"operation_id": key, "submit_id": key, ...}
self.cli.submit(op["project_id"], op["node_id"], key, price.amount)
```

- `submit_id` (the remote idempotency token) becomes the allocation
  identity: same attempt → same token → idempotent remote reuse;
  new attempt → new token → new remote op.
- `preps` stays request-keyed — draft/dedupe sharing is F21's intended
  plan-level behaviour and costs nothing.
- Executor always binds `attempt_id` (executor.py:124); unbound direct
  submits (unit tests) fall back to `prep["submit_id"]` — old
  single-shot behaviour preserved.
- Old `ops` receipts keyed by legacy submit ids still resolve via
  `observe(operation_id)` — untouched.

Test: identical request × two `attempt_id`s → two remote ops/clips;
retry same attempt → same op; equal-duration sibling shots → no
sharing (probe inversion).

### N06 — Vertex attempt-scoped reconcile
**Files:** `providers/vertex.py` (`reconcile` L292-305, `submit` L201-233)

`submissions` is already keyed by `binding["attempt_id"]`; `reconcile`
just never consults it. Fix:

```python
binding = current_effect.get()
if binding and binding.get("attempt_id"):
    prior = self.state["submissions"].get(binding["attempt_id"])
    if prior is not None:
        if prior.get("operation_id"):
            return self.observe(prior["operation_id"])
        return None   # intent recorded, no remote id → stays unknown
```

Executor already wraps `reconcile` in
`dispatch_context({'attempt_id': attempt_id})` (executor.py:257), so no
executor change is needed. Also store a bare `wire_hash` on each op at
submit (`sha256(json.dumps(request…))`, same as `effects.wire_hash`) so
the `request_hash` fallback matches both hash forms:

```python
op["wire_hash"] = hashlib.sha256(json.dumps(request…).encode()).hexdigest()
# reconcile: if request_hash in (op["request_hash"], op.get("wire_hash"))
```

Test: submit → adapter restart → `executor.reconcile` finds the op; no
second submission (probe inversion).

### N11 — content-bound render inputs
**Files:** `rendering/service.py` (`bound_media`, L50-54)

`bound_media` already hashes file *bytes* — but the hashed material
still includes `src`. Strip transport fields from hash material:

```python
def bound_media(items):
    return [{**{k:v for k,v in item.items() if k not in ('src','path','workspace','hypit_workspace')},
             'sha256': hashlib.sha256(Path(item['src']).read_bytes()).hexdigest()}
            for item in items]
```

Bump `version` to `"render.v4"`. Compat: pre-fix builds recorded
v3-material hashes and will still mismatch on resume — they were
already unresumable; no regression. New builds restore across roots.

Test: fresh-root identical bytes → dispatch proceeds; changed bytes →
`render_input_revision_mismatch` (probe inversion).

### N12 — normalized Vertex settings
**Files:** `providers/vertex.py` (`_payload` L132-149); mirror in
`providers/canvas.py` for consistency

Add a shared normalizer (e.g. `providers/base.py`):

```python
def normalized_setting(request, name, default):
    top, nested = request.get(name), (request.get("settings") or {}).get(name)
    if top and nested and top != nested:
        raise ProviderError("conflicting_settings")
    return top or nested or default
```

`_payload` uses `normalized_setting(request,'aspect','9:16')` and
`('resolution','720p')`. Conflicting duplicate declarations are
rejected, never silently picked. Router output unchanged.

Test: nested settings → correct aspect/resolution on the wire;
conflict → `conflicting_settings` (probe inversion).

### N13 — typed reference contract in Canvas
**Files:** `providers/canvas.py` (`_references` L105-145)

Accept three shapes, rejecting everything else with a typed error:

```python
for ref in refs:
    if isinstance(ref, dict):
        ref = ref.get("artifact_id") or (_ for _ in ()).throw(
            ProviderError("malformed_reference"))
    if not isinstance(ref, str):
        raise ProviderError("malformed_reference")
    if ref.startswith("node:") or ref.startswith("resource:"): ...
```

Router's `{kind, artifact_id}` dicts resolve through the existing
artifact→import flow; `node:`/`resource:` strings pass through; bare
artifact ids keep working. `ProviderError`, not `AttributeError`.

Test: router-shaped refs → `node:` bindings; malformed →
`malformed_reference` (probe inversion).

---

## W2 — recovery & retry completion

### N03 — reconcile resumes the job graph
**Files:** `services/worker.py` (`execute('reconcile')` L48-54),
`services/recovery.py`

1. Extract `retry_local`'s descendant-unblock loop into a shared helper
   `unblock_descendants(db, root_id)` in `recovery.py`; `retry_local`
   uses it too.
2. In the `reconcile` command handler, after `executor.recover()`:
   for each job with reconciled attempts, resume iff
   `∃ attempt ∈ {accepted, running, succeeded, downloaded}` **and**
   `no attempt ∈ {failed, cancelled}`:
   `UPDATE jobs SET status='waiting_dependencies'` (phase preserved),
   then `unblock_descendants`. Resumed jobs re-enter their claim queue
   and the workitem's own poll/download path finishes the graph —
   **no new submit, no new reservation** (attempts/reservations are
   untouched).
3. All-`unknown` jobs stay `failed` — operator `resolve_unknown` with
   evidence is the only path (conservative, per spec).

Test (probe inversion): lost submit ack → remote op exists →
`reconcile` command → original job resumes → download collects →
children unblock → remote interaction count unchanged → no duplicate
reservation.

### N09 — working delivery retry path
**Files:** `services/app.py` (`deliver_variant` L287-323),
`delivery/service.py` (`deliver` L55-58), `services/worker.py` (handlers)

Three small pieces:

1. `DeliveryService.deliver` existing-branch: after `reconcile` returns
   `pending` and `existing.get('attempt_id')` is falsy → delegate:
   `return self.retry(delivery_id, final_path, now)` — service-level
   re-entry retries the transfer.
2. `deliver_variant`: when `existing` is not `verified` and a prior
   appcommand exists, enqueue `kind='delivery_retry'` with identity
   `f'{did}:retry:{existing.get("attempt_count") or 1}'` instead of
   returning bare `accepted`. `conflict`/`unknown` deliveries are NOT
   retried — return their status for operator resolution.
3. `worker.execute('delivery_retry')` → recompute
   `final_path = artifacts.verified_path(command['artifact_id'])`,
   verify sha/binding, call `delivery.retry`. `retry()` also bumps a
   `retry_count`/`attempt_count` on the delivery record so each
   subsequent retry mints a distinct command identity.

Test (probe inversion): listing-failure → `deliver_variant` re-entry →
retry command uploads once → `verified`; same-name remote conflict →
status surfaced, no retry; identical dedupe → no duplicate upload.

### N10 — explicit local-attempt identity
**Files:** `resources/runner.py`, `services/recovery.py` (`retry_local`
L30), `services/worker.py` (`render` L203)

1. `OwnedRunner.__init__(db, root, owner, attempt=0)` — identity hash
   becomes `sha256(argv+cwd+owner+attempt)`. Old receipts untouched.
2. Before executing a new attempt, scan prior same-argv receipts: a
   `running` receipt whose recorded pid is still alive
   (`os.kill(pid,0)` — POSIX; `fcntl` is already used) →
   `ContractError('local_process_unresolved')`. Dead/done receipts
   never block.
3. `worker.render` passes `attempt=job['retry_count']` (thread `job`
   into `render`).
4. `retry_local` adds `retry_count=retry_count+1` to its UPDATE —
   every authorised retry mints a new attempt. (Scheduler's automatic
   retry path already bumps `retry_count` at scheduler.py:358-362, so
   auto-retries get fresh identities too; the stale `timed_out`/`done`
   receipts are preserved as evidence.)

Test (probe inversion): cached `done`/rc=1 receipt → authorised retry
executes again under a new receipt; live-pid receipt →
`local_process_unresolved`.

---

## W3 — acceptance & provenance

### N01 — publish only with live acceptance
**Files:** `services/publication_work.py` (`plan` L30-44, `execute` L53-66)

- `plan()`: persist `check_ids` + `binding` into the publicationintent
  body (additive fields via `_set` after `publishing.plan`).
- `execute()`: before `s.publishing.publish`, re-validate
  `s.quality.accept(path, intent['check_ids'], intent['binding'])` —
  `accept()` already fails when a newer non-pass review exists
  (`acceptance_blocked`), so withdrawal after queueing blocks the
  external effect. Fallback for pre-fix intents: read
  `meta['final:'+variant_id]` which already stores
  `check_ids`/`binding` (worker.py:297-299).

Test (probe inversion): withdraw approval post-queue → execute raises
`acceptance_withdrawn`, no remote post, evidence preserved.

### N07 — canonical speech/copy identity
**Files:** `services/audio_work.py` (`queue_fit` L32, `attach` L68-75)

- `queue_fit`: compare normalized forms —
  `speech.normalize(req['text']) != speech.normalize(seg['copy'])` →
  mismatch. Accepts raw or pre-normalized request text.
- `attach`: match on
  `normalize(seg['copy']) == normalize(speech['source_text'])`; count
  attached sids; `if sid not in attached: raise ContractError(
  'speech_unattached','speech_id',sid)` — a no-match attach is a loud
  failure, never a silent 200.
- Stamp provenance (feeds N08):
  `seg['speech'].update(normalized_copy=normalize(speech['source_text']),
   source_text=speech['source_text'])`.

Test (probe inversion): contraction copy → fit+attach succeed;
no-match attach → `speech_unattached`.

### N08 — stale derived-media detection
**Files:** `experiments/diff.py` (`check_treatment`), `worker.py`
(`render` ~L252)

Two enforcement layers:

1. `check_treatment` — for each segment pair:
   - `c.copy != v.copy` and `c.speech == v.speech` → flag
     `stale_derived_media:speech`.
   - `v.speech.normalized_copy` present and `!= normalize(v.copy)` →
     flag `stale_speech` (catches staleness even when copy is
     "unchanged" between declared diffs).
   - `picture` items flagged only when marked `lip_sync`/`derived_from:
     'speech'` — independent footage may stay identical; stale mouth
     motion may not.
2. `worker.render` hard stop: `seg.speech.normalized_copy` present and
   `!= normalize(seg.copy)` → `ContractError('stale_speech')` — the
   render boundary is the last line of defence regardless of how the
   plan got there.

Test (probe inversion): declared deps + unchanged speech → problems +
render block; regenerated speech → clean.

### N16 — pinned product snapshots
**Files:** `services/app.py` (`authorize_experiment` ~L218)

`packaging['products']` entries already carry `{snapshot_id, revision}`
— resolve the *pinned* row instead of `detail()`'s latest:
`records.get('productsnapshot', pid)` filtered to `revision ==
pin['revision']` (via `records.revisions()` or SQL on the records
table). Missing pinned revision →
`ContractError('pinned_revision_missing')` — never silently upgrade.

Test (probe inversion): Shopify refresh to rev1 → authorize still
validates 'Cotton' (rev0); absent rev0 → blocks.

### N17 — claims on every variant
**Files:** `experiments/service.py` (`acceptance_report` L189-195)

Iterate claims across **all** variant plans' segments, not just
control packaging:

```python
segs = list(control.packaging['segments']) + [
    s for vp in self._variants_of(experiment_id, revision)
    for s in vp['segments']]
for seg in segs: for claim in seg.get('claims') or []: …
```

`claim_texts` comes from the pinned snapshots once N16 lands —
dependency order matters.

Test (probe inversion): unsupported claim in B → `unsupported_claim`
problem; supported variant claim → clean.

### N19 — revision-scoped learning
**Files:** `learning/service.py` (`freeze_policy` L68-77,
`_publication_for` L399-401)

- `freeze_policy`: block only on publications with
  `body['experiment_revision'] == revision` — older revisions' posts
  belong to older decision chains and mustn't gate a new revision's
  policy.
- `_publication_for(vp)` takes the variant body; filter
  `pub['variant_plan_id']==vp['id'] AND
  pub['experiment_revision']==vp['experiment_revision']`; >1 match →
  `None` → honest 'missing' coverage (existing
  `missing_or_duplicate_post` logic still applies).

Test (probe inversion): rev1 publication + rev2 `freeze_policy` →
frozen; two public posts in one revision → coverage flags the
ambiguity.

---

## W4 — media fidelity & surface

### N14 — declared intentional stills
**Files:** `services/worker.py` (`render` L284), `App.tsx` (L50)

- `expected['intentional_stills']` built from picture items whose
  artifact `kind` is image:
  `{'start_s': in_frame/fps, 'end_s': out_frame/fps,
    'approved': <passing asset review for artifact+plan_hash>}`.
  Reuse the `asset_verdict` review lookup — extract it into a shared
  `_asset_reviewed(artifact_id, plan_hash)` helper. `TechnicalQC`
  already exempts only `approved` still regions — undeclared stills
  stay flagged.
- Dashboard: `videoAssets` filter becomes
  `kind in ('video','image','static_image')` so imported images are
  reviewable.

Test (probe inversion): declared+approved still → no `frozen_section`;
undeclared → still flagged.

### N15 — route production audio through `MixService`
**Files:** `bootstrap.py`, `services/worker.py` (`render` L243-262)

Biggest single change — one contained commit:

1. `bootstrap`: `s.mix = MixService(db, artifacts)`.
2. `render`: freeze a deterministic profile
   `mix-{experiment_id}-r{revision}` once (idempotent; cfg: duck
   enabled with regions = narration frame intervals @ fps,
   `loudness_target={'rms_dbfs': -14, 'tolerance_db': .5}`,
   `clip_policy='prevent'`). Build tracks: narration →
   `kind:'speech', artifact_id, offset_s=start_frame/fps,
   gain_db=20*log10(gain)`; music → `kind:'music', offset 0,
   gain_db, trim_to_allocation=True`.
3. `s.mix.mix(profile_id, tracks, out_s=target_frames/fps,
   artifact_name=variant.id)` → mixed WAV artifact →
   `audio=[{'id':'mix','src':path,'gain':1,'in_frame':0,
   'out_frame':target_frames}]` to `dispatch` — FFmpeg receives the
   pre-mixed track; raw per-item `amix` gains disappear.
4. Evidence: `final['mix'] = {profile_id, profile_hash, measured}` in
   the `meta['final:…']` record; `region_parameters` supports the
   unchanged-region equivalence evidence.
5. Silent compositions (no narration/music) skip the mix — `has_audio`
   stays false.

Test: mixed artifact exists; `measured.rms_dbfs` ≈ target; unchanged
regions resolve identical parameters across variants; render e2e green.

### N18 — research cache + truthful coverage
**Files:** `services/effect_work.py` (`execute` L79-101),
`services/app.py` (`research_evaluate`), `discovery/service.py`
(cache schema reuse)

- Cache before spend: in `execute`, for `kind=='research'`, look up
  `discovery_cache` by `wire_hash(request)` (+account) **before**
  `effect.prepare` — a hit returns
  `{'status':'succeeded','result':cached_posts,'cache_hit':True,'calls':0}`
  with no attempt, no reservation.
- Populate: after a successful remote research call, write the
  `discovery_cache` row using `DiscoveryService`'s existing
  key/column shape so both paths share one cache.
- Coverage: operation results record `{'calls':0|1,'cache_hit':bool,
  'posts':n,'page':p}`; `research_evaluate` builds `_finish` coverage
  from durable records — `actual_calls` = attempts with `remote_id`
  for this run's jobs, `planned_pages`/`received_pages` from operations
  and results, `queries` = request summaries. Zero-call claims become
  impossible.

Test (probe inversion): two identical plans → second is all cache
hits, `receipts==2`, `actual_calls==2`, `discovery_cache` populated.

### N20 — readiness TTL cache + split refresh
**Files:** `services/app.py` (`providers_readiness` L51-66),
`api/app.py` (L70-72), `App.tsx` (`refresh` L31-37)

- `providers_readiness(force=False, ttl_s=60)`: per-process in-memory
  `{at, data}` cache; fresh → return immediately. `GET
  /api/providers?refresh=1` forces a live re-check.
- Dashboard: remove `api.providers()` from the event-driven
  `refresh()`; fetch on mount + a manual "Re-check" action on the
  providers screen.

Test: 5s-stubbed `readiness()` → `GET` answers instantly after warm;
`refresh=1` invokes exactly once per TTL window.

---

## Verification per wave

```
PYTHONPATH=.:tests .venv/bin/python -m pytest -q <inverted-probe>   # red→green
PYTHONPATH=.:tests .venv/bin/python -m pytest -q tests/             # full suite
cd apps/factory-dashboard && npm test && npx tsc --noEmit           # when UI touched
```

Plus: the hard-blocked-urllib no-network audit (J-drill) after every
wave touching adapters; `make qa` cases re-run where behaviour changed.

## Rollback

- One commit per fix → `git revert <sha>` restores prior behaviour per
  issue. W0 (N02) is the exception: reverting it restores the
  fail-open catch-all — flag it as unsafe-to-revert; forward-fix only.
- Adapter state files gain additive keys (`submissions`, `wire_hash`,
  attempt-keyed `ops`) — old keys are ignored by old code, so
  per-commit rollback leaves no corrupt state.
- `render.v4` hash material: a revert re-breaks only builds created
  under v4; pre-existing (already-broken) v3 builds unaffected.

## Out of scope (unchanged qualification gaps)

Live route qualification, rolling-horizon analytics policy, guided
planner UI, operator settlement tooling, optional routes, and F35 —
tracked separately in the review report. The minor `pytest` foot-gun
(`vendor/` collection) gets a `testpaths`/`norecursedirs` guard in W5.
