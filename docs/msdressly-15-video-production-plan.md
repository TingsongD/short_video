# MsDressly: sequential 15-video production plan

Prepared 15 September 2026; implementation accepted 16 September 2026.
The reusable controller is now implemented in `modules/batch/`; live rollout
is recorded in `PROGRESS.md` and the batch's durable state. See
[operation and recovery](msdressly-batch-runner.md). Completion of the fifteen
videos remains subject to available credits and each delivery/cleanup gate.

## Outcome and limits

Produce the selected fifteen multi-product hauls in order, one complete video at
a time, using the existing Jimeng credit balance. Every video contains ten
selected products, with no product ID repeated across the batch or the preceding
haul. Keep the previous presenter-led try-on format and **169.7-second** working
duration, original product copy, ElevenLabs v3 Jessica narration, captions and
background music. Deliver a 1080×1920, 30fps MP4 assembled from 720p Jimeng footage.
The larger export does not add source detail.

The batch finishes when fifteen videos are delivered, or the remaining budget
cannot fund another complete video and its correction allowance. Preserve any
small unusable remainder; do not generate incomplete footage merely to reach zero.
Do not purchase credits or extend the batch into a future allowance automatically.

## Verified resources and realistic output count

| Resource | Verified snapshot / estimate |
|---|---|
| Jimeng available credits | **13,502**, read from the logged-in Chrome credit-details panel |
| Canvas CLI | 1.0.1; authenticated CN production account; Maestro membership |
| Current example quotes | Seedream 5.0 Pro 2K reference: **8 credits**; Seedance 2.0 Fast VIP 720p ten-second clip: **60 credits** |
| ElevenLabs included balance | **84,504** remaining; 5,496 used of 90,000; overages disabled |
| Local machine | 64 GiB RAM; approximately 188 GiB disk available; memory-pressure tool reported 69% free |
| Existing preview ports | 5184–5188 have no listeners |
| Delivery | Existing Drive folder access verified |

The diagnostic `dreamina user_credit` command returned zeros with an empty
account identity. That response is invalid balance evidence; the logged-in
credit-details panel supplies the planning balance. The native Canvas account
command confirms membership but does not expose the balance in this release.
Refresh the browser balance and native quotes before production and between
videos. No cookie extraction or private endpoint calls are needed.

Example quotes above are fresh reads of existing drafts, not quotes for the new
fifteen videos. Every new shot must receive its own native quote before submission.

The completed haul used 178 generated seconds for a 169.7-second edit. At the
verified example rates, an equivalent new haul has this planning budget:

| Component | Estimated Jimeng credits |
|---|---:|
| Ten outfit-reference images | 80 |
| Approximately 178 seconds of generated footage | 1,068 |
| Base production | **1,148** |
| Correction allowance | **200** |
| Initial reservation per video | **1,348** |

The previous commission reserved 1,348 credits including rejected work and
replacements. This is reservation evidence, not an independently audited billing
statement. Expect **about 10–11 complete videos** from 13,502 credits at this
length and quality. Fifteen equivalents would require approximately
**17,220–20,220 credits** at these rates. Actual duration rounding, quotes and
corrections decide the final count. Do not silently shorten the videos or switch
models to force all fifteen into the balance.

### Separate audio budget

- Plan for up to **4,000 included ElevenLabs credits per video**, **60,000 for
  the batch**, fitting within the verified balance. This is the proposed new
  batch narration ceiling; the preceding commission's 4,000-credit authorization
  is not a reusable allowance. Reserve actual billable text before each request.
- Retain Jessica / `eleven_v3` and use returned alignment information. Rewrite
  copy before synthesis to fit the character and timing limits; reuse accepted
  speech in subsequent edits.
- Reuse the accepted original Lyria instrumental and fit/mix it locally. Planned
  additional music and analysis API spending: **US$0**.
- Use local technical checks plus agent visual/listening review. Project Python
  currently has no Whisper, Faster Whisper or WhisperX. Do not promise automated
  local transcription until it is installed and verified. If paid transcription
  or model review is needed, establish a separate allowance first. Do not reuse
  the exhausted US$1 budget from the previous commission.

## Queue order

Each row contains ten products. Full item identities, product links, prices,
sales evidence and reference-image notes are in
[the product plan](../data/production/next-15-video-plan-20260915/NEXT-15-VIDEOS.md).

| Video | Theme |
|---|---|
| 01 | Checks and statement denim |
| 02 | Matching sets and sporty weekends |
| 03 | Blue-and-white everyday outfits |
| 04 | Sparkle and night-out outfits |
| 05 | Wedding guest and special occasions |
| 06 | Florals and boho textures |
| 07 | Polished work-to-dinner wardrobe |
| 08 | Western details and playful prints |
| 09 | Animal-print outfit refresh |
| 10 | Cozy autumn lounge |
| 11 | Statement jackets and autumn layers |
| 12 | Easy dresses and one-piece outfits |
| 13 | Colorful casual wardrobe |
| 14 | Americana and graphic casuals |
| 15 | Date-night textures and soft layers |

