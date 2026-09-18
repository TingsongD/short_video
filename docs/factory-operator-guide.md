# Viral Video Factory — Operator Guide

A plain-language guide to producing reviewed, deliverable short-form
video variants with the factory dashboard. No programming knowledge
needed for the normal workflow.

> **What it does, in one sentence:** you give it a reference video and
> your own footage/audio/images, it plans four variations, quotes the
> cost before spending anything, renders them, asks you to review the
> results, and delivers the approved files to Google Drive.

---

## 1. Starting the system

Two things run on your computer: the **brain** (API, which also serves
the dashboard) and the **worker** (does the actual jobs).

```bash
# Terminal 1 — the API + dashboard (leave running)
cd "/Users/tingsongdai/Kimi-cursor/Short Form AI YouTube"
.venv/bin/python -m modules.factory.cli serve --port 8100

# Terminal 2 — the worker (leave running)
cd "/Users/tingsongdai/Kimi-cursor/Short Form AI YouTube"
.venv/bin/python -m modules.factory.cli worker
```

Then open **http://127.0.0.1:8100** in your browser. The API serves the
dashboard page itself, so buttons and uploads work on the same origin.

> If the dashboard page ever looks stale or missing, rebuild it once:
> `cd apps/factory-dashboard && npm run build`, then refresh.
> (`npm run dev` on port 5180 is only for developers editing the
> frontend — the production path is always the built page on 8100.)

The top of the page shows the mode. `Mode: live` means configured
routes call real provider accounts — quoted credits are actually
charged once you approve a quote. `Mode: offline` would mean local
test doubles and zero real spend. Check the Providers tab for which
routes are currently qualified.

> **First thing every session:** type your name in the **Reviewer**
> box at the top. The system refuses approvals without a reviewer name —
> that's the audit trail for who approved what.

## 2. The golden path (a complete production run)

Work left to right through the tabs.

### Step 1 — Seeds: give it a reference and your media

1. Paste a YouTube-style link in **Source video link** → **Add source**.
2. Import your own files with **Import footage, narration or music**
   (video, audio, and images are all accepted).
3. Pick your source in the **Source** dropdown → **Attach imported
   source video**.
4. Paste the timing/transcript observations into the big text box →
   **Analyze imported observations**.

   > ⚠️ This box expects a specific JSON shape (`{"beats":[...],
   > "transcript":[...], "music":{...}}`). Ask whoever set up the system
   > for a filled-in example you can copy and tweak. These notes are
   > **preliminary evidence only** — they cannot qualify the source for
   > production on their own.

### Step 1b — Analysis: prove you understood the reference (required)

Open the **Analysis** tab, pick the same source, and press **Run deep
analysis**. The worker gathers verified facts about the file itself
(size, duration, frame rate, audio), word-timed transcript evidence
(when a speech-alignment service is configured), shot boundaries, and
frame grids covering the whole video. It writes the project documents
(Analysis, Timeline, Brief, Treatment, Progress) under
`data/factory/analysis-projects/<seed>/`.

Then fill in three forms — plain language, no JSON:

1. **Understanding** — premise, progression, hook, setups, payoffs,
   ending, replay appeal, intended response. Keep *observed facts*
   (what you literally see/hear) separate from *interpretation* (what
   you think it means), and write down what's uncertain.
2. **Timeline** — named sections covering the whole video, with
   start/end times that match the frame grids.
3. **Treatment** — what the new video preserves from the source, what
   it redesigns, and the script/production direction.

Finally **Mark analysis complete**. From then on:

- **Accept source timing** on the Seeds tab works — the approval is
  bound to the exact file bytes *and* this analysis revision.
- If the source file changes, or anyone edits the analysis afterwards,
  downstream approvals go **stale** and you'll be asked to re-review
  and re-accept — by design, not a bug.

