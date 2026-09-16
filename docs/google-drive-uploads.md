# Google Drive asset delivery

## Verified connection

- CLI: `gdrive 3.9.1`.
- Account: `tingsong.dai@gmail.com`.
- Existing OAuth application: `n8nworkflow`; user completed Google authorization
  on 2026-09-15. Credentials are managed by gdrive outside this project.
- Destination: [Short Form AI YouTube](https://drive.google.com/drive/folders/1XQU20m_xk5030kAxbbIumeHYkrRPkPbs).
- Folder metadata and all 22 previously uploaded filenames verified through
  the CLI. No missing files, duplicate names, or additional uploads.

## Future requested uploads

Use the existing CLI connection. Keep source files in place and create copies
with descriptive delivery names so pipeline references remain valid.

```bash
gdrive files list --parent 1XQU20m_xk5030kAxbbIumeHYkrRPkPbs --max 100 --full-name
gdrive files upload --parent 1XQU20m_xk5030kAxbbIumeHYkrRPkPbs \
  --print-only-id '/absolute/path/to/descriptively-named-asset.mp4'
```

Inspect the destination and prior upload receipt first to avoid duplicates.
Upload only files covered by the user's request, then record returned file IDs
and verify their presence. Folder sharing settings should remain as configured.
No scheduled or automatic upload process has been enabled.

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
