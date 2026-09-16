# Hypit MsDressly reference adaptation

## Commission and current status

Adapt https://www.instagram.com/p/Db9SrsBsIUg/ into a multi-product MsDressly
haul using real catalog references, original copy, a fictional presenter and a
new voice with similar delivery. The approved target is **169.700 seconds,
5,091 frames at 30fps, 1080 × 1920**. This supersedes the earlier thirty-second
single-product proposal. The reference's outlier ratio has not been verified.

All eighteen selected clips are downloaded. The exact-duration final cut is
exported after sampled visual review, four automated audiovisual reviews and
a more detailed native-speech timing check. That last check found timing drift
that the broader model reviews had missed; picture timing was corrected locally.

## Production and review

Project: `data/production/v-product-variation-Db9SrsBsIUg/hypit-full-length-01/`

Finished-video review: http://localhost:5188/#comments while Hypit Studio runs.
The complete editable timeline remains at http://localhost:5187/#comments;
the lighter delivery player shows the actual finished MP4.

Final file: `MsDressly_Full_Haul_2m49s.mp4`, **47,466,376 bytes**. It measures
**169.700 seconds, 5,091 frames, 1080 × 1920 at 30fps**, with H.264 picture and
stereo AAC audio. Full decoding, frame count, duration, dimensions, blank-frame
and audio-peak checks pass. Measured peak is −1.6 dBFS. Opening, outfit, close-up
and final CTA frames were inspected. See `DELIVERY.md` and `final-qc/`.
The MP4 container reports 169.721 seconds; both picture and audio streams
measure 169.700 seconds. The source-duration match uses the picture frame clock.

| Material | File |
|---|---|
| Editable complete composition | `final.svml`, `final.svrun`, `style.svs` |
| Actual 566-word narration copy | `SCRIPT-timing-edit.md`, `final-copy.json` |
| Exact edited ElevenLabs narration | `audio/narration.wav` |
| Original full-length music bed | `audio/music-bed.wav` |
| Phrase subtitles and edit sheet | `MsDressly_Full_Haul_Captions.srt`, `MsDressly_Full_Haul_Edit_Sheet.csv` |
| Stable Canvas jobs, selections and native quotes | `canvas-state.json` |
| Approved spending scope | `budget-approval.json` |
| API receipts and conservative reservations | `receipts/`, `spending-status.json` |
| Visual inspection and automated clip reviews | `assets/visual-inspection.json`, `assets/qc/` |
| Local corrections | `editorial-adjustments.json` |
| Selected picture timing corrections | `picture-selections.json`, `picture-timing-adjustments.json` |
| Verified section renders | `rendered-sections/` |
| Product provenance | `products/selected-products.json` |

The earlier narrated catalog storyboard remains available as
`MsDressly_Full_Haul_Narrated_Storyboard_2m49s.mp4`; it is visibly marked as
pending footage. Rejected generation attempts are preserved for audit and
excluded through explicit accepted-media selections.

## Generation and assembly

- **Official Canvas CLI 1.0.1**, existing authenticated CN account, native
  credential storage. One active generation at a time, one result per job.
- **Seedream 5.0 Pro** creates ten consistent-presenter outfit references.
- **Seedance 2.0 Fast VIP** (`seedance_2.0_fast_vip`) generates 720p portrait
  picture, requesting 178 seconds across eighteen selected clips and trimming
  to the source's exact duration. The 1080p delivery upscales these sources.
- Accepted outfit images and the exact newly recorded narration guide the
  speaking clips. Source-video conditioning was removed after the first test
  copied the reference presenter and text. No source soundtrack is in the edit.
- **ElevenLabs v3 / Jessica** (`cgSgspJ2msm6clMCkdW9`) supplies the final
  soundtrack. Raw generated-video audio is discarded during normalization.
- **Vertex Lyria 3 Clip** supplied a new 27.742-second instrumental. A measured
  interior phrase is crossfaded and fitted locally to 169.700 seconds, reduced
  beneath the narration and faded at the ends. An earlier Pro request was
  rejected without media; its receipt remains recorded.
- **Hypit 0.1.8** performs local normalization, sequential composition, typed
  title, word-timed progressive captions, outfit labels, soundtrack mixing and
  rendering. Existing build outputs are reused explicitly. Exact program
  intervals render with out-of-range layers omitted; a 115-frame comparison
  against the complete source produced identical decoded pictures (SSIM 1.0).
  FFmpeg joins the rendered picture sections without another video encode and
  adds one continuous master soundtrack, avoiding audio padding at section cuts.