The numbers define queue order, not a guarantee that every row is funded.
The remainder stays queued when the stopping rule applies.

## Before starting the batch

1. Turn the preceding haul's working production scripts into a reusable batch
   runner. They currently contain commission-specific product names, paths and
   ceilings; they are not a ready-made fifteen-video automation.
2. Use the saved version-2 selection as immutable input. Create an isolated
   production directory and one Canvas project per video. Preserve the original
   commission and frozen pipeline schemas/fixtures.
3. Add a batch lock so only one controller can spend or render. Persist the queue,
   approved budgets, job identities, quotes, selected resources and delivery
   receipts atomically. Secrets and confirmation tokens remain outside state.
4. Add a shared credit ledger for this batch and a separate narration ledger.
   Record the initial 13,502-credit cap; live balance decreases reduce what can be
   spent, while later top-ups or resets do not increase this cap automatically.
5. Build Drive verification and process cleanup into completion, including
   failure paths. Validate with offline tests and a zero-generation dry run that
   reuses the already delivered final and receipt without making another upload.
6. Confirm the proposed batch audio budget as part of the execution agreement;
   account availability alone is not spending authorization. Jimeng's full
   available-balance policy and Drive/cleanup instructions are already specified
   by the user; do not ask again for those routine steps.

## The loop for every video

### 1. Preflight and prepare

- Recheck native login, membership, live model capabilities, balance, Drive
  access, disk space and memory pressure. Refresh credentials through their
  supported flow if needed; a saved job survives an expired login.
- Recheck the ten Shopify products and select available variants. Resolve saved
  title/image discrepancies before generation. Download matching reference
  angles rather than inventing garment construction.
- Write new copy around an opening hook, ten product reveals and a closing CTA.
  Use the previous video as a pacing/format reference. Reuse the accepted
  fictional presenter identity and room, with the new products. Do not feed the
  original source presenter or source captions into generation again.
- Prepare duration-limited shots; current Seedance 2.0 Fast VIP supports 4–15
  seconds in one-second steps. Plan adequate footage for the complete narration.

### 2. Quote and reserve a complete video

- Save the intended Canvas drafts and obtain per-item quotes. All required
  items must be quotable; a partial quote cannot authorize a full batch.
- Reserve the entire video's quoted requirement plus the 200-credit correction
  allowance before the first Jimeng generation. Check both the remaining batch
  ceiling and the current usable account balance.
- If it does not fit, stop with the next video queued and report the remainder.
  Do not spend on only the first few products of an unfunded video.
- Present the quotes in the production progress record and enforce exact native
  ceilings. The batch's approved cap governs execution; no repeated routine
  approval prompts when quotes stay inside the accepted scope.

### 3. Produce narration and references

- Generate new ElevenLabs v3 speech in recoverable segments, within the accepted
  narration ceiling. Validate spoken copy, pronunciation, pauses and duration.
- Finalize shot timing against measured narration and refresh any affected
  Jimeng quotes before submitting visual generation. Any larger reservation
  must still fit the batch limit.
- Generate ten outfit references sequentially with Seedream 5.0 Pro at 2K.
  Inspect garment identity, presenter consistency, framing and readable text
  before generating the associated footage. Reuse a valid result on resume.

### 4. Generate footage one job at a time

- Use official Canvas CLI, `seedance_2.0_fast_vip`, 720p, 9:16, one result per
  shot. Keep **one video and one Jimeng generation active at a time**.
- Save node and submission IDs before each request. Wait for the same job,
  download through the CLI, verify media and preserve checksums/provenance.
- Keep accepted, running, failed, unknown and downloaded states distinct.
  A timeout or lost response triggers read-only status/recovery using the same
  submission identity, never another paid submission.
- Correct locally when possible. For confirmed defective results, allow at most
  one replacement per shot, at most two video replacements and two reference
  replacements per video, all within the reserved 200-credit allowance. Every
  replacement gets its own recorded quote and intentional new identity. If this
  is insufficient, pause at the affected video with its usable work preserved.

### 5. Assemble and inspect the actual final

- Use the repaired Hypit launcher and local rendering. Keep one render worker
  active; render sections sequentially and join with FFmpeg where appropriate.
  Start a preview server only when review needs it.
- Preserve shot/product order and fitted timing. Use the accepted narration as
  the soundtrack, duck the reused music under speech, and discard unwanted
  generated speech/music. Check visible speaking against the intended words;
  use deliberate product detail cutaways where they serve the edit.
