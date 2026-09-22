# Flash-cut implementation record

Status (2026-09-22): the narrowly authorized `AVvVLM5b-mE` acceptance run is
complete, but the profile is **not globally live-qualified**. The run encoded
all 423 source frames with PE, completed audio analysis, used Jev in shadow
mode, and produced four current 720×1280 A/B/C/D finals. All four passed the
authoritative final QC, loaded in Compare and were verified in the run's Drive
destination. Publishing and scheduling remained disabled.

The run encountered response-token exhaustion, overlapping-window validation,
malformed grounding, a schema-related HTTP 400, an unknown-outcome HTTP 500,
an unusable narration repair, an incomplete editorial plan, a Hypit trim bug
and a false subtitle-QC expectation. The completed run used bounded recovery
plus some assistant-authored corrections. Unknown request identities and holds
were preserved rather than replayed or erased. Follow-on offline hardening now
adds a per-new-run $50 guardrail, second-attempt narration repair, conservative
editorial fallback and automatic planning for safe completed-response recovery.
Those changes are not deployed or broadly live-qualified. See
`FLASHCUT-CURRENT-STATUS.md` for the completed outcome and
`FUTURE-RUN-HARDENING-2026-09-22.md` for current verification and rollout state.
The older $3.26/seed89iXP setup below is superseded historical context.

Credential follow-up (2026-09-21): the connector accepts `JEV_API_KEY` as an
alias for `TYPESAFE_API_KEY`; an existing nonempty Typesafe key retains
precedence when both are configured. A reproducing offline regression failed
before the fix, then the Jev, route qualification, operations and credential
tests passed (**39 passed**). Local readiness detects the supplied key without
exposing it or contacting the provider. Secret files and running services were
not changed. This is not authentication, spending approval or live qualification.

Scope: the approved Hypit-first audiovisual flash-cut implementation plan, including native semantic authoring. One sequential writer; offline development only until a fresh acceptance quote is approved. Acceptance seed: `89iXPZsKn9M`, one new A/B/C/D run.

## Baseline

- Existing working tree contains substantial prior changes; retained in place.
- Consistent owner-only database snapshot and protected-file fingerprints: `/private/tmp/factory-flashcut-baseline.HQnKuI/snapshot`.
- Snapshot reports zero active jobs and 16 final files, all matching their recorded hashes.
- Initial sandboxed baseline stopped after 292 passes and two failures caused by blocked local process inspection; its render supervisor could not register children. Those application checks passed outside the sandbox (9 tests). The full offline baseline passed: **1,424 tests in 1,046 seconds**. This is the baseline, not the final release verification.
- Package 0 focused checks: 5 passed, including actual local Hypit and FFmpeg renders with measured premix RMS; 12 existing composition checks also passed.
- Durable checkpoint checks: 5 passed (reuse, stale binding, persisted exhaustion, corruption, complete coverage).
- Isolated helper preparation: CPython 3.11.16; public Meta source commit `3e352cca660658d4b5c90f42a7808b11469e4c66`; dependencies hash-locked in `config/flashcut-helper.lock`. PE checkpoint SHA-256 `ccc8340a14ea3ebf557a288ba4ed4a5bc026ab98bb4da42fc745d44b4c5c5ffb` verified against the pinned public release. Local encoder checks passed; broader evidence-quality qualification remains pending.
- Focused helper/queue/application checks: **33 passed**, including a real isolated Python 3.11 PE process producing six frame embeddings, credential-free child environment, persisted execution limits, and retained local-media capacity.
- Helper tests: **11 passed** before the additional energy-event checks; includes exact rational timestamps, VFR, bounded audio writes, phase-safe processing, silence, chunk equivalence, and checkpoint reuse.
- Existing services have not been restarted and no paid calls have been submitted.

## Agreed verification boundaries

The approved plan supplies the test boundaries: public composition/capability interfaces and actual rendered output; durable source-evidence interface/helper protocol; provider request/submission boundary; editorial/native Hypit output; run/status APIs and dashboard behavior. Tests use isolated databases and generated local fixtures, never frozen fixtures or production records.

## Package status

