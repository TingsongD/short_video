# Scene-review removal

## Requested change

Remove the Auto pipeline's AI and manual scene-review gate and its dashboard controls. This supersedes the earlier request to improve autonomous review. Final-video quality checks, source/timing validation, provider readiness, budget enforcement and unknown-paid-operation safeguards remain in scope and unchanged.

## Implementation

- Auto prepares structurally valid blueprints directly, retaining semantic warnings and original confidence. It records `prepared_without_scene_review`, `review_performed: false`, and a run limitation instead of fabricating an AI or human verdict.
- Removed live scene-review orchestration, paid correction/verification submission, override/replacement actions, and the provider's `review_blueprint` execution route. The old creation toggle cannot reactivate it.
- Removed AIReviewPanel, Manual fix, Proceed anyways, source-timing acceptance controls, scene cards and their styles from the dashboard. Renamed the remaining technical Analysis review label to Analysis checks.
- Kept read-only compatibility for historical adopted corrections and paid-attempt accounting. Unknown or still-active legacy requests block Resume. Historical content-only pauses present Ready to continue and ordinary Resume; they never buy another scene review.
- Updated the operator guide. Independent final asset/video reviews remain available.

## Verification

- New/updated backend tests cover automatic progress with flagged scenes, no scene-review provider calls, no fabricated reviewed confidence, stale hashes, timeline gaps, changed source, old paid-outcome guards, and rejection of retired API actions.
- Initial broad backend selection: 101 passed, one obsolete scene-card assertion failed (307.11 seconds). Updated that assertion to require absence of the removed UI data and safe Resume guidance.
- Current affected backend suites rerun: 76 passed (15.98 seconds), including the corrected assertion and additional structural tests. The broad run's 28 Auto pipeline/rendering tests passed; no rendering implementation changed afterward. Two dependency deprecation warnings remain.
- Dashboard: 50 tests passed; TypeScript/Vite build passed. Deployed bundle `index-D5yy4vrp.js`.
- Reloaded only idle owned services: API PID 69479, worker PID 69538. Verified unchanged jobs, attempts, run records, reservations and reservation lines across reload.
- Live browser at port 8100: current run shows Ready to continue with normal technical validation; zero Manual fix and Proceed anyways buttons. No generation was submitted by deployment.

## Current production state

Run `auto-8608da8a08644aa8` remains paused, ready for ordinary Resume. Its original disagreement and paid receipts are preserved, not retroactively marked passed. This feature change does not claim completion of the three-round QA goal or any final videos.
