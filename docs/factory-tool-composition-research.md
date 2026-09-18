# Factory tool composition research

Reviewed 2026-09-17. This is a design recommendation supported by official documentation, the installed Hypit source and the factory's existing analytics/learning implementation. No provider credentials were used, no paid calls were made, and no production code was changed.

## Recommended composition

Keep Hypit-directed seed analysis mandatory, with the factory owning workflow state, evidence, budgets, experiments and learning. Select specialist execution tools for a concrete gap. A skill supplies working instructions; a renderer or provider supplies execution. Installing several overlapping skills does not itself create a reliable pipeline.

The recommended default is the existing Hypit authoring/runtime path, its HyperFrames visual renderer, and FFmpeg-based media preparation and verification. Consider Remotion as an alternative composition backend only when a measured template or editor need justifies maintaining it. Use HeyGen avatar generation only for a presenter-led format. Treg and Monid belong behind explicit provider adapters for discovery and capabilities missing from the dedicated stack.

## Verified capabilities and their implications

| Tool | Verified fact | Recommendation for this factory |
| --- | --- | --- |
| Installed Hypit | Version 0.1.8 includes a local HyperFrames provider. Its package declares HyperFrames engine/producer/CLI 0.7.101. Visual rendering uses Chrome and emits a silent MP4; a separate media provider prepares audio and muxes the final output. The render contract checks frame/sample alignment. [Installed package](</Users/tingsongdai/Kimi-cursor/Short Form AI YouTube/vendor/hypit-runtime/node_modules/@hypit/hypit/packages/provider-hyperframes-local/package.json>), [provider documentation](</Users/tingsongdai/Kimi-cursor/Short Form AI YouTube/vendor/hypit-runtime/node_modules/@hypit/hypit/packages/provider-hyperframes-local/README.md>), [render contract](</Users/tingsongdai/Kimi-cursor/Short Form AI YouTube/vendor/hypit-runtime/node_modules/@hypit/hypit/packages/render-hyperframes/README.md>). | Benchmark and qualify this existing path before adding another HyperFrames installation. Package presence alone does not establish that the factory dashboard already exercises it correctly. |
| HyperFrames | Authors HTML/CSS/JavaScript compositions and seeks animations before capturing frames. Its documented deterministic contract disallows wall-clock dependence and unseeded randomness. Local rendering does not consume HeyGen credits; optional services can cost money. [Comparison](https://hyperframes.heygen.com/guides/hyperframes-vs-remotion), [quickstart](https://hyperframes.heygen.com/quickstart). | Suitable for repeatable captions, overlays, motion graphics and structured layouts. It need not add elaborate graphics to a candid-footage seed. Keep one selected composition backend responsible for the master timeline. |
| Remotion | React compositions can be embedded and customized through Player. The server renderer exports video/audio, with `renderMedia()` recommended over separate frame rendering and stitching. [Player](https://www.remotion.dev/docs/player), [renderer](https://www.remotion.dev/docs/renderer). | Useful when reusable React templates, interactive parameter controls or an existing React design system justify it. Treat it as an alternative renderer or a bounded component exporter, not another mandatory pass over every video. |
| HeyGen avatar services | The API distinguishes Avatar Video, where callers choose avatar, voice and script, from HyperFrames, which converts HTML/CSS/JS into motion graphics. [HeyGen quickstart](https://developers.heygen.com/docs/quick-start). | An avatar shot supplier when the creative format needs a visible presenter. A presenter would materially change the current dog-compilation format and should not be inserted into its close-mimic control. |
| FFmpeg and ffprobe | Filters include trimming, concatenation, audio mixing, loudness normalization, caption rendering and silence/black/freeze detection. ffprobe exposes machine-readable stream/container information. [Filters](https://ffmpeg.org/ffmpeg-filters.html), [ffprobe](https://ffmpeg.org/ffprobe.html). | Use for preparation, deterministic assembly where sufficient, export checks and technical defect signals. These checks support a full watch/listen review; they do not evaluate humor, narrative or viewer appeal. |

## Treg and Monid: discovery and qualified execution

Treg exposes catalog search, endpoint documentation, pricing and access checks. Ordinary catalog calls do not automatically switch between providers; explicit routed capability endpoints have different behavior. Its docs describe per-call `X-Treg-Route-Max-Cost` caps, 24-hour caller-scoped idempotency keys, call IDs and actual-cost receipts. Direct calls have no default cost cap. Quoted costs must account for units and potential relay pricing. [Treg official integration reference](https://treg.to/llms.txt).

Monid exposes discover, inspect, run and run-status APIs. Inspection returns parameter schemas and pricing; its skill documents health and latency indicators and prioritizes existing dedicated tools. These are service availability signals, not evidence of creative quality. [API overview](https://monid.ai/docs/api/overview), [inspect](https://monid.ai/docs/api/inspect), [official skill](https://monid.ai/SKILL.md).

Monid's asynchronous execution returns a run ID. A `COMPLETED` lifecycle can still contain a provider HTTP error, and a control-blocked request can return HTTP 200. Adapters must inspect the lifecycle, provider response and expected output, rather than treating an HTTP success or completed job as a usable artifact. [Run contract](https://monid.ai/docs/api/run).

Recommended factory rules:

- Preserve the user's acquisition preference: Hypit download first, then inspect suitable Treg and Monid alternatives when needed.
- Discover for a narrow capability, inspect its current schema and costs, then qualify the exact endpoint and mode. A catalog entry is a candidate, not proof that the factory supports it.
- Store provider, endpoint/model, request hash, price quote, attempt/run ID, billing receipt and verified artifact identity. Keep keys server-side and out of logs.
- Let the factory enforce a whole-round budget and retry limits. Use provider caps when supported; do not assume Monid implements Treg's headers or retry semantics.
- Poll an existing generation job after an ambiguous submission before submitting another paid job or changing provider. An alternative provider may require different inputs and produce a different creative treatment.
- Keep public trend/seed research distinct from authorized channel performance measurement. A scraping catalog does not by itself establish access to the channel's private retention data.

## How tools support a valid creative experiment

These are design recommendations, not vendor guarantees:

1. The mandatory Hypit analysis creates one evidence-linked creative specification: hook, beats, actions, camera behavior, captions, audio, timing and uncertainties.
2. Build A as the close adaptation; derive B/C/D independently by changing one declared creative factor each. Freeze the renderer, provider mode and unaffected media across siblings so tool changes do not masquerade as creative improvements.
3. Reuse unchanged assets and rebuild only affected dependencies. A spoken-line change may legitimately update its aligned voice, captions and animation together while remaining one semantic experiment.
4. Evaluate two separate questions before publishing: whether the render is technically correct, and whether its intended creative change is actually present and watchable.
5. Keep the accepted recipe, source evidence and artifact hashes linked to the experiment result. The winning recipe becomes a candidate control for the next round; tools remain interchangeable executors only after separate qualification.

For the current candid dog compilation, prioritize plausible continuous action, the timing of the reveal, natural reactions and readable captions. Additional avatars or decorative animation should be tested only if a clear hypothesis warrants changing that format.

## Measurement and repeated improvement

The existing implementation is a useful foundation: it freezes the decision policy before publication, preserves decision revisions and input provenance, distinguishes organic observational comparisons from causal experiments, and requires at least two independent seeds for broader confirmation. It currently defaults the exposure metric to thumbnail impressions. [Learning service](</Users/tingsongdai/Kimi-cursor/Short Form AI YouTube/modules/factory/learning/service.py:54>).

There are concrete Shorts measurement gaps. The analytics client allowlist omits `engagedViews`; the service's pull/normalized metric lists also omit engaged views and shares. Its aggregation currently weights average view duration and percentage by `views`. The analytics and learning services also require `exact_rolling` coverage. These are implementation observations, not claims that the requested loop is already operational. [Analytics client](</Users/tingsongdai/Kimi-cursor/Short Form AI YouTube/modules/factory/analytics/client.py:26>), [analytics service](</Users/tingsongdai/Kimi-cursor/Short Form AI YouTube/modules/factory/analytics/service.py:27>), [aggregation](</Users/tingsongdai/Kimi-cursor/Short Form AI YouTube/modules/factory/analytics/service.py:233>), [coverage gate](</Users/tingsongdai/Kimi-cursor/Short Form AI YouTube/modules/factory/analytics/service.py:323>), [learning coverage gate](</Users/tingsongdai/Kimi-cursor/Short Form AI YouTube/modules/factory/learning/service.py:150>).

Official YouTube guidance defines Shorts engaged views without loops and bases Shorts average view duration/percentage on engaged views. Stayed-to-watch is its own measure; do not reconstruct it by dividing engaged views by public views. Channel Analytics supports `engagedViews` with authorized access. Calendar-day reporting and metric availability must be distinguished from exact elapsed-hour coverage. [Shorts metric definitions](https://support.google.com/youtube/answer/12220281?hl=en), [channel reports](https://developers.google.com/youtube/analytics/channel_reports), [data model and availability](https://developers.google.com/youtube/analytics/data_model).

Recommended measurement changes:

- Add a Shorts-specific metric profile with engaged views, supported sharing/subscriber measures, retention and stayed-to-watch where the source actually provides it. Use correct denominators and represent unavailable metrics as unknown.
- Freeze an objective before publication. A sensible initial policy is engaged views over seven comparable complete reporting days, with retention guardrails. Treat an early 48-hour review as provisional and preserve a later 28-day follow-up. Choose and record the handling of the partial publication day consistently.
- Label the coverage actually supplied by the source. Use comparable completed calendar-day windows when that is what the API supplies; do not relabel them exact rolling hours. Wait for missing or delayed metrics instead of substituting lifetime public counters.
- A is the close-mimic control, B changes the hook, C changes one body factor, and D changes the ending. Record each hypothesis before seeing results. Publishing order and comparable slots should be planned and varied across experiments, because organic distribution differs.
- Select a candidate winner only after the predeclared window, exposure and practical-lift criteria are met. A can win; an inconclusive outcome is valid. Performance differences in organic posts remain observational.
- Use the champion's creative recipe as the next control and propose three fresh independent hypotheses. Confirm transferable changes on fresh independent seeds; four variants of one seed are not four independent confirmations. Test combinations of prior winners separately because their effects may interact.
- Give the repeated workflow explicit spend/round limits, quality gates, data-ready checks and publishing authorization boundaries. The system should be able to wait, retry safely, retain the control or stop when evidence is insufficient.