| Package | Status |
| --- | --- |
| 0 — baseline, renderer policy, premix binding | Focused checks and full baseline passed |
| 1 — immutable evidence and isolated helper | Core, queue, fenced checkpoints and backup/restore regressions implemented |
| 2 — dense audiovisual processing/fusion | All-frame PE, rational clock, phase-safe audio, fusion, exact selected images and audio-bearing windows implemented; broader qualification pending |
| 3 — Jev and enriched Gemini | Separate adapters, actual-media payloads, concrete envelope, two persisted clarifications and autorun integration implemented; live routes unverified |
| 4 — editorial/native semantic authoring | Native package, final-speech timing, durably quoted semantic editorial planning, immutable resolved plans and compiler/worker integration exercised end to end offline |
| 5 — autorun/dashboard/QC | Profile, honest progress, independent phase status, frozen template policy and authoritative final-QC context implemented; mocked browser walkthrough passed |
| Offline release checks | Complete backend 1,491 passed; isolated helper 23 passed; frontend 70 passed/build passed; protected-state checker regression also passed |
| Paid acceptance and deployment | Not authorized / not performed |

## Native authoring evidence

- Public Hypit 0.1.8 author interfaces only, via repository-owned
  `packages/aligned-speech`. JavaScript source is the executable build; exact
  package files are frozen and hashed into each new native composition.
- Actual local native render passed: Script, SemanticTake, Selection, Moment,
  Caption Fine and one premix; no speech/WhisperX Needs in the inspected plan.
  Exactly 30 rendered frames; a contrasting two-frame flash occupies only
  frames 14–15. Audio RMS agrees with the premix, not the louder timing-only WAV.
- Native/alignment/editorial regressions reject missing or altered words,
  ambiguous token mappings, stale alignments, cross-variant footage, overlapping
  required edits and out-of-range clip sampling. Changed narration creates a new
  immutable editorial record; prior resolved evidence remains readable.
- Focused evidence/editorial/speech/composition/helper regression batch:
  **32 passed in 19 seconds**. This does not replace full release verification.
- The existing Node `module.register()` deprecation warning remains visible and
  is still a separate compatibility task.

## Integrated verification

- The new-profile offline end-to-end test used real PE and native Hypit, with
  fake hosted analysis/generation/TTS/QC and fake Drive. It processed 270 source
  frames and completed all four variants through verified simulated delivery
  in 195.98 seconds. This is not live provider acceptance.
- Native actual-render checks passed at both 180×320 and 720×1280: exact
  two-frame inserts, complete frame counts, imported final speech timing, no
  extra speech/WhisperX requests and exactly one narration premix.
- An isolated dashboard on port 5178 was exercised with mocked processing,
  waiting, technical-pause and complete states. The real local fixture video
  played to its end in four Compare players. Those four mocked entries
  deliberately shared one local test file and were labeled as such; they are
  not evidence of four live finals. Unknown totals do not show invented percentages; the new
  profile locks phrase captions and required final QC.
- First complete implementation-suite run: 1,480 passed, one failure, six
  helper-module skips. The failure was a main-process/child-process policy
  mismatch caused by editing the policy during the run, not a successful
  release gate. The focused helper integration subsequently passed (8 tests).
  A clean full rerun is required and is being recorded below. Helper skips in
  Python 3.14 are covered by the separate Python 3.11 suite, not counted as
  passes in the main suite.
- The temporary QA browser tab and port-5178 server were closed after the
  walkthrough. Existing port-8100 services were not restarted.
- Additional isolated checks cover allocation fallback 8→4→2→1 without frame
  dropping, and a delayed audio pulse within 1 ms of its source timestamp after
  window extraction. The helper suite now passes **23 tests**.

### Final offline release result

- `.venv/bin/python -m pytest tests -q --ignore=tests/live -rs
  --basetemp=/private/tmp/factory-flashcut-baseline.HQnKuI/release-final-v2`:
  **1,491 passed in 1,321.76 seconds**. Six helper modules are intentionally
  unavailable to Python 3.14; all their required checks ran under the isolated
  Python 3.11 environment (**23 passed in 8.68 seconds**). No required helper
  check is counted as passed merely because the main environment skipped it.
- The subsequently added read-only protected-state checker regression:
  **1 passed**. It permits new rows and detects modifications to old rows.
- Frontend: **70 passed**, production TypeScript/Vite build passed. The inert
  browser walkthrough covers progress, waiting, technical pauses and all four
  Compare controls. The 720×1280 native caption fixture was visually inspected;
  actual output has 30 frames, the two-frame insert and one measured premix.
- `git diff --check` passed; frozen `schemas/` and `tests/fixtures/` unchanged.
- No hosted provider calls, new production run, budget mutation, historical
  reconciliation, publishing, service restart or qualified rollout occurred.

Re-run affected checks after any acceptance-driven code change; do not treat
this result as permission to bypass fresh pricing or live qualification.

## Real-seed preflight corrections (no hosted requests)

