# Jev and lightweight video-perception research for Viral Video Factory

Research date: 2026-09-21. Scope: primary-source research and read-only code inspection; no installation, provider calls, pipeline changes, or Rust. Recommendations below are proposals, not measured improvements in this app.

## Recommendation

Benchmark Jev as an optional, narrow text-decision adapter inside the existing Python workflow. Its best initial jobs are evidence-window prioritization and semantic completeness checks over structured observations. Keep pixels/audio with the perception models, prose with the script model, arithmetic and authority with Python, and final visual QC with the existing artifact-bound QC path.

For semantic frame selection, benchmark `facebook/PE-Core-S16-384` first against `wkcn/TinyCLIP-ViT-40M-32-Text-19M-LAION400M`; use PySceneDetect for actual cut candidates. This is a fit-based recommendation, not a measured speed or accuracy winner on this Mac. Details and primary sources follow below.

Do not replace the workflow engine or make Jev a new mandatory scene-approval gate. A local-rule baseline remains necessary to establish whether adding an API call actually saves time or cost.

## Verified product facts

The current documented model is `jev-1.13.0`; `jev-latest` and `jev-preview` currently resolve to it. Input is text/JSON, not images, audio, video or raw embeddings interpreted as visual evidence. Published input pricing is $0.042/million tokens, with free outputs. Limits are 64k tokens overall and 32k for state plus the longest question. Published rate limits are 1,200 requests/minute and 250,000 tokens/second, explicitly subject to change during early access. Pin the resolved version when evaluating thresholds. [Models](https://docs.typesafe.ai/models)

The endpoint is `POST https://api.typesafe.ai/v1/systemone`, receiving state, model and named questions. Choice selects from up to 255 alternatives; Score returns a probability-weighted result across 2–10 ordered rubric levels; Noul returns a yes-probability. Choice/Score expose distributions and confidence; Noul does not have a separate confidence field. Crucially, question-map keys are not used for inference: instructions must explicitly identify the candidate or state path. [API reference](https://docs.typesafe.ai/api)

Questions sharing state are independently evaluated in parallel. A question cannot read another answer from the same request. Batch independent factors; combine them in Python, or make a second stage only when it truly needs first-stage outputs. Keep state compact rather than merging unrelated tasks into a huge batch. [Introduction](https://docs.typesafe.ai/introduction), [Fan-out](https://docs.typesafe.ai/patterns/fan-out)

Confidence summarizes a probability distribution, not an independently verified probability of factual correctness. Thresholds need calibration against this application's labeled examples, especially for expensive actions. [Confidence](https://docs.typesafe.ai/confidence)

TypeSafe reports 70–500 ms end-to-end responses; its published tests generally originate on the US West Coast. These are vendor measurements, not an app-level SLA. Its own evaluation caveats say headline speed/cost gains are likely toward the high end of real-world gains. [Launch and evaluation caveats](https://typesafe.ai/blog/introducing-system-one-models-and-jev)

## Highest-value uses, in order

| Proposed use | State and atomic question | What Python still owns |
| --- | --- | --- |
| Prioritize evidence windows | Transcript excerpt, visual tags/descriptions with provenance and uncertainty, scene-neighbor summaries and computed event flags; ask whether a window contains a distinct action, introduction or payoff | Mandatory temporal coverage, frame timestamps, deduplication distances, candidate cap and final selection |
| Check analysis completeness | One scene's descriptions, transcript and observation evidence; separately ask whether action/cast/speech meaning is underspecified or contradictory | Schema validation, source bindings, complete timeline coverage and whether a bounded targeted visual reinspection is permitted |
| Classify creative function | Choose hook/setup/demonstration/reaction/payoff/CTA/uncertain from supplied semantic evidence | Preserve scenes and intentional repeats; these labels are not measured virality predictions |
| Check replacement script intent | Original passage, variant hypothesis and candidate rewrite; ask separately about meaning preservation, sentence completeness and hypothesis consistency | Text generation, measured speech fit, duration arithmetic, safe alignment and captions |

First-stage visual selection must not ask Jev to infer what happens from a vector or a motion number. Embedding similarity, frame quality, timestamp distance and audio-energy calculations belong locally. Jev becomes useful when it receives meaningful labels, transcript or trustworthy descriptions. If producing those descriptions costs more than any calls avoided, this route loses its economic advantage.

The official re-ranking cookbook supports a shortlist-then-judge pattern, but its legal-passage results do not establish video-selection quality. Treat this application as a new evaluation domain. [Re-ranking example](https://docs.typesafe.ai/cookbooks/rerank_typesafe)

## Fit with current code

- `modules/factory/analysis/deep.py::_stage_evidence` already extracts a full overview and denser grids around the first six cuts. Enrich this evidence manifest rather than starting another orchestrator.
- `modules/factory/analysis/vertex.py::analyze_media` currently submits the actual video. Jev-selected evidence would need explicit wiring into a future version of that request; a JSON decision alone cannot improve pixel understanding.
- `modules/factory/creative/context.py::validate_context` already enforces cast and scene bindings. Keep these deterministic checks; Jev may identify semantic doubts, not override them.
- `modules/factory/execution/effects.py` binds paid requests, prices and authority. Add Jev through the same controlled-effect seam if implemented, with request identities including source/transcript/evidence hashes, pinned model, rubric and policy versions.
- `modules/factory/execution/retry.py` deliberately refuses blind retries of ambiguous submissions. Do not bypass it because individual decisions are inexpensive.

## Safety, failure and privacy requirements

The official limitations identify weak arithmetic/counting, large irrelevant state, indirection and susceptibility to adversarial input. Do not let seed transcripts or on-screen instructions become privileged workflow commands. Do not use Jev for timestamp arithmetic, budget decisions, operation reconciliation or script generation. Typed output does not mean correct output. [Known limitations](https://docs.typesafe.ai/model-jaggedness/jev-1.13)

A Python SDK is documented. Its retry policy can retry connection/time-out failures and can be disabled using `max_retries=0`; the application should own persisted retry decisions. API docs recommend backoff for explicit 429/529 responses, but that is not evidence that every lost acknowledgment is safely replayable. No provider idempotency-key contract, result-by-request lookup, or duplicate-billing guarantee was found in the reviewed endpoint documentation. Qualification must settle these before automatic paid timeout retries. [Retry configuration](https://docs.typesafe.ai/sdk/python/api/retries), [HTTP errors](https://docs.typesafe.ai/api)

The SDK redacts secret headers but not request/response bodies, so use sanitized application logging and avoid body-level debug logs. [Python client](https://docs.typesafe.ai/sdk/python/api/clients/sync)

TypeSafe says it does not train on input. Its privacy policy does not give a fixed general retention period; retention follows necessity and stated purposes. Zero-data-retention is offered for enterprise customers, not established as the default. Send minimum necessary metadata, never credentials, private media URLs or unrelated customer data. [Privacy policy](https://typesafe.ai/legal/privacy-policy), [Legal overview](https://docs.typesafe.ai/legal)

## Benchmark and acceptance proposal

1. Build a local labeled set covering flash cuts, dialogue, intentional repeated shots, quiet setup/payoff, text-heavy sources, multilingual speech and misleading source instructions.
2. Compare local selection alone, local selection plus Jev, and the existing full-video analysis. Preserve mandatory coverage in every arm.
3. Measure important-event recall, harmful exclusions, cast/action completeness, escalation rate, p50/p95 latency and total provider cost—not just Jev latency.
4. Start in shadow mode: record what Jev would select, without changing production or spending on generation. Authorize any paid Jev/Gemini benchmark separately.
5. Enable only future versioned runs after a material measured win. Preserve conservative coverage when Jev is unavailable or uncertain, and keep bounded technical recovery rather than reinstating manual scene review.

Illustrative arithmetic: a 10,000-input-token request at the published rate costs $0.00042; 1,000 such requests cost $0.42. This is not a per-video quote: include all questions, retries, descriptions, perception work and downstream calls. Savings arise only when the added decision step reduces more expensive work or improves quality enough to justify its cost.

## Unverified before production

Actual account access, regional latency, video-domain accuracy/calibration, total savings, SDK dependency compatibility, paid timeout/idempotency semantics, and account-specific retention terms remain untested. No model access or paid validation was performed for this research.

## Replacing MobileCLIP2: distinguish three jobs

Frame embeddings compare images and short labels. Shot detectors find transitions. A multimodal model interprets actions, speech, narrative and context. None alone is a complete automatic highlight editor; embeddings do not supply reliable OCR, character identity, event ordering or a prediction of views. Retain the existing visual-analysis and full-final-QC paths.

### Candidate shortlist

| Exact checkpoint | Evidence and license | Proposed role / tradeoff |
| --- | --- | --- |
| `facebook/PE-Core-S16-384` | Meta publishes Apache-2.0 weights and image/video evaluation results. Native input is 384px; the small vision tower is roughly 20M parameters, not the total dual-encoder size. [Checkpoint](https://huggingface.co/facebook/PE-Core-S16-384), [model documentation and license](https://github.com/facebookresearch/perception_models/blob/main/apps/pe/README.md) | First quality-oriented small candidate for semantic frame selection. Not a generative model. Its higher input resolution may cost more time than a lower-resolution model with more parameters. |
| `wkcn/TinyCLIP-ViT-40M-32-Text-19M-LAION400M` | Author's model card explicitly labels MIT and reports 84.2M total parameters; the name is not a total-size count. Native input is 224px. [Checkpoint](https://huggingface.co/wkcn/TinyCLIP-ViT-40M-32-Text-19M-LAION400M), [official configuration](https://github.com/microsoft/Cream/blob/main/TinyCLIP/src/open_clip/model_configs/TinyCLIP-ViT-40M-32-Text-19M.json) | Straightforward Python/Transformers speed-oriented baseline to compare against PE-S. No local speed claim until measured. |
| `wkcn/TinyCLIP-ViT-8M-16-Text-3M-YFCC15M` | MIT checkpoint; 23.4M total parameters. Its published classification result is lower than the larger TinyCLIP models. [Checkpoint](https://huggingface.co/wkcn/TinyCLIP-ViT-8M-16-Text-3M-YFCC15M) | Memory-constrained option, not the default semantic judge. |
| `google/siglip2-base-patch32-256` | Apache-2.0 checkpoint with multilingual text processing; roughly 0.4B total parameters, much larger than its vision tower alone. Native input is 256px. [Checkpoint](https://huggingface.co/google/siglip2-base-patch32-256), [configuration](https://huggingface.co/google/siglip2-base-patch32-256/blob/main/config.json) | Larger quality/multilingual challenger. Not the smallest replacement. |
| `facebook/dinov2-small` | 22.1M image-only checkpoint; upstream explicitly licenses code and model weights under Apache-2.0. [Checkpoint](https://huggingface.co/facebook/dinov2-small), [license statement](https://github.com/facebookresearch/dinov2#license) | Optional visual-similarity baseline when text tagging is unnecessary. It is not a paired image/text CLIP replacement. |

PE's official Python configuration specifies a 384-wide, 12-layer S vision tower and a separate 512-wide, 12-layer text tower with a 49,408-token vocabulary. Do not sum rounded table labels into a purported exact total; token embeddings contribute additional storage. Its official demo supports CPU/CUDA, but that does not establish MPS compatibility or latency on this machine. [Configuration](https://github.com/facebookresearch/perception_models/blob/main/core/vision_encoder/config.py), [demo](https://github.com/facebookresearch/perception_models/blob/main/apps/pe/docs/pe_demo.ipynb)

Published image/video benchmark scores are screening evidence, not proof of better Shorts editing. TinyCLIP's paper measures throughput on NVIDIA V100 with large batches; it is not a Mac benchmark. [Original paper](https://openaccess.thecvf.com/content/ICCV2023/papers/Wu_TinyCLIP_CLIP_Distillation_via_Affinity_Mimicking_and_Weight_Inheritance_ICCV_2023_paper.pdf)

MobileCLIP2's code/weight distinction remains material: its MIT code license points to a separate research-only model license excluding product development. The explicit MIT/Apache checkpoint declarations above avoid that particular restriction, subject to their conditions and applicable media rights. [Apple code license](https://github.com/apple-aiml-research/ml-mobileclip/blob/main/LICENSE), [Apple model license](https://github.com/apple-aiml-research/ml-mobileclip/blob/main/LICENSE_MODELS)

### Actual clipping: start without a neural model

Use PySceneDetect's per-frame content-change metrics and AdaptiveDetector as complementary candidate signals. AdaptiveDetector is designed to mitigate camera-motion false positives. Both it and ContentDetector default to a 15-frame minimum scene; the latter also merges short flashes by default. Those defaults are unsuitable for preserving every brief evidence event. Keep raw scores, avoid frame skipping, and separately aggregate semantic scenes. These are proposed settings to validate, not a detection guarantee. [Detector documentation](https://www.scenedetect.com/docs/head/api/detectors.html)

PySceneDetect is BSD-3-Clause and requires no learned weights. Version 0.7 introduced PTS-backed timing for variable-frame-rate sources; pin and test the selected release. [License](https://github.com/Breakthrough/PySceneDetect/blob/main/LICENSE), [migration guide](https://www.scenedetect.com/docs/latest/api/migration_guide.html)

TransNet V2 is a potential later neural shot-boundary upgrade, not an embedding replacement. Upstream distributes trained weights within its MIT repository and documents temporal inference on low-resolution frames. No separate explicit weight-license statement was identified, so retain upstream provenance and notices rather than trusting an arbitrary mirror. Add only if local boundary tests outperform the simpler baseline enough to justify its dependencies. [Official inference](https://github.com/soCzech/TransNetV2/tree/master/inference), [MIT license](https://github.com/soCzech/TransNetV2/blob/master/LICENSE), [weights](https://github.com/soCzech/TransNetV2/tree/master/inference/transnetv2-weights)

## Proposed Python-only composition and qualification

1. Decode the full timeline at low spatial resolution while retaining original presentation timestamps. Measure cuts, frame quality, simple hashes and audio onsets locally. Never equate a 512-sample hop at 16kHz with a 30fps video frame.
2. Preserve baseline temporal coverage, first appearances, repeated-shot context and quiet setup/payoff. Enrich candidate frames using the selected encoder. Keep original-resolution artifacts for visual inspection; cropped square embeddings must not become the only available evidence for portrait footage.
3. Precompute fixed-vocabulary text embeddings once per encoder/version; run image encoding in batches on candidates and coverage frames. Do not run the text tower for every video frame or deploy every shortlisted model simultaneously.
4. Let Jev prioritize optional evidence using small factual summaries. It cannot manufacture visual descriptions from vectors. Low confidence retains conservative coverage or requests bounded extra evidence; it does not reinstate a scene-approval gate.
5. Send the selected exact frames, contextual windows and whole-story context to the existing Gemini adapter. Where useful, a second Jev pass checks whether the returned descriptions are semantically complete. Python validates bindings, coverage and any permitted follow-up requests.
6. Keep A/B/C/D generation, replacement narration alignment, final-video QC and delivery unchanged. This is a source-understanding improvement, not new publishing authority.

Expose a small source-evidence module interface: verified source/transcript/policy in; immutable timestamped evidence manifest and uncertainty out. Keep encoder and optional decision adapters behind internal seams, with model/weight hashes, preprocessing, label vocabulary, transcript/source hashes and policy/rubric versions in cache identities. Never copy similarity thresholds unchanged between encoders.

Benchmark PE-S versus TinyCLIP40 on identical candidate frames first. Evaluate precision/recall for brief events, false duplicate removal, semantic label accuracy, missed quiet scenes, portrait-edge information, warm/cold latency, peak memory and CPU/MPS numerical behavior. Then evaluate whether adding Jev reduces downstream cost without losing evidence. Model size alone does not establish speed. [PyTorch MPS qualification context](https://docs.pytorch.org/docs/stable/notes/mps.html)

No packages or weights were installed/downloaded, no inference or paid validation ran, and no application code, services, records or videos changed. Only this research note was added.
