# Flash-cut workflow — current handover

Updated 2026-09-22. This is the current status index for the AVvVLM5b-mE
acceptance run. Older reports retain their original checkpoint evidence; their
paused-state statements do not describe the completed run.

Future-run hardening is tracked separately in
[FUTURE-RUN-HARDENING-2026-09-22.md](FUTURE-RUN-HARDENING-2026-09-22.md).
The [qualification matrix](FLASHCUT-QUALIFICATION-MATRIX.md) distinguishes the
completed run's narrow live acceptance from the new v3 compact evidence route.
The [live-only checklist](FLASHCUT-LIVE-ONLY-ACCEPTANCE.md) contains unpaid
three-seed stage-one estimates; it does not authorize provider requests.

## Outcome

- Run: `auto-2c9de6ddf2e34d5c`; experiment: `exp-auto-2c9de6ddf2e34d5c`, revision 3.
- A/B/C/D completed, passed final QC, loaded in Compare and were verified on Drive.
- Each final: 720×1280, 424 frames, approximately 14.13 seconds.
- All 423 decoded source frames were encoded by PE; audio analysis completed.
  Jev ran in shadow mode. Rhythm was reported unreliable, not fabricated.
- Verified delivery destination: [factory-deliveries](https://drive.google.com/drive/folders/1dDy1kKvQI8gio3k1oOjgqeIepjZnyiLM),
  the destination saved on this run. Do not infer a different run's destination.
- Video-owned cleanup verified; shared services retained. Nothing published or scheduled.
- Completion-time remaining authority: $33.479344 of the cumulative $50 USD
  ceiling and 9,361 of 10,000 separately bounded prepaid TTS credits. These are
  ledger headroom figures, not a provider invoice: unresolved holds remain counted.

## Fixes and recoveries

| Finding | Verified disposition |
| --- | --- |
| Truncated Gemini output | Bounded, separately quoted recovery with revised token/thinking limits; no replay of unknown calls |
| Overlapping video-window rejection | Continuous cited-window union accepted; actual gaps still rejected |
| HTTP 400 schema rejection | Compact provider schema accepted; strict local validation retained; exact old rejected constraint not isolated |
| Completed responses retaining execution slots | Evidence-backed capacity release, independent of financial settlement |
| Recovery/status ambiguity | Persisted clarification counts and specific HTTP 400/500 recovery messages |
| Missing context already covered elsewhere | Source-bound evidence reuse; one candidate inspected by the assistant |
| Overlong narration and unusable repair | Assistant corrected this draft; final speech fitted, unchanged speech reused |
| Incomplete editorial plan | Assistant-authored, independently validated plan; provider outcome/hold preserved |
| Generic footage direction | This run's prompts received scene-local actions |
| Hypit fractional audio endpoint | Exact-frame native premix trim; actual local rendering regressions passed |
| QC demanded original source captions | Replacement-caption policy clarified; fresh B recheck passed without human approval |
| Slow generation | Original remote request observed to completion; no duplicate submission |

Authentication was restored interactively. Source-language interpretation also
required a run-specific correction; Chinese recognition/translation changes are
explicitly outside the requested next hardening scope.

## Follow-on hardening status

1. **Deployed for future runs:** unusable completed narration
   rewrites can consume a distinct second bounded attempt, and completed invalid
   editorial plans can use a conservative deterministic fallback when every
   retained event remains source-bound and unambiguous. Unsafe cases still pause.
2. Preserve and reconcile unknown outcomes only with evidence. Do not erase old
   holds, resubmit unknown requests or treat execution-capacity release as a refund.
3. **Deployed for future runs:** each newly created automatic run
   receives an isolated cumulative $50 USD guardrail. Holds and settlements
   count; Resume cannot drop it; unrelated runs cannot select it. Stricter
   shared/provider/category ceilings still apply. This does not fund live tests.
4. **Deployed and end-to-end checked offline:** future runs can plan
   bounded saved-response recovery for a completed response-cap failure. It does
   not replay an unknown HTTP 500. New analysis routes still require qualification
   beyond this exact run/source. Reference-conditioned generation remains disabled
   pending its own authorized live qualification.
5. Jev's retained shadow observations covered only one of nine required
   labeled cases and removed none of 78 optional candidates. The nine-case
   offline gate and rapid-cut, callback, silence and VFR fixtures now exist,
   but active filtering remains disabled. This continuous-footage seed does
   not establish flash-cut reproduction quality.
6. **Implemented for future v2/v3 runs:** final technical QC now checks every decoded
   output timestamp, phrase captions against final replacement-speech alignment,
   and decoded-frame occupancy of required brief editorial intervals. It does not
   semantically recognize the intended event, run pixel OCR or verify lip sync;
   sampled visual review remains non-exhaustive. Weak rhythm is a valid result,
   not itself a bug. Historical v1 runs retain their saved QC behavior.
7. Future v3 evidence packaging passed unpaid all-frame preflight on three
   retained seeds: 1,869, 635 and 423 source frames. Clock-bound image/window
   bundles and candidate partitioning fit the saved per-request limits without
   removing measured candidates. Provider acceptance on those new payloads
   remains unverified; see the separate live-only checklist.
8. The local release gate passed: backend 1,573 tests with seven helper-import
   skips, separate Python 3.11 helper 27 tests, dashboard 73 tests and build,
   and 16 actual Hypit/FFmpeg render tests with no renderer skips. The owned
   API/worker were restarted while idle, with zero active jobs in the backup.
   All 20 protected final hashes and tracked historical rows still match.
9. Safe UI-only history hiding is available for eligible entries. Unresolved
   work remains discoverable; no historical clearing was performed.

The hardening tracker is
[FUTURE-RUN-HARDENING-2026-09-22.md](FUTURE-RUN-HARDENING-2026-09-22.md).
The local release gate does not qualify new Gemini media payloads or unattended
multi-seed quality and is not new spending authorization. Provider latency and
interactive authentication cannot be guaranteed away. No exact per-issue delay
breakdown was measured.

## Verification and evidence

Focused checks recorded during recovery include 105 coverage/recovery tests,
36 rendering/composition tests and 31 final-review/context/quality tests. These
are separate, potentially overlapping runs, not an additive full-suite total.
Real Hypit/FFmpeg fixtures and final decode/audio checks passed. At the time
the AVv run completed, the complete suite had not been rerun; the follow-on
hardening release results are now listed above and in the tracker.

All 16 historical final bindings/hashes and protected records, jobs, attempts,
assets, reservations and effect bindings remained unchanged. Five baseline
budget-row differences are earlier explicitly approved ceiling changes.

- [Completed run, final links and cleanup evidence](FLASHCUT-CONTEXT-REUSE.md)
- [Historical seed/recovery checkpoints](FLASHCUT-NEW-SEED-AVvVLM5b-mE.md)
- [Historical bounded format recovery quote](FLASHCUT-FORMAT-RECOVERY-QUOTE.md)
- [Operator guide](../factory-operator-guide.md)