- Use the corrected named-entity caption serializer. Compare parsed caption
  strings with the intended text and inspect the rendered caption states,
  including apostrophes, ampersands, timing, line wrapping and placement.
- Require complete ten-product coverage, matching garment details, consistent
  presenter, clean cuts, lip-sync review, intelligible narration, readable
  captions, correct duration and orientation, full decode, no unexplained black
  intervals and no audio clipping. At 30fps, the 169.7-second picture contains
  5,091 frames; account for normal audio/container padding separately.
- Review the actual exported file, not only the timeline or a model's summary.
  The preceding model review missed the caption bug, so it cannot replace direct
  caption and frame checks. Record any limitation honestly.

### 6. Upload and verify Google Drive delivery

- Name the final descriptively, for example
  `MsDressly_Haul-01_Checks-Statement-Denim_10-Products_2m49s_v1.mp4`.
- Upload to the authorized
  [Short Form AI YouTube folder](https://drive.google.com/drive/folders/1XQU20m_xk5030kAxbbIumeHYkrRPkPbs).
  Check existing receipts and destination files first; reuse an identical
  verified upload rather than duplicating it.
- Verify remote folder, filename, byte size and MD5 against the local export.
  Save the Drive ID/link, local SHA-256 and verification receipt.
- If an upload response is ambiguous, reconcile remote state before retrying.
  A completed local export alone does not pass this stage.

### 7. Stop processes, release ports and reclaim working memory

- Stop that video's Hypit preview/runtime, rendering/capture browser workers,
  FFmpeg processes and descendants. Identify ownership from the recorded
  process tree, working directory and command; stop gracefully first, then
  terminate only confirmed survivors.
- Close only disposable browser tabs created for this video's review. Preserve
  the user's logged-in Chrome session and unrelated applications/services.
- Confirm every recorded process is gone and every port it used has no
  listener. Save before/after process memory and system memory-pressure readings
  in a cleanup receipt. The OS reclaims process memory; filesystem caches may
  remain reclaimable, so a particular system-wide free-RAM number is not promised.
- Keep final files, source media, project files, credentials and recovery state.
  Do not run a system-wide kill or force-purge memory caches.
- Require acceptable memory pressure and at least 25 GiB available disk before
  the next video. Pause if resources have not recovered rather than stacking
  another worker on top of the problem.

### 8. Complete, report and advance

Mark the video `done` only after **QC + verified upload + verified cleanup**.
Report its Drive link, conservative credit use, remaining balance and next item.
Release unused correction reservations; keep charged/ambiguous reservations
until settlement or refund is established. Recheck the balance, then start the
next video through the same loop.

If upload fails, still clean up idle video processes in a `finally` path, retain
the final and pause the batch at delivery. Retry delivery/recovery without
regenerating the video. Never advance while delivery or cleanup is unresolved.

## Recovery and implementation acceptance

Suggested durable state progression:

```text
queued → prepared → quoted → reserved → narration_ready → references_ready
       → footage_ready → rendered → qc_passed → upload_verified
       → cleanup_verified → done
```

The journal must also represent running/unknown generation, credit shortage,
authentication needed, QC failure, delivery pending and cleanup pending. On
restart, inspect saved identities and verified artifacts and continue the
incomplete stage. Never replay a completed paid stage automatically.

Offline checks required before enabling the runner:

- Refuse a second batch controller or overlapping video/shot submission.
- Stop before insufficient complete-video funding; enforce Jimeng and TTS caps
  independently, including replacements and ambiguous charges.
- Resume interrupted submissions/downloads without duplicate generation.
- Prevent advancement after failed QC, checksum mismatch, ambiguous upload,
  surviving child process, occupied port or unacceptable memory pressure.
- Run cleanup after both successful and failed uploads; never kill unrelated
  processes or remove retained artifacts.
- Preserve ten-product ordering, measured speech timing and exact caption text.
- Run the full offline test suite after implementation; current prior baseline
  is 301 passing tests. This planning turn changes no application code.

## Saved planning artifacts

- `data/production/next-15-video-plan-20260915/batch-plan/batch-queue.json`:
  fifteen queued videos, product IDs, limits and completion gates. It is a plan,
  not a background worker or active automation.
- `data/production/next-15-video-plan-20260915/batch-plan/preflight-evidence.json`:
  sanitized account, quote, delivery and machine snapshots.
- [Existing Drive completion procedure](google-drive-uploads.md#required-completion-workflow).
- [Existing Jimeng/Hypit workflow](jimeng-hypit-workflow.md).
- [ElevenLabs subscription endpoint](https://elevenlabs.io/docs/api-reference/user/subscription/get),
  used for the read-only included-credit check.
