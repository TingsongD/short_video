# Produce, review and resume a local video

Production uses the official Jimeng Canvas CLI for missing shots. It preserves
the original script and media across review pauses. The default stop is QC;
publishing requires an explicit continuation through its own approval gate.

```bash
# First run: existing spend approval is still required for the script LLM.
./run.sh produce IDEA_ID --stop-after assets

# Inspect data/production/v-IDEA_ID/asset_status.json and the returned canvas.
# It contains every shot quote and the total; no generation happens yet.

# After explicitly approving that quote:
python -m modules.assets generate v-IDEA_ID --credit-ceiling APPROVED_INTEGER
python -m modules.assets status v-IDEA_ID
python -m modules.assets resume v-IDEA_ID

# When remote work finishes, start any remaining unsubmitted shots using the
# original batch ceiling. Then continue production without regenerating assets.
./run.sh produce IDEA_ID --resume --stop-after assets
./run.sh produce IDEA_ID --resume
```

Alternatively, after reviewing the saved quote, pass
`--jimeng-credit-ceiling APPROVED_INTEGER` to a resumed production run. The adapter
applies the same per-shot native credit limits. Omitting this option never grants
new generation approval. A pending operation stops the run for later resume;
unknown or rejected work requires review. Repeated generation uses the original
ceiling, including already reserved credits. Jimeng credits are recorded in
`assets/jimeng_jobs.json`, separately from the dollar ledger.

## Existing assets and manual fallback

```bash
./run.sh produce IDEA_ID --resume --asset-provider manual --stop-after assets
python -m modules.assets collect v-IDEA_ID
# Stock is opt-in:
./run.sh produce IDEA_ID --resume --asset-fallback stock --stop-after assets
```

Files go into `data/production/v-IDEA_ID/assets/` as `shot-00.mp4`, etc.
The intake status lists missing and rejected shots, including rejection reasons.
Pexels is constructed only when its key exists and used only with explicit stock
fallback. Valid completed assets can pass this gate even without Canvas login.

## Reuse and timing

`production_state.json` records script, narration settings and file hashes.
`--resume` reuses the saved shot list and validated narration; it does not call
the LLM or TTS again for these artifacts. Edited scripts/settings or narration
without a matching receipt stop for review. Missing narration after an earlier
attempt is not automatically regenerated. Use an explicit new `--video-id` when
requesting a new production. Concurrent CLI runs for the same ID are blocked.

`prepared/materials.json` records ordered clips allocated proportionally to the
measured narration length. Videos are trimmed and stills are rendered to those
allocations at 30 fps. Short footage stops assembly; it is not stretched to fit.
Unchanged prepared clips and a previously validated final are reused on resume.

MPT receives one sequential output and a clip limit that preserves each prepared
clip. Its local launcher disables automatic uploading and selects Whisper for
subtitles over custom narration. Runtime logs go to stderr and the result JSON
stays on stdout. MPT's returned task paths are checked and copied into the
production folder; an old `final-1.mp4` alone cannot indicate a successful render.

Review `final-1.mp4`, `final-1.frame-1s.jpg`, `assembly_result.json` and
`qc_report.json`. QC checks resolution, audio, file size and drift against the
actual narration. The local MPT smoke test uses an eight-second fixture
narration, mixed video/still assets and disabled subtitles. It verifies native
rendering/output retrieval; subtitle rendering and the complete live workflow
remain a separate live check. Whisper model availability and font selection
must be verified for that check. The configured ElevenLabs voice is still unset
and must be selected before a real narration run.

## Publishing remains separate

```bash
./run.sh produce IDEA_ID --resume --publish
```

This still requires the existing publish approval and metadata spend gate.
The local workflow milestone ends at QC; no publishing has been performed.