Read-only source: `89iXPZsKn9M`, source SHA-256
`6eca1c0eb95e0fcced52c3383058170360fc480e610c3219543976b610c47e98`;
verified transcript SHA-256
`aa6900d9ca27d2932be5cf1e23a63b1dacd938d5996b2bc65bcc98e9ddc089fd`.

1. The Opus stream has a one-millisecond positive timestamp gap after its
   trimmed first frame. The helper now inserts explicitly recorded zero
   padding, preserving every later source timestamp. A gap may be at most
   1 ms and cumulative padding at most 5 ms; overlaps, larger gaps and rate
   changes still pause. This is labeled padding, not recovered speech.
2. Dense acoustic events previously merged selected windows into a 26.9 MB
   re-encode. Context windows are now at most four seconds with one second
   overlap; every candidate's full context must remain represented.
3. Acoustic peaks previously caused 327 full-resolution PNG selections
   (515.7 MB) for this short source. Deterministic optional acoustic stills
   are now limited to one per second, while **all** measured events,
   audio-bearing contexts, mandatory visual/quiet/callback frames and all-frame
   PE coverage remain intact. Jev shadow advice does not remove evidence.
4. Editorial-only revisions now reuse exact, verified, same-variant generated
   footage through normal production planning. Changed requests and variants
   cannot share assets. Corrupt assets or matching unresolved operations pause
   instead of silently causing another paid submission.

These fixes are future-profile-only. Prior preflight directories retain their
failure evidence; no historical source record was rewritten.

The corrected preflight completed **635/635** PE frames and source-clock audio,
producing 57 selected exact images and seven windows in 100.846 seconds. Fresh
Stage 1 quote and the explicit remaining approval boundary:
[acceptance quote](FLASHCUT-ACCEPTANCE-QUOTE.md). No paid request was sent.

## Installed baseline and benchmark

- Main application: Python 3.14.3; Node 26.7.0; Hypit 0.1.8; FFmpeg 8.0.
- Helper: Python 3.11.16; torch 2.8.0; torchvision 0.23.0; PyAV 18.0.0;
  numpy 2.1.2; scipy 1.15.2; librosa 0.11.0; Pillow 11.3.0; timm 1.0.15.
  The complete dependency graph is hash-locked; setup and license notices are
  in [the helper runbook](../flashcut-helper.md).
- Synthetic 270-frame benchmark: cold 23.063 s, cached 0.533 s,
  peak RSS 1,171,881,984 bytes and retained disk 5,092,552 bytes. Both flash
  frames, opening/ending, callback and antiphase audio survived. Warm reuse
  retained the exact manifest identity. Evidence:
  `/private/tmp/factory-flashcut-baseline.HQnKuI/benchmark-v1/report.json`.
- These are local fixture measurements, not a speed SLA, semantic-accuracy
  comparison, Jev cost saving or virality claim. The real source is more
  expensive to decode and process than the low-resolution synthetic fixture.

## Protected state and current limits

A read-only audit after implementation confirmed identical fingerprints for
records, jobs, artifacts, budgets, reservations, reservation lines, attempts and
effect bindings, identical final bindings and all **16 unchanged final files**.
No production connection setting, historical approval/hold, active service or
paused run has been deliberately changed. Recheck these immediately before and
after any eventual deployment.

`scripts/flashcut-protected-check.py` also verified each existing row by its
stable primary key against the consistent backup, allowing future newly added
acceptance rows without overlooking changes to old rows. Its dedicated offline
regression passes; all 16 final files and all protected rows currently match.

The new routes are not globally live-qualified. A first qualification can use
an expiring scope bound to exactly one new run/seed/source hash, but that scope
does **not** grant spending authority. Every paid operation still needs a fresh
quote/reservation. Unknown submissions keep their identities and holds.

The Hypit skill guided use of public native timing/authoring interfaces and one
premix. The TDD workflow required reproducing regressions before repairs; the
browser skill kept walkthroughs on an isolated mocked page rather than touching
live jobs. Frozen schemas/fixtures remain untouched.

Read-only live health after QA cleanup: API and storage healthy; exactly one
existing API process (14216) and one worker (14217), worker available and not
draining. Port 5178 has no listener. This verifies the unchanged services, not
a deployment of the candidate backend.

Deferred: MPS, reference-conditioned generation, multi-seed quality/cost
benchmarking and the existing Hypit/Node compatibility warning. Unverified:
live Jev credentials/usage, Gemini 3.8 account/payload acceptance, real generated
footage quality, live final QC/Drive delivery and qualified deployment.
