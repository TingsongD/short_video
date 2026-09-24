# Parallel footage generation — 2026-09-22

The user requested concurrent generation after the completed AVvVLM5b-mE
batch spent about 28 minutes generating and collecting 16 footage clips
sequentially. This local patch enables up to four Vertex operations in flight
across runs. Jimeng retains five slots; local exports retain one.

## Changes

- Vertex's default capacity is four. Application startup applies
  `FACTORY_VERTEX_CONCURRENCY` (default `4`, integer `0`–`16`) to existing as
  well as new databases, recording an event when the limit changes. `0`
  prevents new Vertex slot reservations while allowing already reserved work
  to continue; Pause remains the control for stopping dispatch.
- The worker rotates collection, observation and dispatch queues instead of
  always polling before considering a new submission. Deferred work is ordered
  by its next eligible time, allowing a later clip to finish before a slow
  earlier clip. The production-service runner uses the same queue selection.
- A single local worker coordinates the remote operations. Database writes and
  submission bookkeeping remain sequential; provider jobs overlap remotely.
- Every submission retains the existing authorization, quote, budget,
  capability, dependency and idempotency checks. Unknown operations continue
  counting toward capacity and spending. Lowering the limit leaves existing
  holds intact and blocks new work until a slot becomes available.
- This supersedes the handover's original one-Vertex-slot default at the user's
  request. It does not change the number of requested clips, the 30 fps policy,
  paid scope or the retired partial-batch recovery feature.

## Verification

- The 12 new offline checks passed. They exercise four requests running before
  any completes, slow polling, out-of-order completion, collection while paused,
  slot refill, budget exhaustion, lost-response identity, reduced limits,
  existing-database configuration and invalid settings.
- The existing OS worker-death test now requires five Jimeng and four Vertex
  operations to remain held across a crash, then verifies all twelve requested
  clips download without duplicate submissions.
- All four offline F06 scheduler scenarios pass; the capacity scenario now
  queues six Vertex jobs and verifies the four-slot limit. This is automated
  evidence, not a human F-module sign-off.
- Full backend regression run: **1,622 passed, 7 skipped in 2,374.67 seconds
  (39:34)**, using `PYTEST_ADDOPTS='-x --durations=15' make test`. This includes
  the real worker-death test and local rendering. The seven helper-import skips
  are the existing separate-environment cases. The first restricted test run
  hit the sandbox's process-inspection restriction in existing crash/render
  tests; the complete passing run used local process and loopback access.

## Activation and limits

Restart the API and the one worker with the same configuration to apply the
local patch. This coding session does not start production services, resume
queued paid work or make provider calls. Actual four-way Vertex throughput and
quota behavior still require observation during an authorized live run; no
measured speedup is claimed from the offline checks.