> If the analysis shows **blocked**: the box names the problem and the
> recovery action. The common one is *transcript unavailable* — the
> source has speech but no word-alignment service is configured. Your
> options are right there in the tab: import an aligned transcript
> (paste word-timed output from your own tool, with provider and
> provenance filled in), or **declare the source non-verbal** with a
> short justification (music-only, silent). YouTube's automatic
> captions are kept as preliminary evidence — they never count as
> verified word timing.
>
> An imported transcript must carry **word-level** times, not just
> lines or segments: each entry needs the word plus its start and end
> in seconds (`{"word": "…", "start_s": 0.0, "end_s": 0.4}`), in order
> and inside the source duration. Provider and provenance are
> mandatory — say what produced it (e.g. "faster-whisper small.en,
> local inference") so the evidence stays auditable. After a successful
> import, re-run the analysis and the picture grids regenerate linked
> to your words.

Then continue on the Seeds tab: check the extracted beats → **Accept
source timing** → **Prepare four variants**.

### Step 2 — Plan: review the plan, get a price, approve it

1. On the **Plan** tab, pick your experiment in the **Experiment**
   dropdown at the very top of the page.
2. The draft plan is editable JSON — the four variants' copy, regions
   and declared changes. Edit it, or **Load current draft** → tweak →
   **Save revised draft** (makes a new revision; quotes are per-revision).
3. **Prepare current quote** — the system prices every operation and
   shows the totals (credits and/or cost). Nothing has been spent yet.
4. Approve the quote in the **generation approval** box — pick the
   budget and confirm. Only now is work authorized.
5. **Start / recover this revision** — production is queued. The same
   button safely resumes an interrupted run; it never duplicates paid
   work already done.

### Step 3 — Queue: watch it work

Every job shows a state:

| State | Meaning |
|---|---|
| `queued` | waiting for a dependency or a worker slot |
| `running` | in progress |
| `blocked` | needs you — a review, a failure, or operator input |
| `done` | finished |

Failed jobs can be **retried** (local work) or **reconciled** (the
system checks what the remote provider actually did before deciding —
it will never blindly re-charge a paid operation). **Pause/Resume**
controls the whole experiment.

### Step 4 — Reviews: look at everything before approving

Two kinds of review, both required:

- **Asset review** — watch each imported/generated picture asset, then
  **Accept this asset for this plan**.
- **Creative review** — watch each finished variant on the **Reviews**
  tab and give it a verdict (accept/reject + optional note). Automated
  technical checks (frozen frames, black sections, audio levels,
  narration coverage) run on their own; a deliberate still image is
  fine — it won't be flagged as a freeze.

> Your verdict binds to the exact file bytes. If the video changes, the
> old approval no longer applies — you'll be asked to re-review.

### Step 5 — Delivery: send approved finals to Drive

1. On **Delivery**, enter the configured Drive **folder** and
   **account**.
2. **Authorize delivery of A/B/C/D** for each variant you approved.
3. The system uploads the exact reviewed file, verifies the remote
   copy byte-for-byte, and shows the Drive link and cleanup state.
4. If a delivery fails before upload, re-authorizing retries the
   *transfer only* — it never re-renders or re-charges.

### Step 6 — Compare & Studio (optional polish)

- **Compare** shows the four variants side by side.
- **Studio** opens a contained editing workspace on a rendered variant
  for marking changes at a time offset. Saving a proposed change does
  **not** start any generation — it creates a reviewed suggestion.

### Step 7 — Publish, measure, learn (Publishing + Learning tabs)

This stage is offline-capable and gated: nothing posts anywhere until
you explicitly authorize each destination.

1. **Freeze the decision policy first** (Learning tab). The policy —
   metric, horizon, minimum exposure, guardrails, and the seed-selection
   weights — is frozen *before* any publication for that experiment.
   A policy that asks for a reporting window a destination can't supply
   is refused at freeze time (`window_capability_missing`), never
   discovered unusable later.
2. **Prepare metadata** (Publishing tab). Create a metadata package per
   variant + platform, pick/edit a candidate, answer the disclosure
   questions, then **Freeze** it. Publication planning binds only frozen
   packages and refuses a package whose final hash no longer matches
   (`metadata_stale`) — plan again after re-freezing.
3. **Plan destinations.** *Plan publications* creates one durable
   intent per variant × destination — up to sixteen independent slots.
   Slots that fail validation are listed as errors; the rest still plan.
   Frozen packages are attached automatically when present.
4. **Authorize each slot.** Every destination post needs its own
   authorization bound to the exact final bytes. *Run* enqueues the
   durable publish job; the worker posts, observes the provider state,
   and records remote identity + actual publish time. A provider
   `scheduled` response is not the end — a durable observe job polls
   the remote job until it goes public (bounded to 24h past its
   instant), and only the verified public transition schedules
   checkpoints.
5. **Watch checkpoints.** When a post goes public, readback checkpoints
   (24h, 48h, 72h, 7d, 28d — plus 7d_complete / 28d_complete
   source-reporting-day windows on platforms with a qualified
   source-calendar route, currently YouTube) are scheduled
   automatically and collected when due. A pending, partial or failed
   pull retries automatically with bounded backoff and exhausts to an
   honest `failed` label — it is never reported collected. A lifetime
   observation taken materially late (>25% past the requested age) is
   labeled `late` and cannot satisfy the earlier checkpoint.
   *Enqueue readback* forces a manual pull for a due horizon.

   Checkpoint labels, honestly: `pending` (waiting for its instant) →
   `due` → `retrying` (the pull returned incomplete data — it keeps
   retrying with backoff) → `collected` (a complete snapshot landed)
   or `failed` (retries exhausted). `late` means data arrived but past
   the honest window; `missed` means it never will — neither is
   treated as usable evidence for that checkpoint.
6. **Read decisions and select the seed** (Learning tab). Decisions run
   per platform against the frozen policy; *Select seed* ranks all four
   variants (A can win) using the frozen seed policy and stores the
   evaluation. A variant that fails its minimum exposure or guardrails
   on any required platform is disqualified from winning — its rank is
   still recorded as evidence. A champion selection is provisional at
   24h and can be revised when mature evidence lands — the selection
   record versions by horizon + evidence hash, and a revised winner
   marks an already-proposed child's basis superseded (never silently
   replaced).

   Selection outcomes: `champion` (a challenger wins), `retain_control`
   (A keeps the crown — including when challengers fail the margin or
   improvement rule), `inconclusive` (a tie or an unsafe/under-exposed
   control — nobody wins), `waiting` (required evidence hasn't
   arrived — come back later).
