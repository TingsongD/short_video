# Five parallel clips: live validation

## Outcome

Haul 02, **Matching sets & sporty weekends**, is complete: ten products, twenty
selected clips, 169.7 seconds, 5,091 frames at 30 fps, 1080×1920.
[Verified Drive final](https://drive.google.com/file/d/1lJBeCabu_0wtYi-QjByepb58kPgNKaoX/view).

Five distinct Seedance 2.0 Fast VIP operations were observed running together.
The first five clips were submitted across 39 seconds and all downloaded within
**4m49s** of the first submission. Five is now the configured remote-job limit;
the controller still completes one whole video before starting the next.

## Measured improvement

| Comparable stage | Haul 01 | Haul 02 |
|---|---:|---:|
| Outfit images, clips, reviews and local edits | 6h31m29s | **36m50s** |
| Captioned export | 31m14s for twenty sections | **30.7s**, including technical QC |

The combined asset stage fell by about **91%** in this observed run. Production
from the first paid image submission through verified upload and worker cleanup
took **39m59s**. Product approval through cleanup took **45m33s**. Original brief
authoring before product approval is outside those windows.

This comparison uses different products and creative corrections, not a controlled
experiment. Cloud queue times vary. Do not promise five times the speed or add
overlapping job durations together. Submission-to-download times include polling
and time spent reviewing other artifacts; the slowest observed clip was 7m08s.

## Major steps and completion times

All timestamps below are UTC on 16 September 2026; subtract seven hours for
Vancouver local time. Asset generation and review overlap.

| Step | Start | Complete | Elapsed |
|---|---|---|---:|
| Product approval through narration approval | 15:11:27 | 15:16:55 | 5m27s |
| Images, clips and creative review | 15:17:01 | 15:53:51 | 36m50s |
| First five concurrent clips, submission through download | 15:23:11 | 15:28:00 | 4m49s |
| All generated assets downloaded, including corrections | 15:17:01 | 15:51:47 | 34m46s |
| Full captioned export and technical QC | 15:53:55 | 15:54:26 | 30.7s |
| Encoded caption/audio/picture inspection | 15:54:26 | 15:56:45 | 2m20s |
| Drive upload and verification | 15:56:47 | 15:57:00 | 13.0s |
| Owned-worker cleanup | 15:57:00 | 15:57:00 | 0.34s |

## Changes that removed the delays

- Five remote slots with one state writer, immediate collection, and inspection
  while other jobs run. A slow first job no longer hides later completed jobs.
- Continue within the active agent turn after ordinary review checkpoints. The
  ten-minute heartbeat remains interruption recovery, not the normal scheduler.
- Cache reference/voice preparation and review evidence. Reuse the local speech
  model across a batch and preserve original submission/resource identities.
- Prioritize repaired outfit references so their dependent clips become eligible.
- Render this static haul design in one FFmpeg/libass pass; keep editable Hypit
  files. Review timing uses the actual video-stream duration, avoiding AAC tail
  padding being mistaken for available picture.

## Quality, spending and delivery

Two eight-credit outfit corrections and one 66-credit video replacement fit the
existing allowance. Conservative total: **1,224 Jimeng credits**, **2,656
ElevenLabs credits**, and **$0** additional music or analysis APIs. No paid
submission was blindly repeated. One interrupted audio-reference upload was
recovered with its original upload idempotency key.

The replacement restored a missing opening word but repeated another word.
The final retains the approved ElevenLabs recording and uses an inspected,
face-free outfit detail over that moment. A second product detail covers uncertain
native brand pronunciation. All remaining picture timing is adjusted locally;
native generated audio is excluded from the final soundtrack.

Final review inspected all six one-second picture grids and all 478 caption
states. Fifteen OCR disagreements were visually resolved as recognition errors;
apostrophes render correctly. Full decode and black-frame checks passed. Encoded
audio correlation to the approved continuous narration/music mix is 0.999977.
Sampled picture and local ASR support the review; they do not prove perfect lip
synchronization or real-time listening.

Drive verification matched the name, authorized folder, **91,258,536 bytes** and
MD5 `41686efa45b034bc0a6d7aa2d182554a`. Final SHA-256:
`52f06e20c8b9d6e6a678eb1dc55468357c2da7310161bc8b9c11a2b2d806a158`.
No owned workers remain; ports 5184–5188 are free. The production-created Chrome
tab was closed. System memory pressure reported 72% free. Other services were
preserved.

Full offline validation: **342 passed in 28.03s**. Frozen contracts unchanged.
Hauls 01 and 02 are delivered; the remaining thirteen are not marked complete.

## Local evidence

Under `data/production/next-15-video-plan-20260915/productions/haul-02/`:

- `review/parallel-video-observation.json`, `review/first-five-timing.json`
- `review/job-timings.json`, `review/timing-summary.json`
- `review/pack/` and inspected local picture-edit receipts
- `fast-render.json`, `technical-qc.json`, `review/final-review.json`
- `upload-receipt.json`, `review/completion-check.json`

These operational files are private and gitignored; credentials are not copied
into the report or evidence.
