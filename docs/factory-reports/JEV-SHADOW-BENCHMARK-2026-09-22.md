# Jev shadow benchmark — 2026-09-22

This is a read-only audit of the Jev shadow calls from completed run
`auto-2c9de6ddf2e34d5c`. It is not a new provider test, an invoice
reconciliation, or authority for another live call.

## Result

**Active Jev filtering remains disabled and unqualified.** The three requests
covered only the continuous-footage seed bound to source SHA-256
`026ff7cd811e5d78e80b88bd77d3fa346281ef883799641366b00f227d78bc5f`.
Jev returned `retain` for all 78 optional candidates. Therefore it removed no
evidence, produced no downstream payload saving, and did not demonstrate better
quality or lower cost.

| Metric | Observed value |
| --- | ---: |
| Requests with terminal responses | 3 |
| Optional candidates | 78 |
| Retained | 78 |
| Marked optional/removable | 0 |
| Input tokens reported by provider | 17,108 |
| Output tokens reported by provider | 2,978 |
| Request latencies from durable attempt timestamps | 213 ms, 276 ms, 307 ms |
| p50 / p95 latency (nearest-rank) | 276 ms / 307 ms |
| Usage-derived estimate at the saved $0.042/M input rate | 720 USD micros total |
| Conservatively held quote estimates | 2,752 USD micros total |
| Evidence-selection reduction | 0% |
| Required labeled case coverage | 1 of 9 (`continuous_footage`) |

The usage-derived number is calculated per request from observed input tokens;
output was free under the saved dated price. It is **not invoice-confirmed**.
The three reservations remain held and are still counted by every applicable
ceiling; repeated rows across ceilings are not repeated charges. This audit does
not settle, release, duplicate, or otherwise modify them.

## Immutable evidence

| Operation | Response SHA-256 | Optional decisions | Input / output tokens | Latency | Held estimate |
| --- | --- | ---: | ---: | ---: | ---: |
| `sync-a453aea8bc580bc36dadcd8766b27463` | `c266226fac02a445cc6bd60415ecf18c6bef6c16573504dd2d9c355fb358e2e2` | 30 retain | 6,362 / 1,129 | 307 ms | 1,039 micros |
| `sync-486fe3b109071cc9d9a14813e6cb3412` | `83006cef71e7f42f982ea49bf2f7116a3150239500e8a70e067f8924e15b710d` | 27 retain | 6,018 / 1,041 | 213 ms | 966 micros |
| `sync-92e7fb47c35f73a3cce28e43e6e5363f` | `eb533cd271c04d1201cec7649a6e0b6aae258e7b9f2121453f6b47976b9b387e` | 21 retain | 4,728 / 808 | 276 ms | 747 micros |

Evidence lives under `data/factory/providers/jev-decisions/`; attempt and
reservation identities remain in `data/factory/factory.db`. The saved pricing
evidence was checked on 2026-09-21 and expires at
`2026-09-22T23:59:59Z`, so it cannot authorize future use after expiry.

## Qualification gate added

`jev_selection_benchmark.v1` now requires all nine frozen labeled cases:

1. rapid cuts including a two-frame event;
2. continuous footage;
3. repeated callback;
4. quiet setup/payoff;
5. VFR timing;
6. silence;
7. weak rhythm;
8. clear beats; and
9. audiovisual disagreement.

Active filtering requires a self-verifying report with:

- zero mandatory and labeled-relevance loss for both the deterministic baseline
  and the Jev result;
- a recorded Jev observation for every case;
- at least one safely removed optional item;
- estimated downstream savings greater than Jev's recorded/estimated cost; and
- p95 Jev latency no greater than 2,000 ms.

The active selector reconstructs the report from retained case evidence and
rejects a hand-written or altered `qualified: true` value. The current report
fails case coverage, selection benefit and net-cost benefit, so new runs remain
on the saved `shadow` policy.

Offline evidence: the complete helper suite is 27 passing tests; Jev route and
benchmark gating are 8 passing tests. These are development measurements, not a
claim that Jev improves virality or interpretation.
