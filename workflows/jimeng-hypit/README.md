# Jimeng footage → local Hypit editing

This is a five-second portrait editing starter, using an already generated local
video. Copy the four source/profile files into a new video project; edit that
copy for the actual production. The working example is
`data/production/v-jimeng-hypit-pilot`.

Required project files:

- `package.json`: a private package naming this video project.
- `assets/source.mp4`: a validated portrait video covering the full timeline.
- `assets/title.ttf` and `assets/label.ttf`: licensed, regular-weight font files.
- These four files: `video.svml`, `style.svs`, `render.svrun`, `hypit.runtime.json`.

The pilot copies the accepted Jimeng coffee shot and uses this Mac's Georgia and
Arial fonts locally. Fonts and video are kept in ignored production storage.
Supply appropriately licensed fonts when moving the project to another machine.

## Editing

`video.svml` owns source selection, duration, picture/audio tracks, title wording,
placement, paint colors/shadows and display times. `style.svs` owns font sizes,
text alignment, fitting and visual layer order. Titles are authored overlays,
not speech-aligned captions. The starter includes the source clip's audio.

For another clip, verify its actual video duration covers the timeline. For a
silent clip, set Normalize's `audio="none"`, remove `source-audio="content"` and
the `footage.audio` Film track. Keep picture playback at native rate unless a
specific hold, loop or retiming is wanted.

For multiple shots, declare/normalize each file and give each Media Item an
explicit `start`/`end` window in shot order. Use the saved shot list and validated
manifest as the source of that order. Measure narration before assigning windows;
stop for insufficient footage. Do not interpret one selected pilot shot as a
complete asset set. Add separately selected local alignment when real narration
needs word-timed captions.

## Runtime

The profile contains only local FFmpeg and HyperFrames providers, one active
render with two renderer browser workers. Generation stays in the existing
Jimeng asset pipeline and uses its quote/approval/resume commands.

Do not replace this profile with `runtime init`'s hosted starter. Select the
supplied profile with `runtime use hypit.runtime.json`. Before each render,
`plan render.svrun --json` must report all requests local, with no unresolved or
unsupported capabilities. A future narration/transcription addition should keep
that service choice explicit.

See [workflow setup and commands](../../docs/jimeng-hypit-workflow.md).
