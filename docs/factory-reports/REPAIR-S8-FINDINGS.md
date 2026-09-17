# S8 — Finding-by-finding repair evidence

Scope: the 43 findings in [the independent review](REVIEW-2026-09-17.md).
S8 is the focused commit containing this document; its parent is `f282bce`.
The exact tested source files are hashed in `REPAIR-S8-EVIDENCE.json`. S0–S7
commit IDs below identify the primary implementations; S8 integrates and
requalifies them. No operational credentials, assets or financial state were
used for these tests.

**Disposition:** implemented with offline regression evidence. This is not
production qualification. A route being unavailable is never the evidence for
its repair. Protocol fixtures, real local processing and original-attempt
recovery are the evidence. Optional generated music, unqualified reference
modes and automatic paid replacement remain explicitly outside the enabled scope.

## Evidence keys

- **Application:** `tests/test_factory_application.py`, the public production-to-
  publishing journey in `tests/test_factory_repairs_learning.py`, and the real
  HTTP/independent-worker runs in `s8-evidence/{short,long}-journey.json`.
- **Release drills:** `tests/test_factory_repairs_release.py` launches actual OS
  workers and kills them before submission, after remote acceptance, during
  download, rendering and upload. Remote fakes persist independently of the app
  database and do not hide duplicate submission by deduplicating it themselves.
- **Concurrency:** six independent worker processes hold five Jimeng and one
  Vertex operation across lease expiry/death; one local renderer survives caller
  loss without releasing its capacity early.
- **Browser:** mounted production build checked in two tabs; selection and
  worker progress survive refresh; four final identities and delivery/cleanup
  receipts displayed. Browser action uncertainty and named-SSE replay also have
  permanent frontend/API tests. Lost HTTP response is tested programmatically,
  not claimed as a manually induced browser network outage.
- **Restore:** populated v7 migration, interrupted migration, self-contained
  backup, CLI fresh-root restore, required artifact verification, source-process
  quarantine and retirement of historical authority/funding. No operational DB
  was migrated as part of qualification.
- **Manual limits:** agent-observed fixture UI/native Hypit checks are not human
  creative or listening approval for real product footage.

## All findings

