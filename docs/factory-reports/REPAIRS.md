# Factory repair ledger

Starting revision: `dae132a`, branch `feat/factory`. The user authorized S0–S8
implementation and the public test boundaries listed in REPAIR-BASELINE.json.
All checks use offline providers; no new live spend or publication scope exists.

## Package evidence

| Package | Status | Evidence |
| --- | --- | --- |
| S0 containment | passed (offline checkpoint) | 856 suite tests passed in 115.35s; 5 focused safety tests passed (the final regression was added after full-suite collection); Approval clock regression reproduced then fixed; structured event redaction; unavailable handlers and empty reviews block; live transport policy defaults offline |
| S1 state/restore | passed | 863 tests pass (117.24s); atomic v7→v8 migration fault/retry; restored media/ledger checks; normal CLI shares restored database |
| S2 effects/budgets | planned | |
| S3 adapters | planned | |
| S4 media/QC | planned | |
| S5 application | planned | |
| S6 research | planned | |
| S7 publishing/learning | planned | |
| S8 qualification | planned | |

## Finding dispositions

Disabling a capability is containment, not closure. Live qualification is
separate from engineering repairs; historical tests do not sign either gate.

| Finding | Engineering status | Validation |
| --- | --- | --- |
| R01 | open | |
| R02 | open | |
| R03 | open | |
| R04 | open | |
| R05 | open | |
| R06 | open | |
| R07 | open | |
| R08 | open | |
| R09 | open | |
| R10 | open | |
| R11 | open | |
| R12 | open | |
| R13 | open | |
| R14 | open | |
| R15 | open | |
| R16 | open | |
| R17 | open | |
| R18 | open | |
| R19 | open | |
| R20 | open | |
| R21 | open | |
| R22 | open | |
| R23 | open | |
| R24 | open | |
| R25 | in_progress | Self-contained verified backup and persistent restore hold fixed; S2 must enforce hold at dispatch |
| R26 | open | |
| R27 | open | |
| R28 | open | |
| R29 | open | |
| R30 | open | |
| R31 | open | |
| R32 | open | |
| R33 | open | |
| R34 | open | |
| R35 | open | |
| R36 | open | |
| R37 | fixed | Rebranch preserves prior variants; composition history retained; persisted template references resolve |
| R38 | in_progress | Nested credentials redacted before durable events and replay; live transport/API audit remains |
| R39 | open | |
| R40 | fixed | Approval grant/check share injected time; 7 approval tests pass |
| R41 | open | |
| R42 | open | |
| R43 | open | |
