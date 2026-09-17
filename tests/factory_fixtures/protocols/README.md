# Adapter protocol evidence

These are factory fixtures; frozen legacy fixtures are unchanged.

- `canvas-cli-1.0.1.json`: public schema returned by the installed
  `dreamina-canvas schema --format json`; CLI 1.0.1, commit `83aeb67`.
  This was a local metadata read, with no login or generation call. The fake
  implements positional canvas names, caller-owned IDs, `data.items` run
  acknowledgements, operation references and resource download receipts.
- `vertex-request.json`: sanitized successful pilot request from
  `data/production/v-vertex-video-pilot-20260916/request.json`.
- `vertex-completed.json`: sanitized successful pilot envelope. Retains actual
  `completed`, `steps[].content[].type=video`, `data`, `mime_type` and
  `total_*_tokens` field names. Identity, prompt and video bytes are fixtures.
- Hypit envelopes were verified against the installed **0.1.8** sources:
  `packages/cli/src/machine-view.ts`, `view.ts` and `output.ts`. Build/status
  contain a nested build object. Terminal failed status may exit with code 1.
- Drive arguments were checked using installed CLI help. Actual metadata keys
  (`Name`, `Size`, `MD5`, `Parents`) also match the verified legacy uploader.
- Shopify queries pass the installed Admin GraphQL skill's schema validator.
  The pinned request version remains 2026-04; its `ProductVariant.price` is a
  scalar. The validator's bundled current schema also accepts these queries.
  No store requests were made. Product media and variants retain pagination
  evidence; currency is not silently converted to USD.
- ElevenLabs uses the existing batch's v3 `with-timestamps` route and character
  alignment fields. The fixture uses a real generated local PCM waveform.
- Viral Outliers search reuses the existing verified client endpoint and request
  fields. Recovery retains synchronous local receipts rather than inventing
  asynchronous remote jobs.

Contract tests do not establish live generation, input-mode or account
qualification. Veo and unverified Vertex reference modes remain unavailable.
The native Hypit qualification command is `scripts/factory_qualify_hypit.py`;
it uses a fresh isolated runtime with only local media/render providers and
stops that runtime after retrieval.