| Finding | Primary implementation | Permanent regression evidence | Manual / process evidence | Remaining live qualification |
| --- | --- | --- | --- | --- |
| **R01** — Production reports successful rendering and delivery without doing either | `6628500 + S8` | [test_factory_application.py](../../tests/test_factory_application.py) + release drills | Actual loopback app/browser checks; short and long fixture receipts | One funded four-final production, human product/voice/creative review and real delivery |
| **R02** — Paid dispatch does not enforce the shared budget and authorization system | `1e3a31a + S8` | [test_factory_repairs_effects.py](../../tests/test_factory_repairs_effects.py) + release drills | No separate manual claim; permanent negative-probe regression and code inspection | Exact native account/route qualification and current scope before live effects |
| **R03** — Editing a quoted or authorized experiment preserves stale approval | `1e3a31a + S8` | [test_factory_repairs_effects.py](../../tests/test_factory_repairs_effects.py) | No separate manual claim; permanent negative-probe regression and code inspection | Exact native account/route qualification and current scope before live effects |
| **R04** — Canvas silently replaces the approved credit ceiling with a new quote | `474f676 + S8` | [test_factory_repairs_protocols.py](../../tests/test_factory_repairs_protocols.py) | No separate manual claim; permanent negative-probe regression and code inspection | Exact native account/route qualification and current scope before live effects |
| **R05** — Submission is not protected against repeated calls, and real restart recovery fails | `1e3a31a + S8` | [test_factory_repairs_effects.py](../../tests/test_factory_repairs_effects.py) + release drills | Actual OS worker deaths and six independent workers; automated durable fakes | Exact native account/route qualification and current scope before live effects |
| **R06** — Remote concurrency limits stop counting unfinished operations after lease expiry | `1e3a31a + S8` | [test_factory_repairs_effects.py](../../tests/test_factory_repairs_effects.py) + release drills | Actual OS worker deaths and six independent workers; automated durable fakes | Exact native account/route qualification and current scope before live effects |
| **R07** — Terminal failures, pause and manual recovery do not have working production transitions | `1e3a31a + S8` | [test_factory_repairs_effects.py](../../tests/test_factory_repairs_effects.py) + release drills | Actual OS worker deaths and six independent workers; automated durable fakes | Exact native account/route qualification and current scope before live effects |
| **R08** — Outlier baselines can use videos from different creators | `b23790b` | [test_factory_repairs_research.py](../../tests/test_factory_repairs_research.py) | No separate manual claim; permanent negative-probe regression and code inspection | Funded research route and observed creator-history coverage |
| **R09** — Vertex adapter does not match authentication or the successful pilot protocol | `474f676 + S8` | [test_factory_repairs_protocols.py](../../tests/test_factory_repairs_protocols.py) + release drills | No separate manual claim; permanent negative-probe regression and code inspection | Exact native account/route qualification and current scope before live effects |
| **R10** — Canvas adapter uses an incompatible CLI protocol and drops requested references | `474f676 + S8` | [test_factory_repairs_protocols.py](../../tests/test_factory_repairs_protocols.py) | No separate manual claim; permanent negative-probe regression and code inspection | Exact native account/route qualification and current scope before live effects |
| **R11** — Hypit build JSON is parsed incorrectly | `474f676 + S8` | [test_factory_repairs_protocols.py](../../tests/test_factory_repairs_protocols.py) | Installed Hypit 0.1.8 export, rich timeline and native Studio exercised in S3–S5 | None added by this repair; full operator/F-module sign-off remains separate |
| **R12** — There is no runnable application bootstrap/background worker; the documented startup fails | `6628500 + S8` | [test_factory_application.py](../../tests/test_factory_application.py) + release drills | Actual loopback app/browser checks; short and long fixture receipts | One funded four-final production, human product/voice/creative review and real delivery |
| **R13** — API success responses are placeholders rather than domain-service operations | `6628500 + S8` | [test_factory_application.py](../../tests/test_factory_application.py) + release drills | Actual loopback app/browser checks; short and long fixture receipts | One funded four-final production, human product/voice/creative review and real delivery |
| **R14** — The mounted dashboard remains an empty/demo shell | `6628500 + S8` | [test_factory_application.py](../../tests/test_factory_application.py) + release drills | Actual loopback app/browser checks; short and long fixture receipts | One funded four-final production, human product/voice/creative review and real delivery |
| **R15** — Acceptance and delivery can bypass required reviews and artifact ownership | `fc7fb75 + S8` | [test_factory_repairs_media.py](../../tests/test_factory_repairs_media.py) | Actual loopback app/browser checks; short and long fixture receipts | One funded four-final production, human product/voice/creative review and real delivery |
| **R16** — The real Google Drive CLI adapter cannot reliably verify the intended delivery | `474f676 + S8` | [test_factory_repairs_protocols.py](../../tests/test_factory_repairs_protocols.py) | No separate manual claim; permanent negative-probe regression and code inspection | Exact native account/route qualification and current scope before live effects |
| **R17** — Delivery retries can either fail on existing intent or create a duplicate upload | `6628500 + S8` | [test_factory_application.py](../../tests/test_factory_application.py) + release drills | Actual loopback app/browser checks; short and long fixture receipts | Exact native account/route qualification and current scope before live effects |
| **R18** — Shared-work deduplication can under-cover a longer shot and underquote it | `fc7fb75 + S8` | [test_factory_repairs_media.py](../../tests/test_factory_repairs_media.py) | No separate manual claim; permanent negative-probe regression and code inspection | Exact native account/route qualification and current scope before live effects |
| **R19** — Composition and rendering silently omit declared timeline decisions | `fc7fb75 + S8` | [test_factory_repairs_media.py](../../tests/test_factory_repairs_media.py) | Actual loopback app/browser checks; short and long fixture receipts | One funded four-final production, human product/voice/creative review and real delivery |
| **R20** — Speech fitting changes timestamps in the wrong direction and does not render fitted audio | `fc7fb75 + S8` | [test_factory_repairs_media.py](../../tests/test_factory_repairs_media.py) + release drills | No separate manual claim; permanent negative-probe regression and code inspection | One funded four-final production, human product/voice/creative review and real delivery |
| **R21** — The audio mixer does not enforce the frozen mix or exact duration | `fc7fb75 + S8` | [test_factory_repairs_media.py](../../tests/test_factory_repairs_media.py) | Actual loopback app/browser checks; short and long fixture receipts | One funded four-final production, human product/voice/creative review and real delivery |
| **R22** — Technical QC misses real freeze output and does not check all promised clocks | `fc7fb75 + S8` | [test_factory_repairs_media.py](../../tests/test_factory_repairs_media.py) | Actual loopback app/browser checks; short and long fixture receipts | One funded four-final production, human product/voice/creative review and real delivery |
| **R23** — Changed-region QC can pass absent evidence and misses changes outside its one sampled frame | `fc7fb75 + S8` | [test_factory_repairs_media.py](../../tests/test_factory_repairs_media.py) | Actual loopback app/browser checks; short and long fixture receipts | One funded four-final production, human product/voice/creative review and real delivery |
| **R24** — Closing previews and stopping services can leave processes alive or lose ownership | `6628500 + S8` | [test_factory_application.py](../../tests/test_factory_application.py) | Actual loopback app/browser checks; short and long fixture receipts | One funded four-final production, human product/voice/creative review and real delivery |
| **R25** — Backup/restore opens a different database and does not enforce reconciliation before dispatch | `006f274 + S8` | [test_factory_repairs_state.py](../../tests/test_factory_repairs_state.py) + release drills | Populated fresh-root restore/activation exercised; operational database untouched | None added by this repair; full operator/F-module sign-off remains separate |
| **R26** — Configuration and readiness reports do not reflect the running system | `6628500 + S8` | [test_factory_application.py](../../tests/test_factory_application.py) + release drills | No separate manual claim; permanent negative-probe regression and code inspection | None added by this repair; full operator/F-module sign-off remains separate |
| **R27** — Browser idempotency keys collide after refresh or in another tab | `6628500 + S8` | [test_factory_application.py](../../tests/test_factory_application.py) | Actual loopback app/browser checks; short and long fixture receipts | None added by this repair; full operator/F-module sign-off remains separate |
| **R28** — The SSE client never receives the named server events | `6628500 + S8` | [test_factory_application.py](../../tests/test_factory_application.py) | Actual loopback app/browser checks; short and long fixture receipts | None added by this repair; full operator/F-module sign-off remains separate |
| **R29** — Server idempotency persists too late and hashes file imports incompletely | `1e3a31a + S8` | [test_factory_repairs_effects.py](../../tests/test_factory_repairs_effects.py) + release drills | Actual loopback app/browser checks; short and long fixture receipts | None added by this repair; full operator/F-module sign-off remains separate |
| **R30** — Live Shopify import uses an invalid price selection and lacks media transport | `474f676 + S8` | [test_factory_repairs_protocols.py](../../tests/test_factory_repairs_protocols.py) + release drills | No separate manual claim; permanent negative-probe regression and code inspection | Exact native account/route qualification and current scope before live effects |
| **R31** — Source acquisition/research recovery relies on fake-style in-memory operations | `474f676 + S8` | [test_factory_repairs_protocols.py](../../tests/test_factory_repairs_protocols.py) + release drills | No separate manual claim; permanent negative-probe regression and code inspection | Exact native account/route qualification and current scope before live effects |
| **R32** — Publishing adapter does not implement the documented Upload Post protocol | `f282bce + S8` | [test_factory_repairs_learning.py](../../tests/test_factory_repairs_learning.py) | No separate manual claim; permanent negative-probe regression and code inspection | Authorized real posts/Reporting setup and actual 48h/7d/28d evidence |
| **R33** — Publication authorization is not bound to the exact final or destination | `f282bce + S8` | [test_factory_repairs_learning.py](../../tests/test_factory_repairs_learning.py) | No separate manual claim; permanent negative-probe regression and code inspection | Exact native account/route qualification and current scope before live effects |
| **R34** — YouTube thumbnail reach uses a nonexistent Reporting API query shape | `f282bce + S8` | [test_factory_repairs_learning.py](../../tests/test_factory_repairs_learning.py) + release drills | No separate manual claim; permanent negative-probe regression and code inspection | Authorized real posts/Reporting setup and actual 48h/7d/28d evidence |
| **R35** — Readback aggregation and coverage can produce misleading A/B results | `f282bce + S8` | [test_factory_repairs_learning.py](../../tests/test_factory_repairs_learning.py) | No separate manual claim; permanent negative-probe regression and code inspection | Authorized real posts/Reporting setup and actual 48h/7d/28d evidence |
| **R36** — Learning can declare winners on insufficient exposure and cannot follow real experiment identities | `f282bce + S8` | [test_factory_repairs_learning.py](../../tests/test_factory_repairs_learning.py) | No separate manual claim; permanent negative-probe regression and code inspection | Authorized real posts/Reporting setup and actual 48h/7d/28d evidence |
| **R37** — Revision handling overwrites history or fails across service boundaries | `006f274 + S8` | [test_factory_repairs_state.py](../../tests/test_factory_repairs_state.py) + [authoritative revision/API regressions](../../tests/test_factory_application.py) + release drills | Populated fresh-root restore/activation exercised; operational database untouched | None added by this repair; full operator/F-module sign-off remains separate |
| **R38** — Secret redaction is incomplete and bypassed by durable events | `6c0f33a + S8` | [test_factory_repairs_safety.py](../../tests/test_factory_repairs_safety.py) + release drills | No separate manual claim; permanent negative-probe regression and code inspection | Exact native account/route qualification and current scope before live effects |
| **R39** — The dev log and F34 evidence overstate end-to-end and crash qualification | `6c0f33a + S8` | [test_factory_repairs_release.py](../../tests/test_factory_repairs_release.py) and [QA regressions](../../tests/test_factory_qa.py) + release drills | No separate manual claim; permanent negative-probe regression and code inspection | None added by this repair; full operator/F-module sign-off remains separate |
| **R40** — The current backend suite fails because an approval test uses an expiring fixed date | `6c0f33a + S8` | [test_approval_gate.py](../../tests/test_approval_gate.py) | No separate manual claim; permanent negative-probe regression and code inspection | None added by this repair; full operator/F-module sign-off remains separate |
| **R41** — Provider routing does not enforce terminal fallback or qualified live modes | `1e3a31a + S8` | [test_factory_repairs_effects.py](../../tests/test_factory_repairs_effects.py) + release drills | No separate manual claim; permanent negative-probe regression and code inspection | Exact native account/route qualification and current scope before live effects |
| **R42** — Legacy analytics still turns missing reach/baseline into numeric decisions | `f282bce + S8` | [test_factory_repairs_learning.py](../../tests/test_factory_repairs_learning.py) | No separate manual claim; permanent negative-probe regression and code inspection | Authorized real posts/Reporting setup and actual 48h/7d/28d evidence |
| **R43** — Media routes load full files and blocking work into the API process | `6628500 + S8` | [test_factory_application.py](../../tests/test_factory_application.py) | Actual loopback app/browser checks; short and long fixture receipts | None added by this repair; full operator/F-module sign-off remains separate |

