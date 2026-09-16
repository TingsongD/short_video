# Direct Canvas product-reference test

## Purpose

Test whether Jimeng can animate the real MsDressly checkerboard tank while
preserving its visible front details. The user selected the official Canvas
CLI for this first test and supplied Shopify Admin access in `.env`.

The downloaded Instagram reference is a presenter-led clothing try-on. This
first shot tests the product image in motion, not full-video motion transfer,
outfit changes, narration, or lip sync.

## Prepared scene

- Product: Women's Black and White Checkerboard Tank Top.
- Input: the product's one Shopify image, 1365 × 2048.
- Model: `seedance_2.0_fast_vip`, verified in the live catalog.
- Mode: `m2v`, using the imported image node as a reference.
- Output: one five-second 9:16 video at 720p.
- Action: a small front-facing weight shift, stable camera, torso-focused crop.
- Preserve: checkerboard pattern, neckline, armholes, jeans and original setting.
- Quote and enforced ceiling: **30 Jimeng credits**. This is an authorization
  limit, not independent evidence of final settled billing.

[Open the test canvas](https://jimeng.jianying.com/ai-tool/ai-canvas/076538d8-f76e-4742-8731-480a077e4eb9).

## Native CLI findings

Canvas CLI 1.0.1 account and model discovery passed in CN. The local-file
upload returned `cli.upload_state_unknown`; a read-only resource lookup found
no registered image. Importing the public Shopify image URL through the
official `resource upload --source-url` path succeeded with the same resource
ID. No raw Jimeng HTTP or browser credentials were used.

The imported image node contains the successful source resource. Readback of
the video draft confirms its reference points to that image node, its upstream
connection exists, and its prompt placeholder resolves through a reference
part. Chrome also shows two nodes and one connection.

The shot was quoted before execution and submitted once. The native credit
confirmation token remained in memory. Source upload, node updates and video
submission identities are persisted separately from the frozen contracts.
Recovery observes the original operation; it does not replay generation.

## Evidence and recovery

Local folder: `data/production/v-product-variation-Db9SrsBsIUg/`.

- `BRIEF.md` and `ANALYSIS.md`: proposed adaptation and sampled reference evidence.
- `product/`: verified Shopify product record and inspected image.
- `canvas-direct-state.json`: private recovery state and latest operation result.
- `canvas-reference-verification.json`: saved reference relationships.
- `canvas-test-prompt.txt`: exact prompt used for the first test.
- `test-report.json`: test scope and technical/visual results.

Resume with read-only native `operation status` or `operation wait`, using
`video_submit_id` and `project_id` from the state file. Download only the
successful resource belonging to that submission. Validate duration, actual
media type, dimensions, checksum and complete decoding; inspect sampled frames
for product fidelity before considering further generation.

The application M6 adapter remains text-prompt-only. This direct CLI test does
not imply an automatic Shopify importer or image-reference support has been
added to that adapter. See [Shopify asset intake](shopify-product-assets.md).

## Result — 2026-09-15

The one submission completed successfully. Native download checksum, byte count,
M6 media intake and full FFmpeg decoding passed. The original is H.264 at
720 × 1280, about 5.09 seconds including its generated stereo audio. It is saved
as `assets/shot-00.jimeng.mp4` in the evidence folder.

The silent delivery preview copies the video stream without re-encoding; it is
5.017 seconds and also passes full decoding:
`deliverables/MsDressly_Checkerboard_Tank_Seedance2Fast_Product_Motion_Test_5s_720p.mp4`.
The original audio was not evaluated or used in the preview.

Six sampled frames from the start through 4.917 seconds retain the recognizable
checkerboard pattern, high neckline and sleeveless outline. Movement is subtle,
with a small front-facing weight shift. This is a promising product-reference
test awaiting the user's visual review, not certification of exact garment
geometry, all-frame continuity, alternate views or full try-on quality.

No additional generation, automatic regeneration, publishing or store mutation
occurred. Production code and frozen contracts were unchanged; the latest full
offline test result remains 300 passing. Documentation passes `git diff --check`.
