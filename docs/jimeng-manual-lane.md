# Jimeng Lane B — manual asset checklist (SUPPORTED path)

Lane B is always available and is what G6 validates. ~10 min per video.

1. `python -m modules.assets queue data/production/<video_id>/shot_list.json`
   → writes `assets/prompt_cards.md` next to a `_shot_list.json` copy.
2. Open jimeng.jianying.com (your logged-in browser). For each card:
   - paste the prompt, set aspect **9:16**, type video/image per card
   - download the render as `shot-NN.mp4` / `shot-NN.png` into the
     `data/production/<video_id>/assets/` folder
3. Rules enforced at intake: file name `shot-NN.<ext>` (NN = shot idx,
   zero-padded), video covers its requested shot duration (at least 3s),
   min dimension ≥ 720px, mp4/png/mov/webm/jpg/webp. Actual media type must match.
   Tag provenance via `shot-NN.jimeng.mp4` (or `.stock.` for Pexels you
   grabbed manually). Untagged files count as `manual`.
4. `python -m modules.assets collect <video_id>` — validates everything,
   emits `manifest.json` when there is at least one valid asset. To explicitly
   fill gaps from Pexels, add `--fallback stock` (requires `PEXELS_API_KEY`).
   Exit code 2 = shots still missing; check the printed list.
5. Corrupt or undersized files are rejected with a reason — re-render and
   drop the file again under the same name.

The production backend is now the [official Canvas CLI](jimeng-canvas-cli.md).
The old best-effort `jimeng_bridge.py` remains available for diagnostics and is
not used by production. Manual imports continue to work without Canvas login.
