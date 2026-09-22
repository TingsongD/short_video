# Flash-cut acceptance preflight and staged quote

Prepared 2026-09-21. **Superseded by the user's new seed `AVvVLM5b-mE` on
2026-09-22 UTC. No paid requests submitted for this acceptance; no new run created.**

The four proposed shared ceiling increases below were subsequently explicitly
approved and applied exactly as listed. The user then replaced this acceptance
request with a clean-start request for `AVvVLM5b-mE` and standing approval for
videos under $50. Do not launch the old seed or reuse this seed-specific quote.
See `FLASHCUT-NEW-SEED-AVvVLM5b-mE.md` for the pending reset choice and new scope.

Seed: [89iXPZsKn9M](https://www.youtube.com/shorts/89iXPZsKn9M).
One new run is intended, with four A/B/C/D finals. No publishing.
Historical spending approvals do not apply.

## Verified local inputs

- Source SHA-256: `6eca1c0eb95e0fcced52c3383058170360fc480e610c3219543976b610c47e98`.
- Transcript SHA-256: `aa6900d9ca27d2932be5cf1e23a63b1dacd938d5996b2bc65bcc98e9ddc089fd`.
- Actual video clock: `127/6` seconds; **635 decoded / 635 PE-encoded frames**.
- Source-clock audio processing completed; the measured one-millisecond gap is
  represented as explicit padding, not shifted speech or invented source audio.
- 57 original-resolution selected images and seven overlapping, audio-bearing
  windows. All 188 measured candidates remain represented in the evidence.
- Local preflight: 100.846 seconds; retained workspace about 134.38 MiB.
  The duration is an observation on this machine, not a performance guarantee.
- Output: `/private/tmp/factory-flashcut-baseline.HQnKuI/seed-preflight-v4/`.
  `analysis-plan.json` contains the frozen concrete requests; `quote.json`
  contains bounds and dated pricing. The database is isolated from the app.

## Stage 1 — new source analysis only

| Operation | Frozen allowance | USD reservation estimate |
| --- | --- | ---: |
| Gemini 3.8 Flash audiovisual analysis | 13 concrete initial requests + at most two clarification requests | 3.246437 |
| Jev 1.13 shadow advice | Six bounded text-only requests; no hidden retries | 0.006044 |
| Total source-analysis maximum reservation | Both routes combined | **3.252481** |

Requested authorization: **US$3.26 aggregate, this new run's source-analysis
stage only**, after offline checks pass. The small rounding margin is not
permission to change models, increase clarification counts or retry an unknown
submission. Actual live requests are re-quoted before authorization; if they
exceed the approved cap, pause and request a revised quote.

The Gemini cumulative envelope, including worst-case clarification allowances:
15 requests, 105 image inputs, 30 video inputs, 1,269.1 seconds of submitted
media counting repeated context, 259,941,280 payload bytes, 3,714,176 input-token
bound and 122,880 output-token bound. Each request remains within the separately
qualified route's individual limits. These are conservative reservation bounds,
not expected usage or confirmed charges.

Rates checked against [Google Cloud pricing](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing)
and [TypeSafe model pricing](https://docs.typesafe.ai/models): Gemini standard
introductory input/output rates $0.75/$3.75 per million tokens; Jev input $0.042
per million and free output. This local quote expires September 22, 2026,
23:59:59 UTC; recheck rates before using it later. Taxes or account adjustments
are not modeled as provider-confirmed usage.

## Later production quote — not yet authorized

The final-word editorial planning request has a bounded maximum reservation of
$0.078720, but cannot be concretely authored until replacement TTS/alignment is
final. This allowance is **not included in the Stage 1 authorization**.

Scripts, TTS and its two bounded repairs, music, variant footage and its two
bounded overlay repairs per clip, final visual QC and delivery remain separately
unquoted. Their quantities depend on the new analysis and scripts. Do not use
the old paused run's plan as if it were the new production quote, or infer an
unlimited allowance. Present the next concrete stage quote before paid work.

## Dispatch preflight after approval

The user approved the source-analysis-only US$3.26 ceiling. The quote remains
valid, but these four non-retired aggregate USD ceilings have zero headroom:

| Shared budget | Current ceiling / committed USD | Proposed ceiling USD, not authorized |
| --- | ---: | ---: |
| `7udu-approved-20260920-usd` | 62.336690 | 65.596690 |
| `nffa1-live-test-20260920-usd` | 70.971330 | 74.231330 |
| `syp34-vertex-approved-4590780` | 92.373040 | 95.633040 |
| `syp34-vertex-approved-6886170` | 87.782260 | 91.042260 |

Normal accounting applies all four shared ceilings to new work. An isolated
US$3.26 run budget does not bypass them. Raising each by US$3.26 is a separate
change to protected historical budget rows and could enable unrelated work;
request that explicit exception before changing them. No ceiling, reservation,
historical record, connection setting or service was changed during this check.
No new run was created. Production authorization remains outstanding.

## Secure setup and qualification

- Supply the Typesafe key through the ignored owner-only `config/secrets.toml`
  (`[typesafe]` / `api_key` resolves to `TYPESAFE_API_KEY`; `[jev]` / `api_key`
  resolves to the supported `JEV_API_KEY` alias). Never paste the key into chat,
  logs, this report or connection metadata. As of 2026-09-21 the user-supplied
  alias is detected through the existing private configuration loader;
  authentication remains unverified. No secret was copied or changed.
- The new Google and Jev routes must use their own offline contract evidence
  and one expiring `acceptance_scope` containing the new run ID, seed ID,
  source SHA-256 and expiry. The source evidence must belong to that run.
- This scope enables only the first qualification transport; it grants no
  budget authority and does not mark the route live-qualified. Do not copy
  qualification from the legacy Gemini or text-video route.
- Keep `jev-1.13.0` in shadow mode. Missing advice may conservatively fall back
  without dropping evidence, but a run that never exercises Jev cannot claim
  Jev live qualification. Unknown operations keep holds and are not replayed.
- Do not enable reference-conditioned generation, publish, resume historical
  jobs, raise shared ceilings or reconcile old holds as part of this acceptance.

## Completion and promotion

After each separately approved stage, continue the **same new acceptance run**.
Require all four native Hypit finals, authoritative QC passes, current Compare
players and verified Drive receipts before qualification. Verify destination,
name, size and checksum; ambiguous uploads require reconciliation, not duplicates.
Clean up only video-owned services. Promote the profile only after protected
record/file fingerprints and one-worker health checks pass.

Until then, report the implementation as offline-tested and live acceptance as
pending, not fully delivered or deployed.
