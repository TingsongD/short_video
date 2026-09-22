# Factory aligned speech

Pure JavaScript authoring adapter for the pinned Hypit 0.1.8 public authoring API.
The JavaScript source is the build artifact: compositions freeze these exact
files and their hashes. No compiler, package installation or network request is
performed during a render.

`Take` imports final, verified, fitted WAV word timings into native SemanticTake
objects using the Script's own token identities. It refuses missing words,
ambiguous segmentation, changed text, overlaps and out-of-range frame intervals.
It declares no provider capabilities or Needs. It never requests alignment.

Place these Takes in Timeline for semantic timing and captions. Do not present
their audio with Sound: the final Film receives exactly one frozen premix.
Selections and Moments remain native Script values; intra-word edits use explicit
integer frame intervals. The caller is responsible for verifying waveform hashes,
fit/alignment provenance and actual duration before authoring this surface.
