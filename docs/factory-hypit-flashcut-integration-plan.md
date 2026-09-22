# Developer handover: Hypit-first audiovisual flash-cut workflow

Date: 2026-09-21. Revision: 3. Status: implementation and offline qualification in progress; paid acceptance and deployment are not yet authorized. Current evidence and exact limitations: [implementation record](factory-reports/FLASHCUT-IMPLEMENTATION.md).

User-confirmed default: PE processes every decoded source frame for new flash-cut runs (`coverage=all_frames`), not only selected candidate frames. This updates the planned default; it does not mean the integration is already implemented or enabled.

User-confirmed addition: analyze the audio waveform, energy, onsets, rhythm and pauses; combine these with visual evidence to propose moments deserving inspection. A measured spike, a visible cut and an inferred story beat remain different facts.

This document supersedes the earlier integration outline. It is the implementation handover for one sequential builder, not a command to start generation. Existing research notes are background; their earlier candidate-only PE recommendations do not override the all-frame default here.

## Handover navigation

- Sections 1–4: scope, architecture and verified integration gaps.
- Section 5: implementation phases P0–P6, with exit conditions.
- Sections 6–8: caching, validation/rollout principles and limitations.
- Section 9: detailed audio detector and audiovisual fusion specification.
- Section 10: persisted policies, records, clocks and failure handling.
- Section 11: concrete existing/proposed module interfaces and file map.
- Section 12: work-package dependencies and deliverables.
- Section 13: required regression and acceptance matrix.
- Section 14: developer start, verification and deployment runbook.
- Section 15: primary references and remaining qualification decisions.

## 1. Outcome and boundaries

Improve how the Factory reconstructs a seed's setup, reveal, reaction, sound accents and rapid edits, then translates those relationships into A/B/C/D videos with replacement narration. Keep Hypit as the authoring/composition system and explicitly select it as the final renderer for the new profile. Do not build a second video factory.

The combination is complementary: Python measures timing, PE organizes visual evidence, Jev makes small text-based decisions, Gemini interprets audiovisual meaning, and Hypit executes the edit. None of these additions replaces the existing footage-generation or TTS providers. Better seed understanding does not guarantee convincing generated motion, character continuity or virality.

Safeguards:

- Python only for the new pipeline code; no Rust, MobileCLIP2 or `.scene` export.
- Future runs only. Do not migrate/resume the paused run, alter its four videos, or modify the 12 historical QA videos and their records.
- Preserve frozen schemas and fixtures, existing dirty workspace changes, historical accounting, unknown operations and do-not-retry decisions.
- Preserve saved A/B/C/D hypotheses, full-video versus controlled-region policies, replacement TTS alignment, phrase captions, final QC, verified Drive delivery and video-owned cleanup. Full-video comparisons remain multi-variable creative comparisons.
- No new mandatory manual or AI scene-approval gate. Technical failures, missing authority and ambiguous paid outcomes remain legitimate pauses.
- No publishing, new character-generation route, lip-sync, budget increases or paid validation in implementation scope. Reference-conditioned generation stays separately gated.

## 2. Responsibilities

| Module / tool | Owns | Must not own |
| --- | --- | --- |
| Existing Python Factory | Durable jobs, revisions, artifact identities, budgets, retries, QC authority and delivery | Delegating financial or recovery authority to a model |
| Python + FFmpeg, with PySceneDetect and qualified audio-feature routines | Timestamp-preserving extraction, every-frame cut signals, waveform/RMS/onset/band-energy/rhythm measurements, media normalization, frozen audio mix and technical checks | Declaring a scene cut or beat drop from an audio spike alone; silently replacing the selected renderer |
| Meta `facebook/PE-Core-S16-384` | Local embeddings for every decoded source frame, then representative-frame, novelty and coarse-label selection | OCR, reliable character identity, temporal storytelling or video generation |
| Jev, pinned initially to `jev-1.13.0` | Bounded structured decisions about supplied textual facts and optional evidence priority | Watching footage, generating scripts, approving scenes, deciding budgets or retrying operations |
| Existing qualified Gemini analysis route | Watching source context and exact evidence, identifying actions/cast/narrative relationships, resolving visual ambiguity | Frame-accurate arithmetic, provider reconciliation or assumed immunity to hallucination |
| Hypit | Native SVML/SVS/SVRun authoring, timeline composition, render Build/Result and editable presentation | A second uncontrolled paid-job scheduler |

