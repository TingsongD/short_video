# Haul 01 timing analysis

All completion times use Vancouver time (PDT). Work began September 15 and finished September 16, 2026. This covers the first ten-product video, including initial implementation.

## Major completion milestones

| Step | Phase | Start | Completed | Elapsed |
|---|---|---|---|---|
| 1 | Implementation, product preparation and preflight before narration | Sep 15 23:30:29 | Sep 16 00:07:07 | 36m 38s |
| 2 | Narration generation, pause trimming and timing fit | Sep 16 00:07:07 | Sep 16 00:13:25 | 06m 18s |
| 3 | Final quotes and product/narration sign-off | Sep 16 00:13:25 | Sep 16 00:15:28 | 02m 04s |
| 4 | 11 outfit images + 20 clips: generation, recovery, review and edits | Sep 16 00:15:28 | Sep 16 06:46:58 | 6h 31m 29s |
| 5 | Render preparation | Sep 16 06:46:58 | Sep 16 06:47:16 | 00m 18s |
| 6 | 20 captioned sections rendered sequentially | Sep 16 06:47:16 | Sep 16 07:18:30 | 31m 14s |
| 7 | Final join, timing bug fix and technical verification | Sep 16 07:18:30 | Sep 16 07:22:25 | 03m 56s |
| 8 | Remaining final audio/picture QC and sign-off | Sep 16 07:22:25 | Sep 16 07:25:26 | 03m 01s |
| 9 | Drive lookup/upload/checksum verification | Sep 16 07:25:26 | Sep 16 07:25:33 | 00m 07s |
| 10 | Post-upload cleanup | Sep 16 07:25:33 | Sep 16 07:25:35 | 00m 02s |

**Total: 7h 55m 07s.** The visual generation/review phase accounts for 82.4% of wall time.

## Where visual-production time went

| Non-overlapping category within visual phase | Elapsed |
|---|---|
| 20 clips: submission to local download | 1h 42m 20s |
| 11 outfit images: submission to local download | 11m 28s |
| Downloaded assets waiting with no agent turn active | 3h 04m 17s |
| Post-download review/edit elapsed time while agent active | 1h 19m 52s |
| Between-job setup, imports, quotes and other orchestration | 13m 33s |

The prior report counted 17 downloads that occurred while the agent was absent (173.91 minutes). This fuller interval analysis also counts waiting after clip 01 downloaded during an active turn and that turn subsequently ended. The total post-download wait with no active agent is about 184.28 minutes. These figures overlap and must not be added.

## Twenty speaking clips

| Clip | Submitted | Downloaded | Review complete | Submit→download | Download→review | Inactive after download |
|---|---|---|---|---|---|---|
| clip-01 | 00:17:12 | 00:21:21 | 00:39:43 | 04m 08s | 18m 22s | 10m 22s |
| clip-02 | 00:39:57 | 00:47:21 | 01:05:28 | 07m 24s | 18m 07s | 10m 30s |
| clip-03 | 01:07:22 | 01:11:35 | 01:23:55 | 04m 13s | 12m 20s | 10m 16s |
| clip-04 | 01:24:10 | 01:28:12 | 01:39:56 | 04m 02s | 11m 44s | 10m 09s |
| clip-05 | 01:42:12 | 01:52:20 | 02:06:08 | 10m 08s | 13m 49s | 10m 02s |
| clip-06 | 02:08:45 | 02:14:27 | 02:27:23 | 05m 41s | 12m 57s | 10m 25s |
| clip-07 | 02:29:23 | 02:33:17 | 02:45:20 | 03m 54s | 12m 04s | 10m 04s |
| clip-08 | 02:45:36 | 02:49:15 | 03:01:40 | 03m 40s | 12m 25s | 10m 06s |
| clip-09 | 03:03:21 | 03:06:07 | 03:19:26 | 02m 45s | 13m 19s | 10m 15s |
| clip-10 | 03:19:43 | 03:23:06 | 03:39:28 | 03m 23s | 16m 23s | 10m 16s |
| clip-11 | 03:41:00 | 03:43:43 | 03:57:27 | 02m 43s | 13m 44s | 10m 09s |
| clip-12 | 03:57:41 | 04:01:11 | 04:13:36 | 03m 30s | 12m 25s | 10m 11s |
| clip-13 | 04:17:20 | 04:20:28 | 04:32:32 | 03m 08s | 12m 04s | 10m 24s |
| clip-14 | 04:32:48 | 04:46:04 | 04:50:34 | 13m 16s | 04m 30s | 00m 00s |
| clip-15 | 04:54:59 | 04:57:26 | 05:09:58 | 02m 27s | 12m 32s | 10m 26s |
| clip-16 | 05:10:15 | 05:13:36 | 05:27:33 | 03m 21s | 13m 57s | 10m 16s |
| clip-17 | 05:30:46 | 05:34:20 | 05:49:56 | 03m 34s | 15m 36s | 10m 02s |
| clip-18 | 05:50:13 | 05:53:38 | 06:05:34 | 03m 25s | 11m 56s | 10m 14s |
| clip-19 | 06:10:20 | 06:13:11 | 06:27:53 | 02m 51s | 14m 42s | 10m 11s |
| clip-20 | 06:28:12 | 06:42:58 | 06:46:58 | 14m 46s | 03m 59s | 00m 00s |

## Outfit references

