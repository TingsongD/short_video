# Speaker-aware recreation

The earlier a2wQbuKVWSg deliveries used one narrator. Their prior technical QA did not verify preservation of multiple source speakers; they need a new speaker-aware adaptation before they meet this requirement. Existing delivered files and paid receipts are preserved.

## Implementation

New automatic runs require WhisperX STT/alignment plus pyannote speaker diarization before paid analysis or generation. The repository-owned WhisperX launcher wraps the installed engine without modifying installed packages. It loads `pyannote/speaker-diarization-community-1` lazily and retains the model for subsequent requests. Plain transcription remains saved as evidence when diarization is unavailable, but it cannot pass the new run gate.

Speaker labels follow first occurrence (`SPEAKER_00`, `SPEAKER_01`, …). Word attribution needs at least 80% interval support from a unique speaker. Overlapping voices and unassigned words require review; nearest-speaker filling is deliberately not used. Original STT segments and acoustic diarization intervals are retained alongside the speaker-separated transcript. These labels identify voices, not the identity of an on-screen person.

Visual scenes containing several speaker turns are subdivided at speaker changes on the 30 fps timeline, retaining their scene/cast evidence. Existing scene boundaries inside inter-speaker silence are reused to avoid tiny empty shots. Each spoken segment has a frozen speaker and voice assignment. Script requests preserve the dialogue perspective, and a segment without an assignment is blocked before synthesis.

The selected primary voice goes to the first speaker. Other speakers receive distinct voices from the existing account catalog, or explicit `speaker_voices` overrides. The UI exposes optional assignments and shows saved character voices. Casting may change before script adaptation; changing it after that requires a new run. Automatic choices establish distinct voices; they do not certify gender, acting suitability, or visual-character identity.

TTS deduplication and recovered-request matching include the voice as well as text, model, language and settings. Identical words from different characters cannot share the wrong waveform. Fit/attachment checks enforce the selected voice; final editorial passages carry the speaker/voice binding. Measured-duration repairs compare actual text, not the new voice/text cache hash. Existing legacy runs retain their original policy.

## Validation

- Two-character integration rendered all four variants with distinct voice bindings, including identical sentences spoken by different characters.
- A second integration rendered speaker changes within a single visual scene, checking separate audio, continuous segment boundaries and captions.
- A plain-STT integration paused before any paid provider attempt.
- Managed WhisperX-environment smoke checks passed with mocked inference: word labels, one-time model loading/reuse, and missing-access behavior. No model download or live inference is claimed.
- Test logs are under `data/factory-qa/speaker-diarization/`; broader regression evidence is recorded at completion below.

## Live activation and remaining prerequisite

