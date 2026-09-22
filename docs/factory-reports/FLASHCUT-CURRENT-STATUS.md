# Flash-cut workflow — current handover

Updated 2026-09-22. This is the current status index for the AVvVLM5b-mE
acceptance run. Older reports retain their original checkpoint evidence; their
paused-state statements do not describe the completed run.

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

1. **Implemented offline, rollout pending:** unusable completed narration
   rewrites can consume a distinct second bounded attempt, and completed invalid
   editorial plans can use a conservative deterministic fallback when every
   retained event remains source-bound and unambiguous. Unsafe cases still pause.
2. Preserve and reconcile unknown outcomes only with evidence. Do not erase old
   holds, resubmit unknown requests or treat execution-capacity release as a refund.
3. **Implemented offline, rollout pending:** each newly created automatic run
   receives an isolated cumulative $50 USD guardrail. Holds and settlements
   count; Resume cannot drop it; unrelated runs cannot select it. Stricter
   shared/provider/category ceilings still apply. This does not fund live tests.
4. **Implemented and focused end-to-end checked:** future runs can plan
   bounded saved-response recovery for a completed response-cap failure. It does
   not replay an unknown HTTP 500. New analysis routes still require qualification
   beyond this exact run/source. Reference-conditioned generation remains disabled
   pending its own authorized live qualification.
5. Measure Jev's benefit and test real rapid-cut, callback, silence and VFR fixtures.
   This continuous-footage seed does not establish flash-cut reproduction quality.
6. **Implemented for future v2 runs:** final technical QC now checks every decoded
   output timestamp, phrase captions against final replacement-speech alignment,
   and decoded-frame occupancy of required brief editorial intervals. It does not
   semantically recognize the intended event, run pixel OCR or verify lip sync;
   sampled visual review remains non-exhaustive. Weak rhythm is a valid result,
   not itself a bug. Historical v1 runs retain their saved QC behavior.
7. Finish release requalification. The complete dashboard suite (72 tests) and
   production build pass. Focused temporal policy/quality checks (21) and one
   actual offline A/B/C/D native-Hypit path (219.46s) pass. The clean complete
   backend result and final protected-state comparison are still pending.
8. Improve safe historical visibility controls if needed. Existing archive
   eligibility protected unresolved work; no historical clearing was performed.

The hardening tracker is
[FUTURE-RUN-HARDENING-2026-09-22.md](FUTURE-RUN-HARDENING-2026-09-22.md).
Focused passing tests are evidence only for completed slices, not a full release
qualification or new spending authorization. Provider latency and interactive
authentication cannot be guaranteed away. No exact per-issue delay breakdown
was measured.

## Verification and evidence

Focused checks recorded during recovery include 105 coverage/recovery tests,
36 rendering/composition tests and 31 final-review/context/quality tests. These
are separate, potentially overlapping runs, not an additive full-suite total.
Real Hypit/FFmpeg fixtures and final decode/audio checks passed. The complete
backend/frontend suite was not rerun after the final recovery patches.

All 16 historical final bindings/hashes and protected records, jobs, attempts,
assets, reservations and effect bindings remained unchanged. Five baseline
budget-row differences are earlier explicitly approved ceiling changes.

- [Completed run, final links and cleanup evidence](FLASHCUT-CONTEXT-REUSE.md)
- [Historical seed/recovery checkpoints](FLASHCUT-NEW-SEED-AVvVLM5b-mE.md)
- [Historical bounded format recovery quote](FLASHCUT-FORMAT-RECOVERY-QUOTE.md)
- [Operator guide](../factory-operator-guide.md)