## Specific corrections from final integration

1. Immediately completed synchronous synthesis must retain `succeeded`, while
   publication `processing`/`scheduled` states must be translated into effect
   states without losing publication meaning. Full-suite tests caught both seams.
2. Distinct explicitly approved operations may legitimately have identical request
   bytes. Schema 10 retains logical-intent uniqueness, removes the overbroad
   request-hash uniqueness constraint, and preserves populated v7 content.
3. Zero-price account actions still need a reservation and settlement. A surprise
   charge is recorded as an overrun; zero-cost setup cannot mint spending capacity.
4. Synchronous recovery uses the attempt identity, not a hash that might match
   multiple separately approved operations. Reporting setup reconciles its exact
   requested name rather than accepting an unrelated account job.
5. Speech fitting is an actual worker command. Approval binds fitted audio;
   attachment creates a new revision and preserves existing treatment captions.
6. Source analysis quotes bind the registered seed/video/hash/model. The native
   inline-video protocol is exercised with actual local MP4 bytes at a fake
   transport; incomplete/malformed responses cannot silently become a blueprint.
7. Restore does not inherit ownership of original PIDs or recreate old budget
   headroom. Explicit current financial evidence is required before activation;
   new spending still needs new funding and new approvals.

## Reproduction and release boundary

Run `make test`, then the dashboard tests and production build. The operations
runbook gives isolated fixture API/worker commands and both exact frame lengths.
Evidence must be regenerated after material code/provider changes.

The factory module tracker intentionally retains outstanding full-checklist and
human sign-offs. The repair program does not silently sign F35 or any legacy
G-gate. Production enabling remains a separate account/model/input-mode decision
under a current recorded budget and authorization.
