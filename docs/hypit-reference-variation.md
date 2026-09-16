# Hypit product try-on variation

## Scope and current result

Reference: https://www.instagram.com/p/Db9SrsBsIUg/

Product: the MsDressly black-and-white checkerboard tank retrieved through the
authorized Shopify Admin connection. The complete product media list contains
one front image and no video or additional angles.

The requested target is a roughly 30-second presenter-led adaptation: energetic
opening, full-body styling reveal, step toward camera for garment details,
then alternate outfits and a choice/CTA. A new fictional presenter and original
dialogue feature the user's product. The original is approximately 169.713s;
the adaptation compresses its try-on structure. Its outlier ratio is unverified.

**Current output is a five-second typography/layout preview.** It reuses the
previously generated product-motion clip. It has no spoken performance, outfit
changes or music. The full adaptation is prepared and awaiting new spend
approval; it has not been generated.

## Local files and review

Project directory:
`data/production/v-product-variation-Db9SrsBsIUg/hypit-variation-01/`

- `MsDressly_Hypit_TryOn_Style_Preview_5s.mp4`: revised exported preview.
- `layout-review.svml`, `style.svs`, `layout-review-reuse.svrun`: editable preview.
- `video.svml`, `render.svrun`: planned full production; requires future
  `assets/take-01.mp4` and `assets/take-02.mp4`.
- `BRIEF.md`, `TREATMENT.md`, `TIMELINE.md`, `PROGRESS.md`: production decisions.
- `canvas-state.json`: stable Canvas IDs, saved plans and recovery state.
- `variation-report.json`: builds, budget status and verification evidence.

Hypit Comments/Studio is available while its local server runs:
http://localhost:5185/#comments

The preview recreates the reference's fast typing-cursor heading, condensed
white title, yellow italic subheading, small serif captions and italic product
label. It does not yet reproduce the original's brief tilted transition.

## Completed verification

- Hypit 0.1.8 source checks and local render preflight passed for the preview.
- Initial build `bld_20260916T015532486Z_6E04CDF33D` completed.
- Revised build `bld_20260916T015830127Z_3EA1463EFD` completed, explicitly reusing
  the initial build's normalized `clip-one.media` output.
- Export: H.264, 1080 × 1920, 30fps, exactly 5.0s. Its source footage is 720p;
  the larger export does not add captured detail.
- Full video/audio decoding passed. Frames at 0.3, 0.8, 2.5 and 4.8s show
  readable, unclipped text. The AAC track is silent (maximum −91dB in the
  16-bit volume measurement), consistent with the silent source.
- The preview made no new paid-provider requests.
- Full-production source validation correctly stops on the missing future
  footage; its render has not been tested.

## Prepared Canvas generation

Official Canvas CLI 1.0.1, using the existing authenticated account:
https://jimeng.jianying.com/ai-tool/ai-canvas/076538d8-f76e-4742-8731-480a077e4eb9

1. One `seedream_5.0_pro` presenter image, 9:16, 2K, conditioned on the actual
   product image. Quoted at **8 Jimeng credits**.
2. One 15s `seedance_2.0_fast_vip` clip, 9:16, 720p, with the presenter, product
   image and an imported ten-second original-reference excerpt for motion.
3. One 15s clip using the presenter, product and first generated take for
   continuity. It cannot also include the ten-second original excerpt because
   the live catalog limits combined video-reference duration to 15.4s.

All three generation drafts are saved with stable node/update/submission IDs.
The reference video upload is ready. An attempted local scene-image upload
returned uncertain state and is unused; the room is described from observed
frames. No active plan depends on that uncertain image resource.

Both video quotes currently return `REFERENCE_SOURCE_NO_OUTPUT` because their
upstream generated references do not exist. The partial eight-credit image
quote is **not** a price for the complete batch.

## Pending decision and continuation

Pending user approval: a maximum **350 Jimeng credits plus US$0.05 ElevenLabs**,
covering one presenter image, two 15s speaking clips, and transcription of the
reference and generated clips. This is separate from the completed five-second
direct-Canvas test. No new generation or transcription has been submitted.

After approval:

1. Record accepted account, scope and ceilings in Brief and state.
2. Transcribe the reference using the user's existing ElevenLabs account;
   refine the treatment if its timed dialogue changes the visual reading.
3. Quote and generate the presenter once; inspect product fidelity.
4. Quote each dependent video only when its reference exists. Enforce the
   remaining overall ceiling through native Canvas credit controls; never
   interpret a partial quote as batch authorization.
5. Persist IDs before effects and resume uncertain jobs by those IDs. Do not
   automatically regenerate failures or variants.
6. Download and inspect both takes, transcribe actual speech, replace provisional
   caption timings and align the edit to the actual performances.
7. Render, watch and listen to the encoded final, and hand off Studio for review.

This is a prepared manual production through official Canvas plus Hypit. It
does not establish automatic Shopify/M6/Hypit integration or sign off G6/G8/G12.
Publishing remains a separate gate.