7. **Propose the next round.** Freeze a loop policy on the series
   (Learning tab → Loop — a fresh series works too; the id derives
   from the experiment's seed group, or type one manually), then
   *Propose next round* on the experiment. The winner's accepted local
   master is attached as the child seed's source media and the
   proposal reports `media_ready`; if no accepted artifact exists the
   proposal says `no_winner_artifact` and the child stays honestly
   unready — never faked. Re-proposing the same selection is
   idempotent — one active child per parent, even at the round limit.
8. **Pause vs cancel.** *Pause* stops new local work only — posts
   already scheduled with the provider still go live; the UI says so.
   Pause also holds queued dispatch: an already-queued publish job
   waits (resumable), while a cancelled/expired loop or a provider/
   account outside the policy's allow-lists is blocked outright.
   *Cancel series* asks the provider to cancel each scheduled job and
   reports per-job outcomes (`cancelled`, `already_public`,
   `cancel_failed`, `unknown`). A post that went live is never
   reported cancelled.

## 3. The other tabs, briefly

| Tab | What it's for |
|---|---|
| **Providers** | Readiness checklist per generation/audio route (installed → authenticated → tested → qualified). **Re-check readiness** refreshes on demand — it no longer re-runs constantly in the background. |
| **Products** | Product snapshots pulled for claims/packaging evidence. Authorization always validates the *pinned* snapshot revision from the plan — a later refresh can't quietly change approved facts. |
| **Budgets** | Credit/USD ceilings with reserved / used / **unknown** columns. Unknown charges are shown honestly — never silently treated as zero. |
| **Research** | Trend discovery plans. Identical searches hit the durable cache instead of re-charging; coverage reports real provider calls. |
| **Analysis** | The mandatory deep-analysis workspace described in Step 1b — staged evidence, understanding/timeline/treatment forms, review and recovery actions. |
| **Audio** | Speech fitting and attach. |
| **Publishing** | Destination matrix, metadata packages, per-slot authorize/run/cancel-remote, checkpoint readbacks — the Step-7 workflow. |
| **Learning** | Policy freeze, per-platform decisions, seed selection, round lineage, loop policy — the Step-7 workflow. |

## 4. Safety rules the system enforces for you

- **Nothing spends money before a quoted plan is authorized.** Every
  operation is priced first; authorization binds the exact plan.
- **Your approvals bind to exact bytes.** Change the file and the
  approval expires — you'll re-review.
- **Ambiguous never means failed or retried.** If the system can't tell
  whether a paid operation went through, it reconciles remotely first —
  it never blindly resubmits paid work.
- **Withdrawn approval stops publication.** If you fail a creative
  review after queueing a publication, the queued job is blocked — it
  cannot slip through.
- **Speech must match the script.** If copy changed, stale narration /
  captions / lip-sync footage are flagged instead of silently reused.
- **Publishing is gated.** Posting publicly requires its own explicit
  authorization and verified delivery; it can't happen by accident.
- **No production without understood references.** A blueprint can only
  be accepted after a reviewed deep analysis of the exact source bytes;
  quoting, authorizing, starting or recovering production all re-check
  that binding. Editing the analysis afterwards stales the approval
  until you re-review and re-accept.
- **Late evidence can't win an earlier checkpoint.** A metric snapshot
  taken materially after its checkpoint age is labeled late and
  excluded from that evaluation — a number measured at 28 days never
  answers "how did it do at 48 hours".
- **A refused cancellation is never reported as cancelled.** If the
  provider declines or can't be confirmed, the outcome says
  `cancel_failed` or `unknown` — a scheduled post you didn't stop
  will still go live, and the UI tells you.
- **Under-exposed variants can't win.** A challenger below the frozen
  minimum exposure or failing a guardrail on any required platform is
  disqualified — a tiny sample can't crown a champion.

## 5. When something goes wrong

| Symptom | What to do |
|---|---|
| Job `failed` in Queue | Open the job — the error field says why. Use **Retry** for local failures, **Reconcile** when a remote operation might have succeeded. |
| `blocked` jobs | Usually waiting on a review or a delivery authorization — check Reviews and Delivery. |
| "Accept source timing" refuses with *analysis required / incomplete / blocked* | The deep analysis on the Analysis tab isn't finished or hit a blocker — open it, finish the forms or resolve the blocking item, then mark it complete. |
| Buttons refuse with *analysis stale* | The source file changed, or the analysis was edited after approval. Re-run/re-review the analysis, then re-accept the blueprint — stale approvals can never slip through. |
| Provider not ready | Providers tab → **Re-check readiness** → the operator-language hint says what to fix (reconnect, set budget, qualify). |
| Dashboard looks stale | The page refreshes itself every few seconds; provider readiness loads once — use **Re-check readiness** to force it. |
| Something feels lost after a crash | Close the browser worry-free — jobs are durable on disk. Restart the API/worker and press **Start / recover this revision**. |
| `loop_paused` on a publish | The series loop is paused — queued work waits safely. Resume the series on the Learning tab; nothing is lost. |
| `cancel_failed` / `unknown` after cancel | The provider refused or didn't confirm — the post may still go live. Check the remote job on the provider's side before assuming it's stopped. |
| Proposal says `no_winner_artifact` | The champion has no accepted local master file — import or attach the reviewed final, then re-propose (it's idempotent). |
| Selection stuck on `waiting` | Required checkpoint data hasn't arrived — check the checkpoint labels on the Publishing tab; a `retrying`/`late`/`missed` label says why. |

## 6. Honest limitations (as of 2026-09-18)

- Two spots still involve JSON-ish input: the observations box (Step 1,
  preliminary only) and the experiment plan draft (Step 2). The deep
  analysis itself is now plain-language forms.
- Word-level transcript alignment runs through the local WhisperX
  endpoint (`whisperx.local`, model `small` on CPU — free, offline,
  no provider charge). Spoken sources align automatically during
  analysis. If the service is ever down or this runs on a machine
  without it, spoken sources stay blocked on the transcript step;
  importing an aligned transcript or declaring the source non-verbal
  are the supported recoveries.
- Non-YouTube metrics come from the publisher's cached analytics —
  captured-at-age counters, not source-reporting-day windows. Field
  names are provisional until live-qualified; cross-platform weights
  are policy choices, not platform-truth. YouTube collects
  shares and engaged-views (used to weight average watch metrics),
  but none of it is live-qualified yet.
- Publishing spends nothing without per-destination authorization, but
  live provider qualification and real analytics readback are still
  gated off until separately authorized and tested against live
  accounts.
- Generated music and some reference modes are optional routes that may
  show "unavailable" — that's intentional, not a bug.

---

*Questions or stuck states: `docs/factory-reports/REPAIRS.md` is the
engineering ledger; this guide covers operator use only.*
