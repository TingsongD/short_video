# Hypit skill with the existing Jimeng subscription

## Selected workflow

Use the Hypit skill for planning, source authoring, editing and review. Use the
official Jimeng Canvas CLI through M6 for generated footage and images. Import
verified files into Hypit and render locally. This requires no HypiHub key,
HypiHub generation balance, reverse API or custom generation Provider.

After each final export or final revision, complete the mandatory
[Drive delivery and service cleanup](google-drive-uploads.md#required-completion-workflow)
before reporting completion. Return the Drive link after the upload is verified
and the video's local services have released their ports.

Skill installed globally for Codex with:

```bash
npx --yes skills add hypit-ai/hypit -g --agent codex --skill hypit --yes
```

Installed Skill: `~/.agents/skills/hypit/SKILL.md`. It is available for discovery
on the next Codex turn; its instructions were read and used for this setup.
The executable is pinned separately to `@hypit/hypit@0.1.8` in
`vendor/hypit-runtime`. The project launcher is `scripts/hypit.sh`; it preserves
the current video workspace. To restore a missing executable installation:

```bash
npm install --prefix vendor/hypit-runtime --save-exact @hypit/hypit@0.1.8
./scripts/hypit.sh --version
```

### Local renderer compatibility

Hypit 0.1.8's separate capture process does not install the distribution's package
resolvers. The first real export failed with `ERR_MODULE_NOT_FOUND` for
`@hypit/hyperframes`, although source checking and Studio preview succeeded.

The launcher supplies `scripts/hypit-node-bootstrap.mjs` through inherited Node
startup options. It installs the same distribution and external-package resolvers
as Hypit's own executable in the worker and capture child. This keeps the repair
outside the vendor package and leaves shell configuration unchanged. The bootstrap
checks the pinned version; recheck or remove it when upgrading Hypit. The regression
test imports the real capture dependency tree in a fresh child process, offline;
it skips when this optional Hypit installation is absent.

Use the launcher for local runtime and rendering commands. If this video's runtime
was already started with the original executable, stop it once with
`scripts/hypit.sh runtime down` from that video workspace before starting it through
the launcher. This allows the new worker to inherit the repair.

## Generate through Jimeng

Continue to use the existing reviewed asset workflow:

```bash
.venv/bin/python -m modules.assets doctor
.venv/bin/python -m modules.assets prepare data/production/VIDEO/shot_list.json
# Review quotes and approve the actual batch ceiling before this command:
.venv/bin/python -m modules.assets generate VIDEO --credit-ceiling APPROVED_CEILING
.venv/bin/python -m modules.assets status VIDEO
.venv/bin/python -m modules.assets resume VIDEO
```

Use `status`/`resume` for an existing submission; do not generate again after an
uncertain result. Retain the shot list, manifest and recovery journal. Jimeng
keeps its own credentials and credit controls. Editing already accepted media
does not submit another generation.

## Open or render the prepared local pilot

From the repository root:

```bash
HYPIT_PROJECT_CLI="$PWD/scripts/hypit.sh"
cd data/production/v-jimeng-hypit-pilot
"$HYPIT_PROJECT_CLI" runtime use hypit.runtime.json
"$HYPIT_PROJECT_CLI" runtime up --endpoint media.local --endpoint hyperframes.local
"$HYPIT_PROJECT_CLI" check video.svml
"$HYPIT_PROJECT_CLI" plan render-reuse.svrun --json
"$HYPIT_PROJECT_CLI" studio --run render-reuse.svrun --port 5184
```

Open the actual printed Studio URL in the user's Chrome profile. Comments accepts
timestamped feedback; Studio exposes the timeline, title wording, placement and
source editing. The interface supports English and Simplified Chinese.

Before a render, confirm the plan passes and all requests use the local profile.
The starter has five local requests and zero hosted requests. The pilot's
`render-reuse.svrun` explicitly reuses its existing normalized `clip.media` output
and has three local requests, zero hosted requests. Its completed final is already
at `data/production/v-jimeng-hypit-pilot/final.mp4`.

For an intentional edit, check the plan and submit one local render in another
terminal in that video workspace, retaining its new build ID:

```bash
../../../scripts/hypit.sh build render-reuse.svrun --json
../../../scripts/hypit.sh status BUILD_ID --watch --max-wait-ms 45000 --json
../../../scripts/hypit.sh get BUILD_ID --output final.video --to final-revision-2.mp4
```

Each `build` is a new rendering attempt. A timeout of the observer needs status
on that same build ID. A failed attempt requires investigation before a new local
build. Export refuses an existing destination; use a fresh filename for a new
revision and retain earlier outputs. Studio and rendering have separate processes.

The reuse Run references a build in this pilot's local runtime. Copy the starter's
`render.svrun` for a new video, not that pilot-specific recovery Run. If replacing
the source footage in this pilot, remove the explicit `clip.media` reuse first so
the new file is normalized; do not reuse an output that belongs to the old clip.

## Verified pilot — 2026-09-15

- Existing Jimeng coffee footage imported with provenance and SHA-256 recorded.
- Local doctor and preflight pass. The repaired build
  `bld_20260915T182740926Z_30543A5A62` completed with `final.video` present.
- MP4: H.264, **1080×1920, 30 fps, exactly 5 seconds**, AAC stereo, 1,366,810 bytes.
  The source is 720×1280, scaled for this output; this adds no source detail.
- Full FFmpeg decode and existing assembly resolution/audio/duration QC pass.
  QC's five-second reference is the authored timeline, not measured narration.
- Ten sampled frames spanning the clip and a full-size closing frame show the
  push-in, changing steam, two timed titles and persistent label. Studio opens in
  the user's Chrome profile with editable source and timestamped comments.
- Source audio is included: five seconds, mean −20.6 dB and peak −7.6 dB. Automated
  checks establish non-silent audio; listening and creative acceptance remain for
  the user. Titles are authored overlays, not speech-aligned captions.
- **Zero new generation calls or credits** for this editing test; all render work
  was local. The first failed local render's normalized clip was reused.
- Offline validation: **231 passed in 25.48 seconds**. Receipts and QC are in this
  pilot's production folder; consolidated evidence is `data/production/setup-test-evidence.json`.

## Reuse for another video

Copy [the starter](../workflows/jimeng-hypit/README.md) into a new, explicitly named
production folder. Import the intended Jimeng files, save their provenance and
checksums, then author the actual shot order and timing. The agent can perform
this handoff using the two installed skills; a native Hypit generation Provider
is unnecessary for this file-based workflow.

The starter demonstrates picture, source audio, timed titles and rendering.
Real narration, speech-aligned captions and full 4–7-shot coverage remain separate
production checks. Our MoneyPrinterTurbo backend and frozen contracts remain the
existing production baseline; this adds an agent-directed Hypit editing lane.

Narration and music credentials can now come from the project `.env`; see
[audio provider setup](audio-providers.md). Google TTS/Lyria require route and
account verification before generation adapters are connected. Import accepted
audio into the Hypit composition after validating its actual format and duration.