Jev currently accepts text/JSON, not video, images or audio; pin the model instead of a moving alias. [TypeSafe model documentation](https://docs.typesafe.ai/models)

Meta publishes the selected checkpoint under Apache-2.0. Preserve its license/notice and pin checkpoint, code and preprocessing versions. Its speed and numerical behavior on this Mac are qualification questions, not established benefits. [Meta checkpoint](https://huggingface.co/facebook/PE-Core-S16-384)

## 3. Target flow

```text
Seed URL -> existing verified source + transcript + immutable analysis revision
         -> detailed stream/clock manifest
            |-> Python/FFmpeg: visual changes + PE on every decoded frame
            |-> Python/FFmpeg: audio energy/onsets/rhythm/pauses + transcript cues
         -> fuse timestamped evidence; preserve audio/visual lead and lag
         -> Jev: prioritize optional evidence from structured facts
         -> Gemini: whole-story context + exact frames + windows WITH audio
                    bounded targeted clarification when necessary
         -> existing creative context + A/B/C/D scripts and footage plans
         -> existing footage providers + replacement TTS + verified alignment
         -> editorial anchors resolved onto the final narration clock
         -> native Hypit composition -> actual final render
         -> authoritative final QC -> Compare -> verified Drive delivery
```

The crucial distinction is between a semantic story beat, a spoken passage, a generated clip and an editorial microcut. A two-frame reaction can be an edit inside a larger beat; it must not automatically become another narration request or paid generation request.

## 4. Existing-code prerequisites

Inspection found six integration hazards to reproduce and address first:

1. **Hypit is not currently the default for simple cuts.** `services/worker.py::render` selects `ffmpeg_fast` unless transitions/Ken Burns require Hypit; `templates/capabilities.py` also prefers FFmpeg. Add an explicit future-run renderer policy and make both paths honor it. A function's Hypit default does not establish runtime routing.
2. **Potential audio/provenance mismatch.** The worker builds a measured premix, but the composition compiler still receives original speech/music segments. FFmpeg receives the premix separately; Hypit renders the emitted composition. Add a reproducing regression, then bind the same frozen mixed artifact into both render paths. This is a code-traced risk, not proof that a historical video is defective.
3. **Evidence reuse is too coarse for this addition.** Same-source analysis may return an existing result without considering enrichment policy. Add a separate immutable enrichment sidecar; do not overwrite or silently relabel old evidence. Bind queued work to the loaded source, transcript, analysis revision and edit token, using the stronger existing editor enqueue path.
4. **Collected grids are not currently sent to Gemini.** The analysis adapter presently receives the source video, not the proposed enriched package. Explicitly implement and quote the new multimodal payload. Better local extraction alone will not improve Gemini's observation of a missed flash.
5. **Current audio facts are not an event timeline.** `media/audio.py::audio_characteristics` reports presence and whole-file mean/max volume. `analysis/deep.py` uses Hypit/WhisperX transcript timing, but neither constitutes time-resolved impact/beat/drop/silence analysis. Preserve these legacy helpers and add the new detector explicitly.
6. **Existing probe/seek output lacks precision and provenance for cue matching.** `media/probe.py::StreamInfo` does not retain selected stream index, start PTS, native timebase or per-frame timestamps. `media/frames.py::extract_frame` uses rounded timestamp seeking without returning actual selected-frame PTS. New detailed clock/decoded-frame records must close these gaps; do not infer exact frame identity from the old helpers.

Do not expand the exact-key `run_policies.v1` object informally. Store separate versioned source-analysis, editorial and renderer metadata, or implement an explicit backward-compatible decoder. Legacy records without these fields retain legacy behavior.

## 5. Work packages, in implementation order

### P0 — Baseline and dependency qualification

- Record tests, runtime versions and protected record/file fingerprints. Keep implementation against an isolated offline test database.
- Add regressions for the six integration hazards above before changing their behavior.
- Inventory installed Python, PyTorch, Hypit, Node and FFmpeg. Pin compatible PE/PySceneDetect and NumPy/audio-feature dependencies; librosa is the proposed local onset/rhythm implementation, not an instruction to install its latest release. Do not upgrade the working environment blindly or install CUDA-only examples on macOS.
- Start with one bounded local encoder worker and streamed batch limits. Qualify CPU first, then MPS where supported; report cold/warm time and peak memory on full-frame workloads. Fail readiness explicitly if neither backend qualifies. Resource pressure may reduce batch size, not frame coverage; exhausted resource limits cause an actionable pause rather than silent temporal sampling.
- Treat model acquisition as an explicit setup operation, with checkpoint hash and license verification. Tests and production jobs must never trigger surprise downloads.

Exit: a known baseline, an explicit Hypit routing policy, and matching rendered-audio/provenance bindings in local regression tests.

### P1 — Immutable, dense source evidence

Introduce a small source-evidence module: verified source/transcript/revision/policy in; immutable timestamped evidence manifest out. Keep extraction, encoder and decision adapters behind narrow internal interfaces, reusing existing artifact intake and analysis storage.

- Preserve Hypit's working probe/transcription/reference integration. Python/FFmpeg supplements it with dense, timestamp-preserving evidence; it does not reacquire or replace the source master.
- Measure low-resolution visual changes over the full timeline without frame skipping. Use raw content-change scores plus adaptive scene signals, simple hashes and separately timed audio energy/onsets.
- Preserve source presentation timestamps and rational timebases; record any source-to-proxy mapping. Audio events use sample coordinates, not assumed video frame rates.
- Retain brief candidates before semantic grouping. PySceneDetect's scene-length and flash-merging defaults require deliberate changes for this profile; test rather than assume that every peak is a cut. [Detector documentation](https://www.scenedetect.com/docs/head/api/detectors.html)
- Keep baseline coverage throughout the video, including quiet setup/payoff and contextual frames before/after brief events. Never globally deduplicate recurring shots or callbacks.
- Extract exact original-resolution evidence frames and bounded context windows. Register artifacts and their hashes; publish the enrichment pointer only after its bundle is complete.
- Record what was actually sampled, its ordering and remaining coverage gaps. A whole-video upload is not proof that a model examined every frame; tiny text or expressions without a cut remain explicit benchmark cases.
- Reject stale jobs/results after source or transcript edits. Never read whichever seed revision happens to be newest when a queued job finishes.

Exit: two-frame synthetic events, quiet passages, repeated scenes and VFR timestamps survive extraction without changing legacy evidence.

### P1a — Audio-event extraction and audiovisual fusion

Implement the detailed specification in section 9 after establishing P1's shared clock. Audio extraction and PE encoding may then run independently under the existing capacity manager; fusion waits for their complete compatible manifests.

- Persist waveform envelopes, measured features and cautiously labeled event candidates; distinguish no audio, valid silence, unreliable rhythm and failed analysis.
- Align all cues using exact sample/PTS mappings, not audio-window indices treated as video frames.
- Retain possible buildup/drop patterns, pauses, whooshes/risers and transcript-related events as hypotheses for Gemini, not approved scene boundaries.
- Merge evidence priorities, not the underlying timestamps. Preserve visual-only events, quiet passages, callbacks and sound that crosses cuts.
- Expose feature/detector versions, processed duration, event count and evidence quality. Optional diagnostic waveform display must use a compact envelope, not raw audio sample arrays in dashboard responses.

Exit: the section 13 audio/clock/fusion tests pass with synthetic inputs; no additional generation or cloud call is needed to exercise this phase.

### P2 — All-frame PE encoding and optional Jev decisions

- Default new flash-cut runs to `coverage=all_frames` in the saved source-analysis policy. Encode every decoded source frame at its native presentation timestamp, without temporal subsampling or dropping frames before PE. A constant 30 fps, 30-second source has 900 frame positions; variable-rate sources use actual decoded frame positions/timestamps, not rounded duration multiplied by nominal FPS.
- Stream frames through bounded PE batches using the checkpoint's qualified spatial preprocessing. All-frame coverage means no skipped times, not inference at original pixel resolution. Preserve source-resolution evidence for later inspection. Cache fixed-vocabulary text embeddings once per model/vocabulary version; do not rerun the text tower per frame.
- Persist completed encoding chunks and per-frame bindings so interrupted work resumes safely. Each decoded frame position needs a valid embedding result or an explicit error; repeated images remain distinct timestamped positions even when a verified content-addressed embedding can be reused. Check final coverage against successful complete decoding, and do not mark truncated decoding or partial encoding complete.
- Bind restart checkpoints to source hash, selected video stream, decoder policy, native PTS/timebase, model revision, preprocessing, precision and embedding shape. Require clean decoder completion and contiguous frame/checkpoint coverage rather than trusting container frame-count estimates. Preserve dashboard/render responsiveness through bounded queues and local capacity limits.
- Record selected backend, checkpoint/preprocessor identity, coverage and encoded/total frame counts. Missing models, corrupt inputs or unresolved encoding errors pause this required stage. Do not automatically fall back to candidate-only PE. A future opt-in lower-coverage profile would require its own saved policy and distinct result identity.
- Keep memory and disk bounded: stream inference and cache embeddings/manifests; do not require a permanent full-resolution image file for every frame. Retain registered exact-frame images and context windows selected for downstream use.
- Preserve full portrait frames. Qualify preprocessing against edge text and off-center subjects; a square embedding crop must never become the only evidence available to Gemini.
- Record similarity/novelty as suggestions with provenance, not facts. Do not turn a high embedding similarity into character verification or delete a repeat because it looks familiar.
- Feed Jev bounded records containing candidate IDs, timestamps, measured signals, transcript context and explicitly uncertain coarse labels. Never send naked embedding vectors as if they describe a scene.
- Ask independent, explicit questions about optional evidence priority or description completeness. Include candidate IDs in question instructions; do not assume question-map keys convey meaning or that one answer can consume another answer in the same request.
- Treat seed speech, OCR, filenames and descriptions as untrusted data. Validate allowlisted output choices against supplied candidate IDs; never interpret model output or source instructions as executable workflow commands.
- Python enforces required coverage and payload constraints. Jev cannot veto that coverage. Malformed, unavailable or uncertain advisory results retain conservative evidence under the saved fallback policy.
- Full-frame local encoding does not require sending every frame or every embedding to Jev/Gemini. Build bounded candidate summaries after PE, retain mandatory contextual coverage and send selected actual media to Gemini as planned.
- Start Jev in shadow mode: record suggestions without allowing them to remove evidence. Enable active prioritization only after its value is measured.
- Integrate Jev through existing durable effect/provider qualification boundaries. Disable hidden SDK retries; sanitize logs and minimize submitted data. A submission timeout remains unknown, even when generation can continue without an optional decision. Do not erase its reservation or resubmit it.

Exit: every successfully decoded frame position has verified PE coverage before this stage completes; PE failures pause without silently reducing coverage, optional Jev failures retain conservative downstream evidence, and restart recovery is tested. No new approval gate exists.

### P3 — Gemini understands the complete meme structure

Qualify `gemini-3.8-flash` as the target for the new profile, using the existing Google adapter and authorized account where supported. Google documents audiovisual input for this model, but this app's account access, region, request parameters, cost estimates and enriched payload route still need qualification. Keep it disabled for the new profile until that succeeds; do not change legacy runs or silently replace an unavailable route with another model. [Google model documentation](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-8-flash)

- Supply whole-timeline context, source transcript, exact flash frames, the audio-event manifest summary and selected contextual windows retaining the correct audio stream. Specify supported video sampling explicitly. Google documents default sampling around one frame per second; raising sampling alone still cannot guarantee capture of very brief events. [Video-understanding documentation](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/capabilities/video-understanding)
- Require source-grounded observations: setup, reveal, reaction, callback, sound accent, visible action, recurring role, intentional cast/wardrobe transition and text role. Separate spoken words, source captions, logos and environmental text.
- Produce an editorial-event sidecar attached to existing semantic beats. Each event identifies evidence timestamps, purpose, source relationship and intended target anchor—not a fabricated final timestamp.
- Keep targeted-window responses separate from the full-video beat contract. Validate local timestamps, map them back through exact source offsets, and merge only supported observations. Do not let a cropped window claim complete video coverage.
- Permit at most two persisted clarification rounds. Freeze maximum windows, cumulative video seconds/images, sampling FPS, token/payload limits and total request allowance in the quoted plan before submission; a round limit alone is insufficient. New window identities cannot reset these run-wide limits. Batch compatible windows, reuse verified evidence, and never silently truncate mandatory context to fit limits.
- Use stable effect tags including round/window/input identity. Do not reuse the ordinary analysis tag and accidentally retrieve an earlier job.
- Automatically continue after valid evidence/structure checks. Exhausted essential evidence, broken timing or missing Gemini capability gets a specific technical pause; do not silently substitute transcript-only analysis for this profile.

Exit: malformed responses, overlapping windows, missing coverage, budget refusal and unknown submissions fail safely; measured clarification improves evidence without unbounded calls.

### P4 — Turn source relationships into new edits

- Keep A a close structural adaptation with the saved light-paraphrase treatment. Keep B/C/D's existing hypotheses; retain full-video variant-specific footage when that policy applies.
- Map events to named target words/phrases, reveals or sound accents. Resolve these anchors using actual final replacement narration and its validated alignment, not the original transcript's timings.
- Preserve the distinction between natural speech passages and microcuts. Generate coherent material per scene/role/provider constraints, then use valid portions for multiple editorial windows within that variant. Do not silently substitute seed footage or cross-variant assets.
- Bind every final microcut to the actual generated artifact, valid source range and variant ownership. A seed flash describes the desired edit; it is not permission to reuse those seed pixels in regenerated B/C/D footage.
- Retiming a rewritten line invalidates its dependent cuts/captions, not unrelated speech or footage. If a required action is absent from generated footage, use existing bounded repair/QC; do not merely claim the action is present.
- For speechless passages, use explicit authored visual/audio anchors; do not invent narration just to obtain a clock.
- Preserve complete narration, caption readability, safe margins and music/voice mixing. Rapid picture cuts do not require equally rapid unreadable captions.

Exit: an event authored as two target frames renders as exactly two target frames; rewritten narration moves dependent edits correctly without unnecessary regeneration. When transferring a source event across different frame rates, preserve its intended duration/relationship and quantize once onto the target clock, not its source frame count. Retain a minimum visible frame for a required micro-event and record the quantization error; reject conflicting placements rather than silently losing an event.

### P5 — Hypit-first assembly and native semantic authoring in this release

Implement sequentially, but qualify both parts before releasing the profile:

1. Resolve editorial anchors to final frame intervals and feed the existing validated SVML/SVS/SVRun compiler. Select Hypit explicitly even for plain cuts. Preserve build-ID recovery, registered assets and actual returned artifact collection. Use one final clock and the authoritative frozen premix; prevent doubled original audio.
2. Represent the same canonical script and measured alignment through native Script, SemanticTakes, Selections and Moments using `@factory/aligned-speech`. This is part of this release, not a follow-up. Import verified replacement-speech timing without rerunning recognition. Semantic takes may be timing-only; one frozen premix is the sole soundtrack. Extend only the exact required local authoring imports and freeze the adapter hash into every composition.

Use frame/rational precision, not loosely rounded seconds, for microcuts. FFmpeg remains extraction, normalization, premixing and technical-QC infrastructure; a fast-render profile can remain an explicitly selected alternative, never an invisible downgrade.

Inspect the Hypit execution plan to ensure this stage only renders/reuses authorized assets. Do not let an authoring change trigger hidden generation, hosted alignment, new provider calls or unrestricted shell capabilities. Hypit unavailability is a renderer-readiness failure with a clear message.

Exit: actual local Hypit and FFmpeg fixtures verify picture timing, caption readability, audio mix and duration. A missing renderer is an explicit validation gap, not a pass.

### P6 — Progress, accounting and final quality

- Add a simple future-run profile, “Flash-cut / Hypit,” with advanced settings showing saved policy/model versions. No model picker is needed for everyday use.
- Show real substeps and counts: source extraction, PE encoding (for example, 450/900 verified frames when the total is known), frame selection, visual understanding, script/footage, narration alignment, assembly, final QC and delivery. Show waiting/backoff, last refresh, reuse and actionable technical failures. Use an indeterminate total until reliable decoding establishes it.
- Keep model scores in optional diagnostic details, not a new user review requirement. Do not display model confidence as certainty or a prediction of views.
- Extend quotes to include Jev input, all Gemini media/calls and bounded clarifications. Separate estimates from provider-confirmed usage and unresolved holds. Recheck authority before each executable paid dependency.
- Do not assume the earlier $50 video ceiling covers new analysis providers or reuse completed three-round QA authorization. Live benchmarking needs an explicit new scope and ceiling.
- Final QC watches the actual final with expected actions, intended cast changes and target timestamps. Embeddings and Jev do not replace artifact-bound visual QC.
- Keep generation, creative approval, final QC, delivery verification and cleanup independent. Compare must show the correct final revision and authoritative QC result. Delivery follows the saved authorized destination policy without fabricating approval; publishing stays disabled.

## 6. Cache identities and invalidation

| Result | Required identity inputs |
| --- | --- |
| Extracted evidence | Source hash, exact timestamps/timebase, extractor/settings version and proxy mapping |
| Acoustic features/events | Selected audio stream and source hash, decoded-span/trim mapping, decoder/resampler identity, sample rate, channel policy, window/hop/padding, feature and detector versions/parameters |
| PE embeddings/coverage manifest | Frame hashes, checkpoint/code/preprocessor hash and numeric mode; manifest additionally binds all-frame policy, ordered decoded frame positions/PTS and completeness |
| Evidence selection/fusion | Audio-event and visual/PE manifest hashes, transcript hash, fusion/window policy, label vocabulary, brief, Jev model/rubric and selector policy |
| Gemini observations | Exact media hashes/windows/sampling, transcript, model/prompt and analysis policy |
| Editorial plan | Observations, variant/script revision, intent/anchor policy, final speech/alignment hashes and target clock |
| Hypit build/final QC | Asset bindings, editorial/caption/mix policy, native package/compiler/runtime, exact final artifact and QC context |

Cache verified completed results only. Changing a Jev rubric should not re-encode images; changing narration should not regenerate unchanged footage. Unknown receipts are accounting/recovery records, not reusable successful results.

## 7. Verification, benchmarks and rollout

Offline regressions precede each implementation increment. Add new synthetic media outside frozen fixtures or generate them in test temporary directories. Mock every external provider.

Required cases: one/two-frame flashes, black/white frames, motion without a cut, recurring shots, quiet payoff, portrait-edge text, no speech, multilingual transcripts, VFR and rational frame rates; stale queued revisions, corrupt model/frame hashes, missing local models, malformed Jev/Gemini responses, restart-safe clarification limits, budget refusal and unknown operations; narration changes, same-variant reuse, premix identity and renderer recovery.

All-frame regressions must also prove 900/900 positions for a synthetic 30-second/30-fps source, correct actual decoded coverage for VFR, preserved repeated-frame positions, chunk-level restart reuse, batch-size reduction without sampling, explicit pause on decode/encode gaps and unchanged selected-evidence limits for cloud calls.

Run the complete offline backend suite, frontend tests, production build and mocked dashboard walkthroughs. Render actual local fixtures through Hypit and FFmpeg. Require synthetic event/caption placement within one output frame of the intended mapping, correct duration/coverage and agreement with the expected premix after allowing codec differences.

Then, with separately authorized paid access, compare on a fixed labeled seed set:

1. Existing workflow baseline.
2. Dense visual evidence + all-frame PE + Gemini, without new acoustic cues or Jev.
3. The same visual evidence + audio-event fusion + Gemini, with Jev disabled.
4. The same fused evidence + Jev shadow/active selection + Gemini.

Keep the Gemini model/settings fixed across arms when measuring selector or audio-fusion value. Evaluate a model upgrade separately from those changes; otherwise a better model could be mistaken for a better selector.

Measure important-event recall, lost context, cast/action correctness, false deduplication, final hook/reveal alignment, p50/p95 end-to-end latency, peak memory, clarification count and total provider cost. Freeze the benchmark set and acceptance criteria before results are inspected. Require all mandatory synthetic events retained, no known-important-event regressions on the labeled set, and a demonstrated quality or efficiency gain before enabling the additional selector by default. Benchmark scoring is developer QA, not a production scene-approval gate.

Roll out one future-run profile behind a feature flag after offline checks and separately authorized live qualification. Before deploying, take a consistent backup and protected-record/final-file fingerprints; drain only owned idle services. Verify health, one worker, unchanged protected data and no legacy run resumption. Roll back code/configuration rather than restoring an old database over newer activity.

Report separately: implemented/offline-tested, locally qualified, live-qualified, deferred and unverified. Native semantic authoring is a required release gate. MPS acceleration, reference-conditioned generation, broad multi-seed benchmarking and the minor Hypit/Node warning remain separate tasks.

## 8. What this plan does not claim

The implementation record distinguishes measured local fixture results from live qualification. No Jev cost saving, broad interpretation improvement or virality benefit is established by one synthetic benchmark or one eventual live seed. Existing footage-generation fidelity can still be the dominant quality limit.

The Hypit skill informed the single-clock approach, separate speech/cut identities and native semantic integration. Repository inspection determined the original renderer/premix hazards. Implementation changes are recorded separately; no historical jobs, provider spending or deployment are implied by this document.

## 9. Detailed audio detector and audiovisual fusion specification

### 9.1 Input, channel policy and source clock

Analyze the verified source's selected mixed soundtrack. Do not assume isolated music, voice or sound-effect stems exist. Do not install a source-separation model or purchase stem extraction as part of this change.

1. Select streams deterministically: use an explicitly saved stream selection; otherwise use a unique eligible default stream, or the sole eligible stream. Multiple equally eligible tracks are a technical ambiguity, not permission to choose randomly. Exclude attached cover art from video-frame coverage.
2. Record native stream indices, timebases, start PTS, dispositions, language, channel layout and decoded spans. Establish one source presentation timeline while preserving audio/video offsets and discontinuities.
3. Create a registered analysis derivative only when necessary. Proposed feature rate: 48 kHz float PCM, with an explicit resampling mapping. This does not improve the bandwidth of a lower-rate source. Preserve the original asset and gain; do not normalize each window or remove silence before measurement.
4. Compute energy per channel, then aggregate powers or retain channel-specific measurements. Apply the same phase-safe rule to spectral flux, bass and rhythm inputs: aggregate per-channel spectra/features, not a cancellation-prone mono waveform. Do not average stereo waveforms blindly: antiphase content can cancel and create false silence. Keep a maximum-channel peak measure for clipping/transient diagnostics.
5. Use the same selected soundtrack for acoustic features, transcription and Gemini context. Qualify Hypit's track selection or supply a registered, correctly mapped derivative; do not silently analyze one language track and transcribe another.
6. Distinguish `no_stream`, valid digital silence, quiet content, clipping, partial decoding and failed decoding. Missing measurements are null/unavailable, never fabricated zeros.

Source time for a feature comes from the decoded span's origin plus its sample position divided by its sample rate, then the explicit source mapping. Record whether the feature position denotes window start, center or a refined onset. Account for padding and resampling latency exactly once. An audio feature hop is not a video frame: 512 samples at 16 kHz is 32 ms, not 1/30 second.

Select exact visual evidence by decoded frame identity/PTS, not an assumed timestamp seek. For a sound between frames, retain the surrounding frame identities; for delayed reactions, retain the measured lead/lag rather than moving either event.

### 9.2 Measured features and cautiously named events

These are initial engineering settings to test and freeze into `audio_events.v1`, not scientifically validated thresholds. Tune on the development set before the held-out acceptance set is evaluated. A later parameter change creates a new policy identity.

| Feature | Initial implementation | Permitted interpretation |
| --- | --- | --- |
| Energy envelope / peaks | 20 ms RMS window, 10 ms hop; peak and clipping fraction in parallel | Local energy rise/fall, impulse candidate; not perceived loudness or importance |
| Spectral onset | Positive spectral-change measure; proposed 2,048-sample window at 48 kHz, 480-sample hop | Change in sound; not proven percussion, speech or a scene cut |
| Low-frequency energy | Proposed 20–200 Hz band, 4,096-sample window with the same hop; record source bandwidth limitations | Bass-energy change candidate, not proof of a drop |
| Pause / low energy | Noise-floor-aware, bounded threshold; proposed minimum interval 80 ms | Quiet interval; speech absence remains unproven without reliable context |
| Rhythm | Beat tracker over sufficiently supported repeated onsets, with local tempo consistency | `rhythmic_beat_candidate`; allow unavailable/unreliable, never force BPM for dialogue |
| Buildup / drop | Compare sustained energy, bass, onset density and spectral texture before/after a change over contextual windows | `drop_candidate` or `buildup_candidate`, not a confirmed musical transition |
| Speech-related cue | Reliable transcript passage/word boundaries plus nearby acoustic changes | `speech_boundary` or `emphasis_candidate`; never invented words or precise timing from volume alone |

For transient selection, begin with a rolling robust baseline (for example, median plus a calibrated multiple of median absolute deviation), a numeric floor and bounded adaptation. Store raw measurements as well as normalized strengths. Handle all-zero/MAD-zero intervals explicitly. Thresholds must work relative to local context without amplifying quiet noise into meaningful events.

Beat tracking, energy measurement and onset analysis can use qualified local Python routines; none requires a cloud model. Upstream functions provide measurements, not labels such as "punchline" or "funny reaction." [RMS](https://librosa.org/doc/0.11.0/generated/librosa.feature.rms.html), [spectral onset](https://librosa.org/doc/0.11.0/generated/librosa.onset.onset_strength.html), [beat tracking](https://librosa.org/doc/0.11.0/generated/librosa.beat.beat_track.html)

### 9.3 Drop candidates, silence and false positives

A single large peak is insufficient for `drop_candidate`. Require a contextual transition involving sustained changes, such as a preceding reduction/buildup followed by bass/percussion density or texture change. A compressed soundtrack can have a real drop with little amplitude increase. Preserve uncertainty when the mixed track does not support a musical interpretation.

Keep candidates for sudden music cutoffs, possible risers/whooshes, repeated acoustic motifs and phrase endings. In the first release, these remain measured pattern hypotheses or Gemini interpretations; do not add an unqualified audio-classification model to assign sound names.

Required negative cases: microphone pops, plosive consonants, clipped peaks, constant bass, applause-like noise, musical accents without picture changes and visual cuts under continuous audio. Quiet speech is not empty space. Do not remove pauses or insert effects solely because the detector found a gap.

If rhythm is unreliable, report that status and continue using other valid cues. Valid silence or missing audio permits visual analysis to continue. A broken decoder or an unreliable clock is a technical failure and must not be relabeled silence.

### 9.4 Streaming, recovery and bounded resources

- Proposed acoustic core size: 10 seconds. Sample-level features retain their full window support on each side. Drop/buildup candidates use at most two seconds of look-behind and look-ahead initially; longer musical interpretation belongs in bounded Gemini context. Persist these support limits with detector identity.
- Run rhythm estimation on fixed, source-anchored windows of at most 30 seconds: a 10-second output core plus up to 10 seconds of real context on each side. Emit only candidates owned by the core, with deterministic edge ownership. Clip context at true source edges without inventing beats in padding. Cache each window's complete inputs/results; do not call a globally optimizing beat tracker separately on arbitrary transport chunks and expect equivalence.
- A whole-file reference test must use the same anchored-window operator as streaming execution. Resume with identical window origin, required context and algorithm state; commit a core only after its required look-ahead is available or the source ends cleanly. All feature/detector chunk boundaries must preserve coverage and avoid duplicate events within declared numerical tolerances.
- Persist completed feature chunks and decoded-span coverage atomically. A detector threshold change can reuse compatible raw features; changing the selected stream or resampling policy cannot.
- Set positive limits for subprocess duration, decoded duration, queued bytes, stored feature bytes, event count and local concurrency before a job starts. Derive them from the accepted source and qualified machine profile; reject a plan that lacks bounds. Do not silently truncate data on overflow.
- Start with one encoder job and one audio-extraction job, coordinated through existing capacity accounting. Apply backpressure; no nested unbounded worker pools. Device/precision changes must match a qualified policy and cannot mix incompatible cached chunks.
- Allow at most two persisted automatic recovery attempts per failed local chunk for classified recoverable failures. Within an attempt, bounded PE batch-size reduction is permitted down to one frame. Corrupt media, unknown clocks and repeated failures pause with the affected span. These local counters are separate from provider retries, speech repairs and Gemini clarification rounds.
- Cancellation stops owned local subprocesses and leaves verified checkpoints reusable. It does not delete manifests referenced by runs or claim that a remote request was canceled.

### 9.5 Fuse moments, not just isolated frames

The pure fusion step consumes completed audio events, all-frame visual/PE evidence and the bound transcript. Its output is an ordered candidate-moment manifest with explicit evidence references, not a new scene-approval decision.

1. Retain mandatory visual coverage and all protected brief-event evidence independent of audio scores.
2. Associate cues in a bounded neighborhood. Initial near-cue search: 500 ms before and after; allow longer setup/payoff context through explicitly budgeted windows. Preserve original timestamps and observed lead/lag.
3. Keep `visual_cut`, `audio_accent`, `rhythmic_beat_candidate`, `drop_candidate` and `story_interpretation` separate. Group related evidence under a moment ID without collapsing distinct events or erasing dense cuts.
4. Rank optional evidence using reproducible rules: multimodal support, local novelty, supported speech relationship and temporal diversity. Detector strengths are not probabilities of virality. Record why each candidate was selected, retained as mandatory or omitted as optional.
5. Choose multiple useful frames where necessary: before the event, exact flash/cut frames and a clear post-event action/reaction. The loudest instant need not contain the best representative image. Sharpness ranking must not discard the only frame showing a brief event.
6. Estimate clip-local edit rhythm from repeated associations only when enough consistent evidence exists. A median lead/lag is a descriptive hint, not a rule to shift every cut. Retain off-beat edits and callbacks.
7. Send Jev bounded factual summaries with IDs and uncertainty; send Gemini actual selected frames and audio-bearing windows. The model may explain the sequence, but code still validates timestamps, bindings and coverage.

No audio strength threshold can exclude a silent flash, quiet setup or intentional repeated scene. Large evidence sets must use a recorded partitioning/selection policy. If mandatory detail cannot fit the quoted media/call limits, report `evidence_budget_exceeded`; do not silently drop it or expand the paid plan.

### 9.6 Reconstructing sound relationships in the output

An illustrative source pattern is: punchline ends, 150 ms pause, impact, reaction cut. Record which relationships appear intentional and their evidence; do not assume every measured delay is creative intent.

For the target, bind the punchline by stable segment/word identity to final TTS alignment. Place the associated visual and sound cues relative to that target anchor. If the target uses a different music bed, map musical events against the selected final audio asset, not the source song's absolute timeline. Required unresolved anchors pause only the dependent work.

Do not copy protected source music/effects merely because they were analyzed. Select already authorized/appropriately licensed assets or use the existing funded production path for replacements; new paid audio generation still needs its own quote and authority. There is no new sound provider in this handover.

Keep complete narration and effect tails; microcuts affect picture without chopping syllables or restarting the music bed. Freeze the final speech/music/effects mix and make that exact asset the Hypit sound input. This single-clock, relationship-based design follows Hypit's Script/Selection/Moment model.

## 10. Policies, records, clocks and error handling

### 10.1 Additive policy snapshot

Add `flashcut_policy.v1` metadata to new runs and bind it through experiments/plans. Do not add keys to the strict existing `run_policies.v1` parser or frozen schemas. These field names are proposed internal contracts to implement and test, not fields already available in the application.

| Policy group | Required saved values |
| --- | --- |
| `visual` | `coverage=all_frames`, exact PE checkpoint/code hashes, preprocessing policy, device/numeric mode, decoder/stream policy and batch/resource limits |
| `audio` | `audio_events.v1`, selected stream policy, sample/channel mapping, windows/hops/bands, thresholds, context, detector versions and chunk/recovery limits |
| `fusion` | `av_fusion.v1`, mandatory-coverage rules, cue neighborhoods, diversity/priority rules and detail-window limits |
| `decision` | Jev enablement/mode (`shadow` initially), pinned model, rubric hash, call/token caps and recorded conservative fallback |
| `understanding` | Intended `gemini-3.8-flash`, qualified route/account/region reference, prompt/result versions, sampling settings and cumulative media/call limits |
| `editorial` | Anchor/offset policy, rational target clock, caption/mix versions and actual soundtrack bindings |
| `renderer` | `hypit_primary.v1`, qualified runtime/compiler/capabilities; legacy routing remains separate |

Clarification limit is two rounds, but the paid plan must also persist concrete maxima for calls, images, aggregate window duration, bytes/tokens and output allowance. Compute these before authorization using the actual seed and qualified provider limits. Refuse submission if a maximum is absent or exceeded; a newly named window does not reset run-wide totals. Do not hardcode current public provider limits as eternal constants.

### 10.2 Required immutable records

| Record | Minimum contents and invariants |
| --- | --- |
| `clock_manifest` | Source ID/hash, selected stream indices, native timebases, common origin, decoded audio spans, per-frame PTS/duration, trim/resample mappings and exact extractor identity |
| `frame_manifest` | Ordered decoded-frame IDs, actual timestamps/hashes, completed chunk refs, embedding bindings, coverage totals and clean-decode completion evidence |
| `audio_manifest` | Source/stream/clock identity, processed sample spans, channel/features policy, feature chunk hashes, events, event strength/uncertainty, audio status and completeness |
| `moment_manifest` | Input manifest/transcript hashes, candidate IDs, source intervals, separate audio/video anchors, lead/lag, mandatory/optional status, chosen frames/windows and selection rationale |
| `understanding_result` | Exact submitted evidence IDs/hashes, prompt/model/route, operation identity, validated observations, unresolved questions and local-to-source mappings |
| `editorial_plan` | Variant/draft revision, target word/action/music anchor IDs, resolved final-frame intervals, valid clip ranges, soundtrack bindings, intended relationships and dependent work IDs |

Keep large embeddings/features outside normal status responses and database rows; store registered content-addressed chunks with lightweight manifests. Records become visible only after files are durable, hashes verify and the current revision binding is still valid. A crash between staging and publication can leave an unreferenced temporary bundle, not a half-complete live record.

Use structured validation with explicit required fields, enums, numeric bounds and deterministic serialization. Reject unknown candidate references, invalid ranges, non-finite values and mismatched inputs. Treat raw provider replies as diagnostic evidence, never executable instructions. Preserve old bundles; garbage collection must prove an artifact is unreferenced and stay outside this initial implementation unless already supported safely.

### 10.3 Example event semantics

Illustrative values below are not observed facts from a user's video:

```json
{
  "event_id": "audio-event-42",
  "kind": "drop_candidate",
  "source_span_id": "audio-span-0",
  "onset_sample": 208800,
  "sample_rate": 48000,
  "source_time_s": 4.35,
  "timestamp_convention": "refined_onset",
  "support": ["low_energy_before", "bass_change", "sustained_onset_density"],
  "interpretation_status": "unconfirmed",
  "mixed_track": true
}
```

This example assumes a zero-offset continuous span. Real records use the saved span mapping. Associate it with a separately measured visual cut and their signed offset; never change `source_time_s` to make the cut appear synchronized. Strength/confidence fields, if present, must identify their measurement/calibration method rather than masquerading as truth probabilities.

### 10.4 Stage states and recovery behavior

Use existing run/job states for orchestration and expose these additive substage facts:

| Condition | Substage outcome | Allowed action |
| --- | --- | --- |
| No audio stream | `not_applicable_no_stream` | Continue visual work without fabricated transcript/audio events |
| Valid silence or no detected candidates | `measured_no_events` | Continue; retain visual evidence and recorded audio status |
| Unstable rhythm | `rhythm_unreliable` | Omit beat claims; retain other valid acoustic cues |
| Local work queued/encoding | `waiting` / `processing` | Show real counters; respect capacity and cancellation |
| Decode fails/truncates | `decode_failed` | Bounded classified local recovery, then specific technical pause |
| Clock/stream mapping ambiguous | `clock_mapping_unavailable` | Pause; never estimate offsets from nominal FPS |
| Source/revision changes | `stale` | Discard publication of late results; retain immutable prior evidence |
| Limits exhausted / all-frame PE incomplete | `resource_limit_exhausted` / `coverage_incomplete` | Pause with affected range and count; no hidden lower-FPS mode |
| Optional Jev unavailable or malformed | `advisory_unavailable` | Use saved conservative selection; record any unresolved paid outcome separately |
| Unknown paid submission | `provider_outcome_unknown` | Reconcile only; never automatically resubmit or erase its hold |
| Required Gemini route unqualified | `provider_not_qualified` | Pause before submission; no silent model/transcript-only substitution |

All transitions and counters must survive worker restart. Existing application-wide unknown-operation/budget enforcement can still block subsequent paid work; an optional Jev fallback does not override it. Distinguish recoverable observation failure from submission uncertainty.

## 11. Concrete module interfaces and file map

Paths below describe the original interface seams. The implementation record lists the actual installed modules, tests and adapter package. Keep one sequential implementation writer.

### 11.1 New deep module and internal seams

Propose `modules/factory/analysis/source_evidence.py` as the main module. Its interface takes a verified source/revision binding, immutable policy snapshot, existing checkpoint/cancellation context and injected local adapters. It returns either a complete immutable evidence-manifest reference, resumable progress or a typed technical failure. It does not call paid models or mutate the seed's historical transcript.

Internal adapters should cover real variability: FFmpeg decoding versus a synthetic test decoder, PE inference versus deterministic test embeddings, and real feature extraction versus supplied synthetic features. Do not expose a large collection of frame-by-frame methods to every caller or build a generic plugin framework for hypothetical providers.

Keep fusion pure: manifest-bound observations plus policy in; validated candidate moments and selection explanations out. Paid Jev/Gemini effects run through the existing durable execution interface, outside local extraction. This separation makes offline tests incapable of accidentally invoking a provider through an encoder helper.

### 11.2 Proposed implementation files

| New file / module | Responsibility |
| --- | --- |
| `analysis/source_evidence.py` | Source/revision binding, local stage coordination, checkpoints and atomic bundle publication |
| `analysis/evidence_policy.py` | Versioned policy validation/defaults and stable identity generation |
| `media/source_clock.py` | Detailed stream selection, PTS/sample mappings and decoded-frame identities without breaking legacy `Probe` |
| `media/audio_events.py` | Streamed phase-safe acoustic features, bounded detectors and cautious event records |
| `analysis/frame_encoder.py` | Pinned PE adapter, all-frame batch processing and qualified backend readiness |
| `analysis/event_fusion.py` | Pure audiovisual candidate association, context/coverage preservation and bounded selection |
| `analysis/editorial_events.py` | Target anchor resolution, exact frame intervals and dependency binding |
| `providers/jev.py` | Qualified, sanitized Jev transport with SDK automatic retries disabled and strict result parsing |

These are small modules with substantial behavior, not one class per event. Keep data validators beside the owning module or an internal records file; do not modify frozen external schemas.

### 11.3 Existing integration touchpoints

| Existing path | Required change / reuse |
| --- | --- |
| `analysis/deep.py`, `services/app.py`, `services/worker.py` | Reuse revision/edit-token-bound enqueue, source intake and immutable transcript; attach separate enrichment |
| `autorun/service.py`, `autorun/policies.py` | Save future-only policy, advance enrichment substages, consume exact complete manifests; preserve legacy policy parser |
| `analysis/vertex.py` | Versioned enriched/full-context and targeted-window tasks; actual media binding, stream consistency, quotes and strict validation |
| `services/effect_work.py`, `execution/effects.py`, `providers/configured.py` | Durable Jev/Gemini identities, account/qualification gates, reservations and restart/unknown protections |
| `audio/alignment.py`, `audio/mix.py` | Reuse final TTS timing and authoritative premix; attach target cues without replacing verbal authority |
| `services/worker.py`, `templates/capabilities.py` | Agree on saved Hypit-first renderer policy; compile the actual premix asset |
| `composition/compiler.py`, `composition/gate.py` | Bind editorial events/assets; qualify frame-precise syntax and local-only rendering capabilities |
| `rendering/service.py`, `rendering/hypit_build.py` | Reuse build identity, observation, retrieval and uncertain-outcome recovery |
| `quality/service.py`, `creative/context.py`, `delivery/service.py` | Add correct intended-event context; retain authoritative final binding and verified delivery |
| Dashboard `features/autorun/AutoRunScreen.tsx`, `features/analysis/AnalysisScreen.tsx` | Profile/readiness, real substage counters and optional evidence timeline |
| Dashboard `features/compare/CompareScreen.tsx` | Correct revision, labels and QC state; optional event markers, not a new approval screen |

Expose additional fields through existing run/detail/status interfaces. Resolve media through the existing authenticated artifact route; do not invent a public bucket, bypass session/CSRF controls or put local filesystem paths/secrets into client diagnostics. Keep event/detail collections lazy, scoped and bounded; do not restore whole-dashboard polling.

## 12. Work-package dependencies and deliverables

| Order | Package | Required deliverable before advancing |
| --- | --- | --- |
| 0 | P0: baseline, protected-state inventory and prerequisites | Baseline report, reproducible premix/routing tests, compatibility inventory, feature flags disabled |
| 1 | P1: detailed clock and immutable evidence | Clock/frame manifests; source/revision race and crash tests; unchanged legacy behavior |
| 2 | P1a: audio feature extraction | Typed events, streaming/chunk checkpoints and audio negative-case tests |
| 3 | P2-local: every-frame PE | 900/900 synthetic-frame coverage, no silent degradation, restart/memory evidence |
| 4 | P1a-fusion/P2-Jev | Deterministic moment selection, strict text-only adapter, fake-provider tests; Jev shadow semantics |
| 5 | P3: enriched Gemini | Actual-media payload tests, separate window response contract, bounded quotes/refinement and unknown-operation tests |
| 6 | P4/P5: editorial anchors and native Hypit | Script/SemanticTake/Selection/Moment, measured target timing, premix parity, actual local renders and cache invalidation tests |
| 7 | P6: dashboard/QC/delivery integration | Mocked walkthrough, correct waiting/error states and no false creative approval |
| 8 | Qualification and rollout | Full offline suite/build, protected fingerprints, separately authorized live results, gated future-run enablement |

The chronological table is the builder sequence. Audio and PE runtime jobs may overlap only after their interfaces and capacity rules are independently tested. Commit logical changes only if requested/appropriate to the active workflow; never sweep unrelated dirty files into a patch.

For every package, record: requirements covered, reproducing tests, files changed, compatibility decisions, exact verification results, known gaps, remaining paid qualification and a reversible code/configuration rollback. Update the implementation tracker only after actual evidence exists; this handover is not a passing test report.

## 13. Required regression and acceptance matrix

Create new tests outside frozen fixtures; generate synthetic audio/video in temporary directories. Proposed filenames are additions, not existing test claims.

| Test group | Required cases | Acceptance |
| --- | --- | --- |
| `test_factory_source_clock.py` | Nonzero A/V offset, audio trim/priming, VFR, 24/25/30/30000:1001 rates, multiple tracks, no audio | Correct saved stream and sample/PTS mapping; no nominal-FPS substitution |
| `test_factory_audio_events.py` | Impulse/burst, 44.1/48 kHz, mono/stereo/antiphase energy AND spectra, silence, quiet speech, clipping, missing/corrupt audio | Correct measured categories; exact sample/PTS mapping and detector-specific localization bounds as specified below |
| Audio interpretation negatives | Plosives, isolated clicks, constant bass, compressed musical transition | No automatic scene/drop labels from spikes; supported changes remain candidates with uncertainty |
| Chunk/restart | Event across chunk edge, pause spanning chunks, cancellation, process restart | Whole/chunked results equivalent within frozen tolerance; each event once; no incomplete success |
| `test_factory_frame_encoder.py` | 900-frame clip, identical frames at different times, OOM, missing/corrupt weights, stale chunks, VFR | Every decoded position covered; matching chunks reused; no skipped frames or hidden model change |
| `test_factory_av_fusion.py` | Silent two-frame flash, quiet payoff, whoosh before cut, impact after action, repeated image/different narration | Mandatory events retained; observed offsets unchanged; context survives optional ranking |
| `test_factory_jev.py` | Invalid/unknown IDs, instruction-like transcript, malformed output, timeout, refusal, shadow mode | Strict allowlists; no authority escalation; no unknown replay; shadow mode leaves media selection unchanged |
| Gemini enrichment | Actual image/window hashes, window offsets, overlapping windows, missing coverage, oversized payload, exhausted round/call cap | Correct media reaches adapter; no stale effect result or false full-video coverage; no hidden extra call |
| `test_factory_editorial_events.py` | Seed reveal at 1.2 s versus target at 1.8 s, duplicate phrase, removed anchor, trim/rate/padding | Target alignment wins; stable word IDs; transformations applied once; unresolved required anchors pause |
| Invalidation | Audio threshold, transcript, encoder, policy, selected frame/window, final soundtrack changes | Only dependent stages rerun; no stale render/QC inheritance; old records immutable |
| Existing renderer tests plus additions | Exact flash pixels, phrase text/margins, original-stem/premix mismatch, delayed accent, build recovery | Actual files, not mocks, establish intended frames/audio and no duplicate/doubled sound |
| Dashboard tests | Known/unknown totals, stale selection, waiting, blocked span, optional Jev failure, no-stream state | Honest counters/actionable messages; no new scene gate, no false approval or completion |
| Historical/authority protection | Legacy policy records, paused run, completed finals, reservations, publishing disabled | Protected records/files unchanged; no paid call without applicable authority |

For renderer fixtures, inspect frames immediately before, inside and after a two-target-frame event. Do not settle for matching file duration. Check complete rendered caption text/layout and the decoded audio's onset, gain/ducking and duration against the intended premix, allowing documented codec tolerance. Verify picture cuts do not cut narration syllables.

Separate clock correctness from detector accuracy. Sample-to-source conversion should be within one analysis sample plus independently measured decoder/resampler error, before output-frame quantization. Feature-window centers and padding offsets have exact testable conventions. Event localization tolerances are detector-specific: initial synthetic budgets may allow the relevant window duration plus one hop; freeze each tolerance before qualification. A tighter one-10-ms-hop physical-onset claim requires an implemented and tested onset-refinement step. The 42.7/85.3-ms spectral/bass windows do not inherently provide 10-ms localization just because their hop is 10 ms.

Current `tests/test_factory_phrase_renderers.py` covers actual local Hypit and FFmpeg output, but its geometry/frame-count assertions are insufficient for all the new guarantees. Extend coverage. A Hypit-unavailable `VALIDATION GAP` skip blocks release of Hypit-first mode; it is not a green acceptance result.

Benchmark the four arms in section 7 on the same labeled seed set. Split development and held-out cases, and freeze thresholds/acceptance criteria before evaluating held-out results. Report event precision/recall, temporal errors, false drop claims, lost-context examples, full-frame coverage, CPU/MPS time/memory and total paid usage. Do not claim savings from Jev token price alone. Human benchmark annotation is development QA, not a restored user review step in production.

## 14. Developer runbook and rollout checklist

### 14.1 Start safely

1. Read repository `AGENTS.md`, `GOAL.md`, `BUILD_PLAN.md` and `docs/viral-video-factory-handover.md`, honoring their factory scope banners. Keep one sequential builder and frozen contracts.
2. Read this handover and inspect current source; line numbers and installed dependencies can change. Record branch, working-tree changes and baseline failures without reverting the user's work.
3. Identify protected run/export/receipt records and final files read-only. The historical count is a scope reminder, not a substitute for resolving exact IDs. Do not print credentials or broad configuration contents.
4. Keep development/tests in isolated temporary roots, use fake providers, disable network/downloads in unit tests and ensure live-test enablement is absent. Do not use the active dashboard's database as a test fixture.
5. Reproduce prerequisites and implement packages in section 12 order. Stop only the affected work for a genuine blocker; report pre-existing failures separately and continue safe independent documentation/tests where possible.

### 14.2 Verification commands

Commands below are operating instructions. Consult the implementation record for actual executions, results and any remaining gaps.

```bash
# Repository root; external providers mocked and live-test opt-ins disabled.
make test
npm --prefix apps/factory-dashboard test
npm --prefix apps/factory-dashboard run build

# Focused existing composition/render coverage; add new tests from section 13.
.venv/bin/python -m pytest tests/test_factory_composition.py tests/test_factory_rendering.py tests/test_factory_phrase_captions.py -q
.venv/bin/python -m pytest tests/test_factory_phrase_renderers.py -q -rs

# Inspect patch hygiene and frozen-contract changes; never reset files to make these pass.
git diff --check
git diff --exit-code -- schemas tests/fixtures
```

If frozen paths were already dirty at entry, compare against the recorded entry state; preserve/report unrelated changes instead of claiming this patch caused them. Also inspect new/untracked files, which `git diff` alone does not cover.

`scripts/factory_qualify_hypit.py` offers richer isolated local rendering checks. Inspect its current options before use and give it a newly allocated, previously nonexistent output subdirectory under a validated temporary parent. Never target the live factory root. Synthetic test renders are test artifacts: no Drive upload or provider generation belongs in offline qualification.

### 14.3 Qualification gates

- **Local:** verify exact PE weights/license/preprocessing and CPU/MPS behavior, every-frame coverage, detector timing and resource bounds. No model download in a test or normal job.
- **Jev:** qualify account access, response schema, usage evidence, timeout semantics and data handling. Start paid shadow validation only under a new explicit budget. Shadow mode itself is not free and must not submit extra Gemini work.
- **Gemini:** qualify `gemini-3.8-flash` on the actual Google route, supported parameters, image/video/audio payloads, sampling, input limits, response schema, quotes and recovery. API availability is not proof of a successful local integration.
- **Hypit:** qualify exact installed runtime/compiler syntax, real frame/audio output and build recovery. Native semantic bridge qualification remains separate from frame-compiler qualification.
- **Promotion:** document a measured quality or efficiency benefit without required-evidence loss, no protected-state changes and no unresolved release-critical tests. No qualification flag may be invented merely to let an automated run continue.

### 14.4 Deployment, verification and rollback

Deployment is included in the approved implementation, but remains gated on passing offline checks and one freshly quoted, authorized live acceptance run on `89iXPZsKn9M`. Historical spending approvals do not authorize it. The acceptance run must produce four current QC-passed, Compare-visible, verified-Drive-delivered finals before general enablement.

1. Record original dispatch/drain state. Use the existing drain operation to prevent new work; do not auto-resume paused jobs. Verify active jobs and owned processes rather than assuming idle.
2. Inspect and use `scripts/factory-rollout-snapshot.py` for a consistent SQLite backup/integrity check and protected fingerprints; `scripts/factory-qa-audit.py` supplies read-only record/final-file comparisons. Use an explicit validated destination with owner-only permissions.
   After adding a new acceptance run, use `scripts/flashcut-protected-check.py`
   with the baseline backup, current database and artifact root: it permits new
   rows but verifies every old protected row, final binding and final file.
   An inspection failure is unresolved verification, never proof of unchanged
   state. This tool does not restore or edit either database.
3. Deploy only to idle, verified owned API/worker processes. Do not blanket-stop Hypit helpers or shared dashboard services. Failed port/process inspection means verification unavailable, not ports free.
4. Verify API health, exactly one owned worker, logging/permissions, intended feature flag/profile defaults, unchanged legacy paused states, unchanged protected record/final hashes and no unexpected provider submissions.
5. Restore dispatch only to its previous permitted state. New profile readiness is not authority to start a generation run.
6. If a check fails, roll back only this change's code/configuration/feature flag without erasing unrelated work. Leave additive records and newer activity intact; never restore an old database over newer records. Runs already saved under a new version require that version's reader or an explicit pause, not reinterpretation as legacy.

### 14.5 Final implementation report

Report each package as `not_started`, `implemented_offline`, `locally_qualified`, `live_qualified`, `deferred` or `blocked`, with exact tests/artifacts and remaining limitations. State separately whether the app was deployed and whether any paid operation occurred. Include protected-fingerprint verification and rollback notes. Do not mark the whole feature complete while a required renderer or provider route remains unverified.

## 15. Primary references and remaining decisions

Consult these primary references at implementation/qualification time; pin versions rather than assuming live documentation matches the installed runtime:

- [Jev model identity and text-only inputs](https://docs.typesafe.ai/models); [Python retry controls](https://docs.typesafe.ai/sdk/python/api/retries).
- [Meta PE-Core-S16-384 checkpoint](https://huggingface.co/facebook/PE-Core-S16-384); [official Perception Encoder implementation](https://github.com/facebookresearch/perception_models/blob/main/apps/pe/README.md).
- [Gemini 3.8 Flash model](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-8-flash); [video input/sampling](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/capabilities/video-understanding).
- [FFmpeg audio statistics](https://ffmpeg.org/ffmpeg-filters.html#astats); [silence detection](https://ffmpeg.org/ffmpeg-filters.html#silencedetect).
- [librosa RMS](https://librosa.org/doc/0.11.0/generated/librosa.feature.rms.html), [onset strength](https://librosa.org/doc/0.11.0/generated/librosa.onset.onset_strength.html) and [beat tracking](https://librosa.org/doc/0.11.0/generated/librosa.beat.beat_track.html). These versioned pages explain algorithms, not a mandatory dependency pin.
- [PySceneDetect detector behavior](https://www.scenedetect.com/docs/head/api/detectors.html).
- [Hypit upstream](https://github.com/hypit-ai/hypit); use the installed package vocabulary and project-owned launcher for exact supported syntax.

Settled: no Rust; PE on every decoded frame; audio-event fusion; Jev advisory; Gemini audiovisual interpretation; Hypit-first future profile; replacement narration controls final speech timing; no restored scene approval; existing records protected.

Engineer-owned qualification decisions: exact compatible dependency/checkpoint revisions, portrait-preserving preprocessing, CPU/MPS numeric policy, calibrated detector thresholds, source-specific bounded media budgets and supported Hypit semantic surfaces. Record these before enabling the profile. Ask the user only for missing secure account setup, separately scoped paid validation or a material scope change—not to reapprove ordinary offline engineering choices.

Not proven by this handover: real-world meme-quality improvement, lower total cost, Mac throughput, new-route account readiness, automatic reference-character continuity or viral performance. Source analysis and editing fidelity can improve while generated-footage quality remains the limiting factor.
