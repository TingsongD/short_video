# Future-run improvements — implementation and validation

Scope: the approved future-run plan after three-round QA. No paid live
acceptance run, generation submission, publishing, ceiling increase, historical
settlement or modification of completed videos is included in this work.

## Implemented

- **Versioned policies:** new dashboard launches explicitly opt into full-video
  variations, phrase captions and two bounded speech/overlay repairs. Automatic
  Drive delivery defaults on only with a configured authorized destination and
  pinned account. Older runs and API clients omitting policies retain legacy
  behavior. Output policies participate in draft/plan/render identities.
- **Narration repair:** measured duration drives a shorter complete rewrite
  that must preserve A's meaning/light paraphrase or B/C/D's hypothesis. Durable
  counters and pending intents enforce at most two repairs per affected segment
  across restarts. Each paid operation uses quotes, scope/authority checks and
  reservations. Unknown outcomes pause for reconciliation; unchanged narration
  reuses its original synthesis. Dependent work follows the revised draft.
- **Footage:** every B/C/D beat receives variant-specific generation with common
  character/wardrobe/setting context and coherent per-variant visual direction.
  Full-video provenance checks reject missing beat coverage, shared bindings
  and identical cross-variant asset bytes. Full-video mode replaces only the
  unchanged-picture restriction, retaining applicable audio, timing, source and
  technical checks. Compare explicitly labels multi-variable creative comparisons.
- **Overlay checks:** generated clips undergo visual QC before caption rendering.
  Incidental environmental text is accepted; ambiguous evidence pauses without
  regeneration. Confirmed unwanted overlays permit at most two independently
  quoted targeted repairs. Setting the limit to zero disables repairs, not QC.
  The original assets/attempts remain in the audit trail; no seed/shared fallback.
- **Captions:** complete final-narration text coverage, ordered timestamps and
  beat bounds; exact provider-submitted text for character alignment, normalized
  final speech for injected alignment. Short phrases, punctuation grouping,
  at most two lines, 48px at 720p with proportional scaling, measured font widths,
  high contrast and safe margins in FFmpeg and Hypit. Long words fail explicitly
  rather than shrinking. Unreliable alignment has a specific recovery message.
- **Delivery:** current-revision automated QC, creative approval, verified upload
  and publishing remain separate. Automatic delivery never fabricates human
  approval. Remote parent/name/size/checksum must match; existing identical
  external uploads can be reconciled. Duplicate matches or missing checksums
  do not trigger duplicate uploads. Verified completion requires video-owned
  cleanup; shared API/worker services are not cleanup targets.
- **Dashboard/accounting:** generation, QC and delivery states are separate;
  durable per-segment/clip repair counts and actionable pauses are visible.
  Estimates, provider-confirmed usage, quoted usage and unresolved holds are
  separate. Historical evidence and do-not-retry decisions are preserved.
- **Dependencies:** verified the installed graph and pinned compatible FastAPI
  0.141.1 / Starlette 1.6.0 / httpx2 2.13.0 / AnyIO 4.14.2; retained httpx 0.28.1
  for other clients. Pillow 12.3.0 provides caption font metrics. No warning
  suppression. The separate vendor Hypit launcher still emits a Node
  `module.register()` deprecation notice; that is not a Starlette/AnyIO warning.

## Verification

- Complete offline backend suite: **1,306 passed in 839.34s**.
- Final expanded focused regression set: **65 passed in 98.23s**.
- Additional full-video quote/provenance/targeted-repair checks:
  **3 passed in 61.24s** (including the two newly added scenarios).
- Frontend: **53 passed**, 12 test files; production TypeScript/Vite build passed.
- Dependency check: all **40 installed packages compatible**. `git diff --check`
  passed. Frozen schemas and fixtures were not edited.
- Mock browser dashboard: inspected new controls, separate completion phases,
  repair exhaustion and accounting labels with all actions inert.
- Real local FFmpeg caption fixture: 720×1280, 30fps, 30 frames; visually checked.
- Real Hypit caption fixture: checked/planned/built/retrieved at the same size
  and frame count, then visually checked. Plan explicitly reported five local
  requests, **zero provider requests**, and passing preflight. Build
  `bld_20260921T063150070Z_228317BB74` completed in the isolated temporary fixture
  workspace `/private/tmp/factory-caption-qa.DfOEVB`. This synthetic test fixture
  is not a user production export and was not uploaded.

The focused tests cover repair exhaustion/restart, refusal of insufficient
budget, no replay after a lost repair response, unchanged speech reuse, every-
beat variation and accurate price aggregation, cross-variant duplicate rejection,
incidental-text acceptance, uncertainty/zero-limit pauses, single-clip recovery,
phrase layout/coverage, automatic delivery without human approval, failed/stale
QC, lost upload acknowledgements, ambiguous external matches and retained holds.

## Rollout and limits

Offline validation and local API/worker rollout are complete. The pre-restart
read-only audit found three succeeded runs, twelve final bindings and no
ready/running jobs. After the graceful idle-service restart, API/storage health
and the single worker heartbeat were healthy. SHA-256 fingerprints of all
application records, budgets, reservations and twelve final bindings were
**identical before and after restart**. No completed run was migrated.

Rollout also found the existing local WhisperX helper stopped. It was restored
using the existing runtime's endpoint startup, which reported ready; no
transcription was submitted and runtime configuration was not changed. The
live Auto screen shows a connected worker and the new default controls. A
misleading legacy per-operation-limit label was corrected to per-plan limits,
matching the existing enforcement rather than changing budget authority.
The isolated mock-dashboard tab/server were closed and port 5191 verified free;
the shared dashboard remains running on 8100.

No live creative quality or provider latency/cost claim is made from fixture
tests. Character continuity remains a prompted requirement checked by visual QC,
not a guarantee of identity or lip sync. A paid acceptance run needs fresh
authorization and does not extend the completed three-round QA cycle.
