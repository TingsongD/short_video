# Hypit integration review

Reviewed 2026-09-15 UTC against upstream commit
[`07bf1cca6730091691030bbe8a064275b2dcf817`](https://github.com/hypit-ai/hypit/tree/07bf1cca6730091691030bbe8a064275b2dcf817),
package version 0.1.8. This is a source and documentation review. Hypit was
cloned into a temporary inspection directory; its dependencies, Skill and runtime
were not installed or executed. No generation or paid service was used.

## Recommendation

**Add Hypit as an optional M8 composition/rendering backend, beginning with a
local-media pilot.** Retain our Jimeng Canvas generation, narration, production
checkpoints, media validation, cost controls, QC and publishing approval.

The proposed path is:

```text
M1–M5 research, idea, format and script
    → M6 Jimeng Canvas → validated clips/images
    → M7 narration → voice.mp3
    → M8 Hypit composition → local final.mp4
    → existing QC → human review → separate publishing gate
```

This is an architectural recommendation, not a completed integration. The
existing MoneyPrinterTurbo backend remains the baseline until an actual Hypit
render has demonstrated better editing results at acceptable render time.

## What Hypit would add

| Capability | Value in our workflow | Upstream evidence |
|---|---|---|
| Word-linked visual timing | Place a title or B-roll change on the word the narrator actually speaks; more precise than our current proportional shot allocation. | [Script](https://github.com/hypit-ai/hypit/blob/07bf1cca6730091691030bbe8a064275b2dcf817/docs/quickstart/script.md), [timing](https://github.com/hypit-ai/hypit/blob/07bf1cca6730091691030bbe8a064275b2dcf817/docs/quickstart/timing.md) |
| Styled captions and graphics | Karaoke highlighting, cue motion, fonts, overlays and reusable layouts. These are the main potential improvement over our present MPT task builder. | [Caption Fine](https://github.com/hypit-ai/hypit/blob/07bf1cca6730091691030bbe8a064275b2dcf817/packages/caption-fine/README.md), [Media Track](https://github.com/hypit-ai/hypit/blob/07bf1cca6730091691030bbe8a064275b2dcf817/packages/media-track/README.md) |
| Editable production files | Store reusable composition templates alongside our format IDs; change presentation without regenerating Jimeng media. | [Run sources and explicit reuse](https://github.com/hypit-ai/hypit/blob/07bf1cca6730091691030bbe8a064275b2dcf817/docs/quickstart/run.md) |
| Browser review | Preview the timeline, edit supported properties, and save timestamped comments before export. | [Studio](https://github.com/hypit-ai/hypit/blob/07bf1cca6730091691030bbe8a064275b2dcf817/docs/quickstart/preview.md) |
| Local rendering | Chrome/HyperFrames renders pictures; separate media operations render audio and mux the final video. Existing files can supply the inputs. | [Media declarations](https://github.com/hypit-ai/hypit/blob/07bf1cca6730091691030bbe8a064275b2dcf817/packages/media/README.md), [render contract](https://github.com/hypit-ai/hypit/blob/07bf1cca6730091691030bbe8a064275b2dcf817/packages/render-hyperframes/README.md) |

## Important integration boundaries

### 1. Keep Jimeng outside Hypit's generation system initially

I found no Jimeng/Dreamina/Canvas CLI integration in the reviewed packages,
services and relevant guides. Hypit's Seedance authoring package describes model
requests; the included HypiHub provider executes those requests through a separate
service/account. Sharing a model-family name does not share our Jimeng browser
login, Canvas resources or credits.

Import the downloaded, validated `shot-NN.jimeng.*` files instead. A custom Canvas
provider is possible in principle, but would need to preserve our quotes, credit
ceilings, stable submissions and uncertain-result recovery. It adds little value
to the first editing pilot.

Sources: [Seedance author package](https://github.com/hypit-ai/hypit/blob/07bf1cca6730091691030bbe8a064275b2dcf817/packages/seedance/README.md),
[HypiHub provider](https://github.com/hypit-ai/hypit/blob/07bf1cca6730091691030bbe8a064275b2dcf817/packages/provider-hypihub/README.md).

### 2. Spoken timing needs explicit alignment

Our frozen shot list contains the full script and voice text, but no per-shot
spoken segments or word timestamps. Therefore it cannot automatically become
Hypit's word-linked timeline without a mapping step.

For the first pilot, use `voice_text` as one Script segment, align the existing
narration, and keep our measured shot allocations for the pictures. This tests
captions without inventing a correspondence between shots and sentences. Later,
store approved word/segment anchors in a separate edit-plan file to drive cuts
and callouts. Preserve the frozen shot-list and asset-manifest schemas.

Hypit's real-media `SemanticTake` requires normalized media, an authored segment
and an explicit language. Its deterministic alignment package consumes acoustic
evidence; importing an MP3 alone does not supply measured word timing. The default
hosted WhisperX path is a separate service. Select the local WhisperX provider
explicitly for a pilot with no provider charges.

Sources: [WhisperX author surface](https://github.com/hypit-ai/hypit/blob/07bf1cca6730091691030bbe8a064275b2dcf817/packages/whisperx/README.md),
[alignment contract](https://github.com/hypit-ai/hypit/blob/07bf1cca6730091691030bbe8a064275b2dcf817/packages/speech-alignment/README.md),
[local WhisperX](https://github.com/hypit-ai/hypit/blob/07bf1cca6730091691030bbe8a064275b2dcf817/packages/provider-whisperx-local/README.md).

### 3. Preserve our recovery and spending rules

Hypit documents a fresh ID for each `build`, explicit reuse of earlier outputs,
and no implicit cross-build cache. Closing a status observer leaves execution
running; losing the worker's execution context ends that attempt. Worker restart
does not resume it automatically. Persist the returned build ID, inspect it after
interruptions, and use explicit completed-output references for a new build.

Its pricing command reports rates and uncertainty, not a guaranteed total or our
native Jimeng credit ceiling. The reviewed build CLI has no spending-ceiling flag.
Use a profile containing only the intended local providers for the first pilot,
and retain the existing generation and dollar approval controls in Python.

Sources: [build/reuse/pricing behavior](https://github.com/hypit-ai/hypit/blob/07bf1cca6730091691030bbe8a064275b2dcf817/docs/quickstart/run.md#read-prices-for-the-selected-run),
[actual CLI flags](https://github.com/hypit-ai/hypit/blob/07bf1cca6730091691030bbe8a064275b2dcf817/packages/cli/src/arguments.ts#L78-L121).

### 4. Local setup is feasible, but rendering is not yet benchmarked here

This Mac has Node 26.7.0, pnpm 10.33.2, FFmpeg/FFprobe and uv on PATH, 12 logical
CPUs and 64 GiB RAM. Hypit itself was not on PATH. Upstream requires Node 22.15+
and documents a managed Chrome runtime; local WhisperX adds its own Python
environment, recognition weights and language alignment weights. Meeting the
listed Node range does not establish that our exact version is runtime-tested.

Start with one render request and two Chrome workers, then measure. Local
WhisperX's practical Apple Silicon path is CPU/int8; its CTranslate2 backend does
not acquire CUDA or PyTorch MPS support merely because this is an Apple Silicon
Mac. Local rendering avoids a provider charge but still uses machine resources
and setup time.

Sources: [development requirements](https://github.com/hypit-ai/hypit/blob/07bf1cca6730091691030bbe8a064275b2dcf817/docs/guide/develop.md),
[render resource controls](https://github.com/hypit-ai/hypit/blob/07bf1cca6730091691030bbe8a064275b2dcf817/packages/provider-hyperframes-local/README.md),
[local transcription setup](https://github.com/hypit-ai/hypit/blob/07bf1cca6730091691030bbe8a064275b2dcf817/packages/provider-whisperx-local/README.md).

### 5. The license fits our current internal use, with limits on productization

The checked license expressly permits own-organization commercial work, client
work performed by that organization, and single-organization deployments. It is
a modified Apache-based license with additional terms: hosted/multi-tenant
offerings to third parties and commercial redistribution require separate
permission; surfaced Hypit attribution must be retained. The producer claims no
ownership of generated outputs. Our internal content-production use fits the
stated permitted category; a future customer-facing video SaaS is a different
licensing decision.

Source: [upstream LICENSE](https://github.com/hypit-ai/hypit/blob/07bf1cca6730091691030bbe8a064275b2dcf817/LICENSE).

## Concrete adoption plan

1. **Prove local composition first.** Pin the reviewed version; prepare an isolated
   project with explicit local media, HyperFrames and WhisperX providers. Use four
   existing clips/images and a real spoken narration. Render a roughly 20-second
   1080×1920 video with word highlighting, a hook title and one animated callout.
   Run the same source material through MPT for comparison. This can use manual
   assets while the separate Canvas authorization remains pending.
2. **Add a selectable M8 adapter after the comparison.** Proposed files:
   `modules/assemble/hypit.py` for process/result handling and a template exporter;
   reusable SVML/SVS templates under `modules/assemble/templates/`. Select via
   `assembly.backend = "mpt" | "hypit"`. Feed existing validated artifacts and
   preserve our output/QC interface. Store Hypit build IDs, output addresses,
   source/template hashes and renderer version in a separate `hypit_job.json`.
3. **Expand templates only after one end-to-end pass.** Add a format-ID-to-template
   registry outside the frozen format contract. Introduce semantic shot anchors,
   Studio review and controlled presentation variants after the first template is
   reliable. Script, voice, and visual-generation changes keep their existing
   explicit regeneration requirements.

### Adapter details that matter

- Export `.svml` (composition), `.svs` (presentation recipes), `.svrun` (requested
  outputs), and a local runtime profile into an explicit per-video workspace.
  Escape our prose for SVML's reserved syntax; do not treat user text as markup.
- Use the existing prepared clips for the first comparison. Hypit still requires
  its own typed media normalization; measure that overhead. Later, native image
  items can preserve still-image motion controls without our still-to-video step.
- Check the compiled plan before building. Import only local media/renderer/
  alignment dependencies for the pilot; avoid generation nodes and hosted routes.
- Use structured CLI output for plan, build, status and result lookup. Export the
  exact named output with `get --to` into a fresh staging path, because `get`
  refuses an existing destination. Validate it before replacing our final file.
- Keep native playback and sufficient source coverage. Hypit supports hold,
  loop and stretch, but our current no-silent-retiming policy remains in force.
- Include backend, renderer version and template/style hashes in assembly reuse
  checks. A Studio edit must invalidate the render, without invalidating approved
  Jimeng assets or narration.

Sources: [SVML text syntax](https://github.com/hypit-ai/hypit/blob/07bf1cca6730091691030bbe8a064275b2dcf817/docs/quickstart/script.md#comments-and-escaping),
[export CLI](https://github.com/hypit-ai/hypit/blob/07bf1cca6730091691030bbe8a064275b2dcf817/packages/cli/src/arguments.ts#L143-L169),
[media playback policies](https://github.com/hypit-ai/hypit/blob/07bf1cca6730091691030bbe8a064275b2dcf817/packages/media-track/README.md#item-windows-and-source-playback).

### Pilot acceptance

- The planned build has no paid generation or hosted transcription requests.
- Every shot is covered in the intended order; captions follow the actual words.
- Export passes existing resolution/audio/duration QC and a visual subtitle check.
- An interrupted observer can reconnect without submitting another build; a
  completed alignment can be explicitly reused after a style-only edit.
- Record setup time, render time, peak memory, output size and human editing effort.
  Keep MPT as default unless the measured result justifies changing it.
- Offline adapter tests must cover paths/escaping, malformed CLI results, missing
  media, existing export destinations, job recovery and preservation of gates.

No production code, frozen contracts, credentials or running pipeline were changed
for this review. Upstream runtime/license/test details are in the companion
`hypit-upstream-review.md` note.
