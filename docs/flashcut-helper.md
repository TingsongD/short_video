# Isolated flash-cut helper

This installation is separate from the application's Python 3.14 environment and the managed WhisperX environment. It has no HTTP listener, receives no provider credentials, and cannot download models while processing a job. The initial qualified target is macOS arm64, Python 3.11, CPU FP32, batch eight (allocation recovery: four, two, one). MPS remains unqualified.

## Explicit setup

Use an existing Python 3.11 interpreter and an explicitly installed `uv` executable:

```sh
python3 scripts/flashcut-helper-setup.py --install --python /absolute/path/to/python3.11 --download-model
python3 scripts/flashcut-helper-setup.py
vendor/flashcut-helper/.venv/bin/python -m pytest tests/helper -q
```

The first command downloads public dependencies, PE source and checkpoint. The second is verification only. Neither command submits paid requests. Existing mismatched source/model files are reported, not overwritten. Never point installation at the application or WhisperX environment.

Dependencies are hash-locked in `config/flashcut-helper.lock`; direct requirements are in `config/flashcut-helper.in`. Readiness checks all installed locked versions, the source commit and checkpoint hash. Jobs fail closed on a mismatch. Tests generate their own small local media and must not download models. A missing model or renderer is a validation gap, not a successful check.

## Upstream code and model notices

- Meta Perception Encoder source: [facebookresearch/perception_models](https://github.com/facebookresearch/perception_models), pinned commit `3e352cca660658d4b5c90f42a7808b11469e4c66`.
- Weights: [facebook/PE-Core-S16-384](https://huggingface.co/facebook/PE-Core-S16-384), revision `aabf3b990573d8114ae6e501b4697106beac8f19`, SHA-256 `ccc8340a14ea3ebf557a288ba4ed4a5bc026ab98bb4da42fc745d44b4c5c5ffb`.
- PE uses Apache License 2.0. Preserve the upstream `LICENSE.PE`, copyright notices and this attribution when distributing the helper. The same upstream repository contains differently licensed PLM material; this integration uses PE, not PLM.
- Other helper packages retain their installed distribution license notices. Python, FFmpeg and Hypit retain their respective distribution terms; this document does not relicense them.

## Limits and recovery

The immutable v1 policy caps sources at 18,000 decoded positions and 600 seconds. It permits no frame dropping. Heavy jobs share one `local_media` slot. Each 256-frame chunk allows the initial attempt plus two local recoveries; helper-level startup/extraction failures also have an initial attempt plus two recoveries. Completed chunks are hash-verified and reused.

The helper uses actual decoded presentation timestamps, keeps audio sample mapping, and rejects corrupt frames, ambiguous stream selection and discontinuous audio instead of inventing timing. PE similarity is evidence of visual resemblance, not proof of character identity. Acoustic spikes and drop candidates are measurements, not semantic conclusions.

The frozen `explicit_padding_1ms.v1` audio policy preserves a positive gap of at
most 1 ms with separately recorded zero samples; at most 5 ms total may be
padded. It never closes a gap by shifting later speech. Larger gaps, overlaps,
unknown timing or changing sample rates pause processing. Padded samples are
not claimed to be recovered source content.

Selected windows are limited to four seconds with one second overlap. Every
candidate retains full half-second lead/trail context where source bounds allow.
All measured audio events remain in the manifest; optional acoustic stills use
one representative per second, not three PNGs for every energy spike. Mandatory
visual/quiet/callback coverage is never removed by this rule or by Jev shadow
advice. Source-resolution selected PNGs remain separate from 384px PE inputs.

The disk watchdog covers both evidence and selected registered media. It stops
on inspection failure, less than 10 GiB free, or more than 32 GiB across those
roots. Initial processing is deliberately serialized through `local_media`;
do not increase concurrency without measuring memory and disk pressure.

## Unpaid quotation preflight

`scripts/flashcut-preflight.py` runs under the helper interpreter against explicit
local source/transcript paths and their expected SHA-256 hashes. Supply a
dated non-secret pricing JSON and a **new** output directory. It never opens
the application database, loads credentials, calls providers or grants budget
authority. Its output includes exact source evidence and a bounded analysis
quote, including two clarification rounds and a separate maximum editorial
planning request after final TTS. It does not pretend that footage/TTS quantities
are known before the new script and production plan exist.

`scripts/flashcut-benchmark.py` similarly creates a new isolated synthetic
benchmark directory. Neither script is a production job or a substitute for
the worker's fencing/capacity lifecycle. Keep preflight outputs for diagnosis;
do not promote them by editing historical run records.

Evidence is stored under the factory data root's `source_evidence/` directory and included in recovery backups. Do not delete it while any run refers to it. Selected media will use the normal artifact registry; embedding arrays never go through dashboard media APIs.