`HF_TOKEN` was not configured and the pyannote model was not cached at the initial check. Accept the [pyannote model access terms](https://huggingface.co/pyannote/speaker-diarization-community-1) and add a Hugging Face read token as `HF_TOKEN` in gitignored `config/secrets.toml`. Never paste the token into chat. New source analysis must run against the updated WhisperX service; Resume from its speaker-review pause requests a new local evidence revision.

The reviewed transcript import route can retain explicitly supplied speaker labels/status and diarization provenance for uncertain turns. Overlapping dialogue must be resolved explicitly; this implementation does not automatically separate concurrent voices or infer faces from acoustic clusters. Very short turns that cannot form valid timed segments remain an honest review/fit gate. No voice cloning or automatic lip-sync certification is performed.

No paid regeneration was performed for this implementation. The four prior Drive videos remain the previous single-voice versions. The current seed's existing cumulative spend and 7,000-credit cap still apply to any follow-up remake; prior costs and holds must remain included.

Primary references: [WhisperX](https://github.com/m-bain/whisperX), [pyannote community model](https://huggingface.co/pyannote/speaker-diarization-community-1), [ElevenLabs account voice catalog](https://elevenlabs.io/docs/api-reference/voices/search).

## Completion checkpoint

Implemented and activated in the local application. The API reports live mode with the sole worker connected; the WhisperX health endpoint advertises `whisperx-pyannote.v1` and the community diarization model. The browser's Auto screen shows the new speaker behavior and optional assignments. No run was launched during verification.

Final targeted regression: **41 passed in 75.04s**, including missing-diarization recovery through a fresh evidence revision and both complete multi-speaker rendering cases. Earlier broad affected-backend run: **117 passed, one failed** against the pre-repair in-memory service. That failure exposed a text-versus-cache-hash comparison in speech-fit recovery; it was fixed and the exact test passed in the final 41-test run. A separate three-test speech-repair regression also passed. The broad log is retained and is not described as an uninterrupted all-green run.

Frontend: **82 tests across 16 files passed**; TypeScript/Vite production build passed. Managed WhisperX adapter smoke checks passed with mocked inference and network denied. The optional configuration-key shape check passed, `git diff --check` passed, and frozen legacy schemas/fixtures were unchanged by this work.

Live source diarization, speaker/visual-role review, voice auditions and remade video QC/delivery remain pending `HF_TOKEN` and model-access setup. No live pyannote result or updated Drive delivery is claimed. The local API/worker remain running for continuation; current retained tool sessions are API14873 and worker26291.

## Live access test after token setup

On 2026-09-24 UTC (2026-09-23 local), the configured token successfully authenticated with Hugging Face. Both the local WhisperX service and the application/worker were healthy. However, the authenticated download of `pyannote/speaker-diarization-community-1/config.yaml` returned HTTP 403: the token's account is not in the model's authorized list. This is a model-access prerequisite, not a failed token login. Accept/request access to this exact model with the account that owns the configured token, then repeat the access test.

Sanitized results are saved in `data/factory-qa/speaker-diarization/live-access-check.json`, `live-auth-diagnosis.json`, and `live-model-denial.json`. No credentials or authorization headers are recorded. Real source diarization and new generation were not started because the required model download is still denied; no new paid requests were made.

## Successful access and first real seed inference

After the user accepted access on the matching account, the authenticated model configuration download passed at 2026-09-24 03:33 UTC. The live local service then processed the existing `a2wQbuKVWSg` source in **64.88 seconds**, including initial model setup. The original source and historical evidence were retained.

The result contains **four acoustic groups and 164 words**: 160 automatically assigned and four unassigned. This is successful model execution, not a certification of four distinct character identities or of all assignments. The four flagged words are `account.` (22.204–22.684s), `Not` (25.084–25.224s), `miles.` (31.306–31.606s), and `Ladies` (32.870–33.070s). The result is correctly `needs_review`, and an explicit call to the production diarization gate confirms it blocks generation. Do not fill these words by proximity or equate automatic labels with human verification.

Raw STT also repeats previously corrected source wording errors. The existing user-confirmed corrections remain authoritative; this immutable machine result does not supersede them. Speaker/character review, alignment around turns, casting and remake QC remain outstanding. No paid generation was started during this test.

Evidence: `data/factory-qa/speaker-diarization/live-source-transcript-20260924T033322Z.json`, `live-test-result-20260924T033322Z.json`, and `live-test-review.md`.

## Variant B remake delivered under explicit review waiver

The user requested skipping the four-word speaker review and recreating **only B**. That instruction is recorded in `data/production/seed-a2wQbuKVWSg-variant-B-speakers-v2/production.json`; the raw diarization remains `needs_review`. This task-specific production decision does not disable the automatic source gate or falsely mark acoustic evidence human-verified. Sentence context assigns `account.`, `Not` and `miles.` to group 01 and `Ladies` to group 00; the complete sentence “The miles are the goal” stays with group 01.

The standalone B revision retains its existing hook, corrected wording and 37 caption-free generated clip assets. Ten new dialogue takes use Sarah (00), Roger (01), Jessica (02) and Bill (03). All takes fit at their natural speed within the existing three scenes. Per-voice gain balances the mix without changing timings. New final-word alignment drives 33 caption phrases. No new picture generation was needed; A/C/D and the original experiment's Compare/delivery history are unchanged. The revised B is delivered separately at the link below.

Live output STT recovered the full script and four acoustic groups. Its short “Well, we all need a hobby” take was clustered with Sarah despite its recorded Jessica synthesis identity; this demonstrates the remaining limitation of acoustic clustering on short similar voices, not reuse of the wrong TTS artifact. Source-group identities and exact visible-character/lip synchronization remain uncertified, consistent with the requested waiver and reuse of B's footage. No subjective listening certification is claimed.

Final QC passed: 720×1280, 30 fps, 1,723 frames / 57.433333 seconds; full decode, every frame interval and zero-offset comparison against the balanced mix. All 33 caption midpoint states and seven full-frame scene samples were visually reviewed for legibility, contrast and clipping. Final SHA-256: `9994312ee794500b2afb1f4580d636d59e5810461cc51c7501c90b5c739bc67c`.

[Revised B with four voices](https://drive.google.com/file/d/1Sw-qhVFqE5uxd40Z8YBuQEDrSmi8XSMy/view) is verified in the original authorized factory folder: matching parent, filename, 9,327,768 bytes and MD5. The first local render submission created no build because the runtime was not selected; its receipt is preserved. The completed render used the existing shared runtime; all disposable render children exited and no task-owned listener survives. Shared API/worker, WhisperX and the pre-existing Hypit worker remain available.

New cost: **723 ElevenLabs credits**, no new USD provider commitment. Complete seed task totals now **US$54.094415 plus 2,593 credits**, including prior holds, within the original US$200 / 7,000-credit ceilings. Production receipts include `cost-receipt.json`, `qc.json`, `upload-receipt.json` and `cleanup-receipt.json`; sources, final video and voice assignments are retained in the same production folder.