Real catalog selection: checkerboard tank, blue ankle-length jeans, white
wide-leg jeans, short-sleeve denim shirt, blue wide-leg jeans, black romper,
red pullover, charcoal set, white textured jacket, brown set and beige set.
Product references establish design intent; generated footage is not a physical
fit or performance test, and inventory snapshots do not guarantee all variants.

## Quality corrections

1. Replaced the opening that copied the source performer and garbled titles.
   The accepted opening uses a new presenter and captions authored in Hypit.
2. Corrected a red outfit reference from an open cardigan to the actual pullover.
3. Replaced clip 07 after short sleeves became long sleeves and a second woman
   appeared. Its accepted replacement keeps one presenter and the correct shirt.
4. Cropped clip 05 above changing footwear while retaining the featured tank
   and jeans.
5. Replaced the first 1.6 seconds of clip 08 with a verified dark-jeans detail,
   then revealed the correct white jeans. Narration continues over the cutaway.
6. Framed clip 16 on the brown top and presenter to exclude a brief unwanted
   trousers change. The romper shot uses a product close-up, and a brown-trouser
   detail covers omitted native generated words across the clip 15/16 boundary.
7. Fitted sixteen clips locally to measured native/reference word-time anchors.
   This corrects drift of up to roughly 1.4 seconds while retaining the complete
   original ElevenLabs track. The aligned pictures have exact target frame
   counts. ASR-based timing is approximate and does not prove perfect lip sync.

All generation receipts and failed attempts remain distinct from accepted clips.
Sampled images and automated reviews support selection but do not establish
frame-perfect lip sync or human viewing approval.

## Voice and timing evidence

The source Scribe transcript contains 699 words, about 247 words/minute. The
new narration contains 566 authored words, about 200 words/minute. Thirteen
Jessica takes were edited locally by removing optional sentences and pauses.
Most pitch-preserving tempo factors are 1.00–1.16; the short opening uses 1.28.
The result measures exactly 169.700 seconds. Captions use actual word times.

One initial TTS request was rejected because v3 does not support context fields;
removing those fields resolved it. Successful requests submitted 3,823
characters, including delivery tags. The conservative reservation, including
that validation rejection, is 3,979 of the approved 4,000 credits.

Gemini's initial audio and clip checks reported intelligible narration and usable
visible speech timing, but missed drift detected by the word-time comparison.
The corrected full-film review reports clear audio, readable captions, consistent
identity and no significant problems. An initial whole-film response exhausted
its output limit; it is preserved as incomplete. A separate concise Flash-Lite
review completed with thinking disabled and a US$0.01 reservation, supported by
the [official token prices](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing).
Human review remains pending. Background style was
inferred from the supplied audio; this is new music with similar energy, not a
reproduction of its exact composition or verified tempo.

## Spending and recovery

| Account | Approved maximum |
|---|---:|
| Existing Jimeng account | 2,000 credits |
| Existing ElevenLabs account | 4,000 TTS credits |
| Combined additional audio analysis, transcription, music and review | US$1 |

The user approved the corrected opening and then automated generation. That
later instruction permits bounded quality corrections within the same caps.
The completed Jimeng reservation is **1,348 credits** including rejected
attempts and replacements. Additional audio API reservations total **US$1.00**,
including the truncated review and completed concise review. The dollar
allocation is exhausted; do not make more paid calls under this approval.
These reservations are not independently verified settled billing.

Every Canvas submission uses a verified native quote and credit ceiling.
Submission IDs are saved before effects. Accepted or ambiguous jobs recover
through their existing operation IDs; never submit them again. Audio requests
have durable receipts that block duplicate POSTs. Purchases, top-ups and
publishing are outside this commission.

## Verification boundaries

No production-module code or frozen contracts changed. The latest full offline
suite remains the prior **300 passing** run, not rerun for production artifacts.
This is a separate Hypit workflow; it does not verify MoneyPrinterTurbo or sign
all G6/G8/G12 production gates. The local final export and technical checks are
complete. Owner viewing/listening approval and publishing remain separate.

The older `hypit-variation-01/` retains the superseded thirty-second draft and
verified five-second silent style preview. Do not run its old Canvas drafts.

Canvas: https://jimeng.jianying.com/ai-tool/ai-canvas/076538d8-f76e-4742-8731-480a077e4eb9
