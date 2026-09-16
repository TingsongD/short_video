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
