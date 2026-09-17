# Google Drive asset delivery

## Verified connection

- CLI: `gdrive 3.9.1`.
- Account: `tingsong.dai@gmail.com`.
- Existing OAuth application: `n8nworkflow`; user completed Google authorization
  on 2026-09-15. Credentials are managed by gdrive outside this project.
- Destination: [Short Form AI YouTube](https://drive.google.com/drive/folders/1XQU20m_xk5030kAxbbIumeHYkrRPkPbs).
- Folder metadata and all 22 previously uploaded filenames verified through
  the CLI. No missing files, duplicate names, or additional uploads.

## Required completion workflow

The user's standing instruction (2026-09-15) authorizes these steps after every
finished video, including corrected final exports, across Jimeng/Hypit and other
production routes. Perform them within the video task without asking again.
This applies to the finished deliverable, not each intermediate generated shot.

1. Finish export and QC. Preserve the local video and give its delivery copy a
   descriptive name that identifies the subject, version and duration.
2. Upload the finished video to the authorized folder above using the existing
   CLI connection. Check prior receipts and destination files first; reuse a
   verified identical upload instead of creating a duplicate. Preserve distinct
   revised finals with descriptive version names.
3. Verify the remote parent, name, byte size and MD5 against the local file.
   Save the Drive ID/link, local SHA-256 and verification result in an upload
   receipt within the video's production folder. After an ambiguous upload
   response, reconcile remote state before retrying.
4. Stop the completed video's preview servers, render/runtime workers and child
   processes. Identify ownership by workspace, command and process ancestry;
   gracefully stop those services, then terminate any verified survivors.
   Verify their ports have no listeners and save a shutdown receipt. Preserve
   saved files and credentials, other projects' services and active work.
5. Return the Drive link and confirm the freed ports. Mark local preview URLs
   offline in the production handoff. Completion requires both a verified upload
   and verified service cleanup.

If upload or verification fails, retain the local deliverable and recovery
receipt, still stop the completed video's idle services, and report the upload
as pending. Never claim delivery succeeded without remote verification.

## Upload commands

Use the existing CLI connection. Keep source files in place and create copies
with descriptive delivery names so pipeline references remain valid.

```bash
gdrive files list --parent 1XQU20m_xk5030kAxbbIumeHYkrRPkPbs --max 100 --full-name
gdrive files upload --parent 1XQU20m_xk5030kAxbbIumeHYkrRPkPbs \
  --print-only-id '/absolute/path/to/descriptively-named-asset.mp4'
```

Inspect the destination and prior upload receipt first to avoid duplicates.
The standing instruction covers each finished video; upload additional assets
when requested. Folder sharing settings should remain as configured.

## Current delivery evidence

The delivery contains 20 distinct media assets, a readme and an asset catalog.
Identical cached copies were consolidated by SHA-256. Media decoded locally;
remote names and IDs were verified, without claiming remote checksum validation.

- Upload manifest and Drive file IDs:
  `data/production/drive-export-20260915/upload-manifest.json`.
- Sanitized authorization check:
  `data/production/google-drive-setup/auth-status.json`.

These generated local receipts are gitignored. Do not add OAuth credentials
or exported account archives to the project or delivery folder.

## Corrected MsDressly full haul (2026-09-15)

- [MsDressly_Full-Haul_Corrected-Captions_1080x1920_2m49s.mp4](https://drive.google.com/file/d/1zUxjyRIILGZ4UedvxS_u_e7rNcNZgAGZ/view)
- Destination: the existing authorized folder above; sharing unchanged.
- **47,366,136 bytes**, remote MD5 `d3f65067ded01419cdbe3a4e0b6f31dc` matches local.
- SHA-256 `314b53f2c3d9e279584ec8ebd291afc9666b2e5501530cbe7c097bb56c41aaa0` identifies the caption-corrected final.
- Receipt: `data/production/v-product-variation-Db9SrsBsIUg/hypit-full-length-01/drive-delivery/upload-receipt.json`.
- Local Hypit preview services and workers stopped after verification; ports 5184–5188 are free.

## Sequential batch: haul 01 (2026-09-16)

- [MsDressly_Haul-01_Checks-Statement-Denim_10-Products_2m49s_v1.mp4](https://drive.google.com/file/d/1iV_A7HB-tbbWs7HGGqUYSr0tT5se7SFs/view)
- Verified in the authorized folder above, with unchanged sharing.
- **51,603,087 bytes**, remote MD5 `448575b8e268cf4627200df71abe3940` matches local.
- SHA-256 `57c15bb9dc884d9ba6b122b1367316404a105ea1f35c6c9018705fad2be92b25`.
- Receipts: `data/production/next-15-video-plan-20260915/productions/haul-01/upload-receipt.json` and `cleanup-receipt.json`.
- QC: 169.7 seconds, 1080×1920, 30 fps, 5,091 frames; all twenty sections and ten products present. Review evidence and limitations are in the adjacent `review/final-review.json`.
- No surviving owned video workers; ports 5184–5188 verified free. Local previews are offline.

## Sequential batch: hauls 02–04 (2026-09-16)

- [MsDressly_Haul-02_Matching-Sets-Sporty-Weekends_10-Products_2m49s_v1.mp4](https://drive.google.com/file/d/1lJBeCabu_0wtYi-QjByepb58kPgNKaoX/view): 91,258,536 bytes; verified remote MD5 `41686efa45b034bc0a6d7aa2d182554a`.
- [MsDressly_Haul-03_Blue-and-White-Everyday_10-Products_2m49s_v1.mp4](https://drive.google.com/file/d/18KciMXRSGwSkHP7-w2POZtaMbwgeBLa-/view): 105,345,229 bytes; verified remote MD5 `aa0f95a82bcd7b00c0d99f976e7257f1`.
- [MsDressly_Haul-04_Sparkle-and-Night-Out_10-Products_2m49s_v1.mp4](https://drive.google.com/file/d/13XFuiTBhZDrVcClvY6Ni06fjd-aHYMjg/view): 98,494,563 bytes; verified remote MD5 `38e525cfedd00f8855fb1c9ed73de431`.
- Each final is 169.7 seconds, 1080×1920, 30 fps. Receipts and QC limitations are saved in each haul folder. Remote parent, name, bytes and MD5 verified; sharing unchanged.
- Owned workers stopped, production browser tabs closed, ports 5184–5188 verified free after every upload.

### Haul 05 — Special Occasion Dresses (2026-09-16)

- [Verified final video](https://drive.google.com/file/d/1PRYrEZA0ol-sfftMG6ZgZ5Neesr2MNqY/view), 169.7 seconds, 1080×1920, 30fps.
- 102,059,284 bytes; MD5 `6464cd6c58eccdef862053d55a4df046`; Drive parent and filename verified.
- 1,174 Jimeng credits including one corrected outfit image. 530 caption states checked; one 33ms boundary inspected on adjacent frames. Burgundy variant label corrected before upload.
- Final audio correlation 0.999976 against approved Jessica v3/music mix. Two short garment-detail cutaways preserve correct narration over native pronunciation differences. Sampled review does not guarantee perfect lip sync.
- Task workers stopped, production browser tab closed, ports5184–5188 free, 70% memory free at18:23UTC. Batch spent5,888 /13,502 credits.

### Haul 06 — Florals and Boho Textures (2026-09-16)

- [Verified final video](https://drive.google.com/file/d/1S7vcrJONU0zbtT93M7V7oJ8wkpdqvDMp/view),169.7seconds,1080×1920,30fps.
- 122,121,183bytes;MD5 `bad0a3176c0fb135374e036a7295b1aa`;SHA256 `ac5c083fb66e790926e2705f3e32a74afbb546909ad9bedbc45bf49cf7d2d3c2`.
- Remote folder/name/bytes/checksum verified19:09:15UTC. Owned workers stopped, production tab closed, ports5184–5188free,70%memoryfree.
- 521caption states scanned;65OCR discrepancies visually resolved. Original Jessica/music correlation0.9999739. Minor print-placement variation and one local detail cutaway recorded in final-review.json.

### Haul 07 — Work-to-Dinner (2026-09-16)

[Verified final](https://drive.google.com/file/d/1zPrt67JObd5ExnOG4xfTrN1FoXHhgCeE/view): `MsDressly_Haul-07_Work-to-Dinner_10-Products_2m49s_v1.mp4`, 102,343,447 bytes; MD5 `3a53c81dfaee9723cca1d36f66b56603`. Parent/name/size/checksum verified; workers stopped, ports 5184–5188 free and production tab closed. Local receipts in `data/production/next-15-video-plan-20260915/productions/haul-07/`.

### Haul 08 — Western Details and Playful Prints (2026-09-16)

- [MsDressly_Haul-08_Western-Details-and-Playful-Prints_10-Products_2m49s_v1.mp4](https://drive.google.com/file/d/1fDBF8RpCv9DX1MjwU23v--owyNzEr4zl/view)
- 101,711,918 bytes; parent/name/bytes/MD5 verified. MD5 `ed92411f2cd5d63af4d71a8d933f5c55`.
- 169.7 seconds,20clips,10products.539caption states audited,37differences inspected;35OCR errors and2one-frame cue boundaries verified. Full decode and audio correlation0.99997689pass. Three-second fringe-jacket detail covers native pause drift.
- Workers stopped, production tab closed, ports5184–5188free. Receipts in haul-08 folder.

### 2026-09-16 — Haul 09 delivered

Animal Print Outfit Refresh verified in Drive: https://drive.google.com/file/d/1SFaOniIxUTMWDZi7bwa7TaHw8gcIH7NL/view . Twenty reviewed clips, ten products, 169.7 seconds. 1,168 Jimeng credits including one cardigan correction; 2,973 TTS credits. Nine delivered; batch total 10,542/13,502, leaving 2,960. All 539 caption states scanned and all 37 OCR differences inspected as recognition errors; six final grids inspected. Full decode and soundtrack correlation 0.99997651 pass. Drive bytes/MD5/parent/name verified, workers stopped, ports 5184–5188 free, browser tab closed, 73% memory free. Continue video 10 within unchanged ceiling.

Filename: `MsDressly_Haul-09_Animal-Print-Outfit-Refresh_10-Products_2m49s_v1.mp4`. Bytes: 112645470. MD5: `5b5cca77cfc42e98f928ddab918ad1d0`.

### 2026-09-16 — Haul 10 delivered

Cozy Autumn Lounge verified in Drive: https://drive.google.com/file/d/1S0dhCnyInxgfdtOtJkg6NbxZEMG6R4X2/view . Ten products, twenty reviewed clips, 169.7 seconds. 1,162 Jimeng credits including one corrected hoodie image; 3,170 conservative TTS credits including one corrected take. All 544 caption states audited, all 27 OCR discrepancies inspected as recognition errors. Six final grids inspected, full decode and original soundtrack correlation 0.99997726 pass. Drive parent/name/bytes/MD5 verified; workers stopped, production tab closed, ports 5184–5188 free, 73% memory free. Batch total 11,704/13,502; 1,798 remain. Continue video 11 if its complete quote and repair reserve fit.

Filename: `MsDressly_Haul-10_Cozy-Autumn-Lounge_10-Products_2m49s_v1.mp4`. Bytes: 102,371,779. MD5: `acb4e594d0da2a811f5f77fdb0e468d6`.

### 2026-09-16 — Haul 11 delivered; funded batch complete

Statement Jackets and Autumn Layers: [verified Drive final](https://drive.google.com/file/d/1o1fQskQQ4tY6oCLdczjlHs2ISqn2sEz_/view). Ten products, twenty sections, 169.7 seconds, 1080×1920 at 30 fps. All selected clips and six final grids inspected. All 541 caption states scanned; all 53 OCR differences visually resolved as recognition errors. Full decode passed, no black-frame detections, original Jessica v3/music correlation 0.99997533, peak -0.4 dB. Final audit took 30.8 seconds.

Haul 11 consumed a conservative 1,224 Jimeng credits: 1,154 base, two 8-credit outfit corrections and one 54-credit video replacement. The replacement was rejected for garbled native speech; the original opening plus a 5.43-second garment-detail view preserves correct Jessica narration. Three other brief detail cuts cover isolated articulation differences. Minor generated pocket-flap and vest-length differences are recorded in final-review.json. TTS reservation 3,207 credits includes one corrected take. Interrupted audio upload recovered with its original resource UUID, no duplicate paid submission.

Drive parent/name/106,080,494 bytes/MD5 verified at 22:39:48 UTC. MD5 `8d311221e6d9898baba15b5ea91716e1`; SHA-256 `305d4709b560b9a8115af3fc7098edcb2ca5a485081219d41a68425c1d524911`. Workers stopped, production browser tab closed, ports 5184–5188 free, 73% memory free. Local preview is offline.

**Funded stop:** 11 of 15 planned videos delivered. Conservative batch spend 12,928 / 13,502 Jimeng credits, leaving 574 within the approved ceiling. Actual logged-in Jimeng balance observed as 674. Current quote-derived lower bound for another complete video is 1,100 credits before the 200-credit repair reserve; this is a calculation from verified rates, not a haul-12 quote. Videos 12–15 remain unstarted, with zero new generation/TTS submissions for them. No top-ups or ceiling changes. Continuation automation `produce-sequential-msdressly-hauls` paused. Batch TTS reservation total 33,429 / 60,000. Evidence: `data/production/next-15-video-plan-20260915/batch-plan/funded-completion.json`.


### Short Haul 12 — 90 seconds, five products (2026-09-16)

- [Finished video](https://drive.google.com/file/d/1A_eNuhHCm4aTgQV5DCLflV7uHDzex2OD/view): `MsDressly_Haul-12_Five-Easy-Outfits_5-Products_90s_v1.mp4`.
- Verified parent, name, 54,441,131 bytes and MD5 `b623765adc665adcb58dbb32b4219d53`.
- [Red gingham cover](https://drive.google.com/file/d/1TBjpIEp7VrkKmT5OJumbtjYnE0UHaUf1/view) and [denim cover](https://drive.google.com/file/d/1zoHZO5IJdZ91Q-ZW12e8w25cLPKUtCfh/view): PNG files, each verified by parent, name, byte size and MD5.
- Receipt root: `data/production/msdressly-short-haul-12-20260916/productions/haul-01/`.
- Production workers and tab closed; ports 5184–5188 free; preview offline; final memory-free reading 71%.
- Used 674 Jimeng credits including correction and covers; official account balance verified as zero.


### 2026-09-16 — Google Vertex Omni 1.1 Flash API test

- [Verified four-second portrait test](https://drive.google.com/file/d/1TXAztF8J3y1kWtdtIUXjW8_ThYSHzfUd/view): `Google-Vertex_Omni-1.1-Flash_Checkerboard-Tank_API-Test_720p_4s_v1.mp4`.
- 720×1280, 24 fps, 4.01 seconds. 3,153,441 bytes; remote parent/name/bytes/MD5 match. MD5 `bcac38390b11dd02b4894fdda4e9cf9e`.
- Receipts: `data/production/v-vertex-video-pilot-20260916/`. Owned workers stopped; ports 5184–5188 verified free; 69% memory free. No local preview service started.
- Generic text-to-video API smoke test; no actual Shopify product reference or seed video used.