| Reference | Submitted | Downloaded | Review complete | Total | Verdict |
|---|---|---|---|---|---|
| look-01 | 00:15:28 | 00:16:35 | 00:16:56 | 01m 28s | passed |
| look-02 | 01:05:34 | 01:06:41 | 01:07:07 | 01m 33s | passed |
| look-03 | 01:40:03 | 01:41:14 | 01:41:58 | 01m 55s | passed |
| look-04 | 02:27:31 | 02:28:38 | 02:29:08 | 01m 37s | passed |
| look-05 | 03:01:47 | 03:02:42 | 03:03:07 | 01m 19s | passed |
| look-06 | 03:39:35 | 03:40:27 | 03:40:46 | 01m 11s | passed |
| look-07 | 04:15:30 | 04:16:29 | 04:17:05 | 01m 35s | passed |
| look-08 | 04:50:42 | 04:51:38 | 04:52:00 | 01m 19s | passed |
| look-09 | 05:27:40 | 05:28:50 | 05:30:31 | 02m 51s | passed |
| look-10 | 06:05:43 | 06:06:38 | 06:07:39 | 01m 56s | failed |
| look-10-repair-01 | 06:08:05 | 06:09:13 | 06:10:02 | 01m 57s | passed |

## Render sections

| Section | Start | Verified complete | Elapsed |
|---|---|---|---|
| clip-01 | 06:47:16 | 06:48:41 | 01m 25s |
| clip-02 | 06:48:46 | 06:50:00 | 01m 14s |
| clip-03 | 06:50:06 | 06:51:31 | 01m 25s |
| clip-04 | 06:51:37 | 06:52:40 | 01m 03s |
| clip-05 | 06:52:45 | 06:54:11 | 01m 25s |
| clip-06 | 06:54:16 | 06:55:43 | 01m 27s |
| clip-07 | 06:55:50 | 06:57:18 | 01m 28s |
| clip-08 | 06:57:24 | 06:58:27 | 01m 03s |
| clip-09 | 06:58:33 | 07:00:01 | 01m 28s |
| clip-10 | 07:00:08 | 07:01:24 | 01m 17s |
| clip-11 | 07:01:30 | 07:03:22 | 01m 51s |
| clip-12 | 07:03:28 | 07:04:56 | 01m 28s |
| clip-13 | 07:05:03 | 07:06:30 | 01m 27s |
| clip-14 | 07:06:36 | 07:08:03 | 01m 27s |
| clip-15 | 07:08:10 | 07:10:02 | 01m 52s |
| clip-16 | 07:10:09 | 07:11:26 | 01m 17s |
| clip-17 | 07:11:33 | 07:13:25 | 01m 52s |
| clip-18 | 07:13:31 | 07:15:00 | 01m 29s |
| clip-19 | 07:15:06 | 07:16:44 | 01m 38s |
| clip-20 | 07:16:51 | 07:18:30 | 01m 39s |

## Slowest clip cycles

| Clip | Submission through review | Submission through local download | Post-download review/wait |
|---|---|---|---|
| clip-02 | 25m 31s | 07m 24s | 18m 07s |
| clip-05 | 23m 56s | 10m 08s | 13m 49s |
| clip-01 | 22m 31s | 04m 08s | 18m 22s |
| clip-10 | 19m 46s | 03m 23s | 16m 23s |
| clip-17 | 19m 09s | 03m 34s | 15m 36s |

## Interpretation and priority

1. **Agent continuation is the largest avoidable delay.** Approximately three hours accumulated after native files were downloaded but no agent turn was active. The existing heartbeat instructions were corrected to keep the agent with each video through delivery; next-run improvement is not yet measured.
2. **Clip generation/recovery is second.** The 20 submission-to-download spans total about 102 minutes, median about 3 minutes 37 seconds. Clips 20 and 14 take the longest in this measure; both had recovery interruptions, so their 14m46s and 13m16s spans do not establish slow model computation. Keep saved-job recovery and retry only documented safe download operations.
3. **Review and picture alignment are substantial.** Active post-download elapsed time includes ASR, comparing product images, timing edits, cutaway inspection and related work. Reuse validated tooling, while retaining genuine artifact review.
4. **Local rendering takes 31 minutes.** Sections run one at a time and usually finish in 1–2 minutes. Sections 17, 15 and 11 are longest. No hours-long render pause occurred at section 6. Keep the current one-worker policy unless a controlled resource test justifies a later change.
5. **Initial implementation is not a per-video cost.** The first phase contains setup and code work; do not extrapolate it unchanged to all remaining videos.
6. **TTS and upload are minor.** Twenty TTS requests total about 95 seconds to saved responses; the six-minute audio phase also includes local pause removal, timing allocation and intervening agent work. Music was reused. Upload and verification took seconds.

## Evidence and limits

This reconstruction uses saved submission/review timestamps, render receipts, local native-file/response/verification modification times, Drive and cleanup receipts, and persisted task-start/end events for this task. It does not expose credentials or raw private conversation content.

Submission-to-download includes provider processing, polling, transport and recovery. It is not an API-side timing metric. File modification timestamps are local availability evidence. Active-turn elapsed time is not exclusively editing or compute. QC performed during rendering is not counted a second time. The join-timing bug occurred after all sections rendered and is already fixed. No new generation or media editing was performed for this analysis.

## Machine-readable detail

CSV and JSON exports are in `data/production/next-15-video-plan-20260915/productions/haul-01/review/timing-analysis/`: `phases.csv`, `visual-jobs.csv`, `narration-requests.csv`, `render-sections.csv`, and `timing-evidence.json`.
