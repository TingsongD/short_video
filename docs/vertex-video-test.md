# Vertex AI video generation — live test

**Verified:** September 16, 2026, Vancouver time (September 17 UTC).

**Result: passed.** The existing Google Cloud account generated a video through
Vertex's API, returned its media, and delivered a verified copy to Drive. The
tested model was `gemini-omni-1.1-flash-preview` in `global`.

## Deliverable and measured results

[Watch the test on Google Drive](https://drive.google.com/file/d/1TXAztF8J3y1kWtdtIUXjW8_ThYSHzfUd/view).

| Measurement | Result |
|---|---|
| Prompt | Checkerboard tank on a hanger; warm boutique lighting; camera push-in |
| Input | Text only; no Shopify image or seed video |
| Duration | 4.01 seconds, requested 4 seconds |
| Picture | 720 × 1280, portrait 9:16, 24 fps, H.264 |
| Audio | AAC, 48 kHz, stereo |
| Submit to downloaded response | 48.79 seconds, including polling delay |
| File size | 3,153,441 bytes |
| Estimated API usage cost | **US$0.409384**, not settled Cloud billing |
| Drive verification | Parent, filename, byte size and MD5 match |
| Cleanup | No surviving owned workers; no occupied owned ports |

The full video and audio decoded without errors. Four evenly spaced frames were
inspected: the garment, hanger, rack and lighting match the generic prompt, and
the camera progressively approaches the garment. No large overlaid captions were
seen. The generated neck tag can contain synthetic markings. Audio was checked
technically, not given a separate listening or speech-transcription assessment.

This proves basic API generation and delivery. It does **not** establish exact
product identity, seed imitation quality, presenter continuity or lip sync.

## Authentication and API behavior

The saved `GEMINI_TTS_VERTEX_API_KEY` returned HTTP 401 on a read-only Interactions
listing: this endpoint requires OAuth credentials. The existing native `gcloud`
login required Google reauthentication. The user completed it in Chrome; the
refreshed OAuth token was held in memory and was not saved in project state.

The working generation request used:

- `POST https://aiplatform.googleapis.com/v1beta1/projects/{project}/locations/global/interactions`
- Model `gemini-omni-1.1-flash-preview`.
- Top-level `background: true`.
- A text input and video response format with `aspect_ratio: "9:16"`,
  `resolution: "720p"` and `duration: "4s"`.
- `generation_config.video_config.task: "text_to_video"`.
- Omitted `delivery` and `gcs_uri`, returning inline video bytes on retrieval.
- `GET` the original interaction ID to obtain progress and the completed result.

The first request specified `delivery: "uri"` without a storage bucket, following
an incomplete combination in the sample documentation. It returned an
interaction ID, then failed with `invalid_request`: URI delivery requires
`gcs_uri`. Its usage was empty and no video was generated. After confirming that
terminal failure, the corrected request omitted the delivery setting and
succeeded. The failed attempt and successful attempt have separate receipts.
No ambiguous or running request was resubmitted.

An HTTP 200 or an interaction ID is therefore insufficient to mark generation
successful. Check `status`, the top-level `errors` array and actual media output.
The generic API reference puts `background` at the request root and retrieves
interactions with `GET`; some video-guide examples differ. The saved successful
request records the combination verified here.
[Video guide](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/video/generate-videos-from-text),
[Interactions reference](https://docs.cloud.google.com/gemini-enterprise-agent-platform/reference/models/interactions-api).

## Model and cost evidence

The linked [Gemini video overview](https://gemini.google/overview/video-generation/)
currently features Gemini Omni 1.1 Flash. Its Vertex model is a public preview;
Google documents 3–10-second output, portrait/landscape options and reference
media workflows. Model IDs and request shapes differ from the Gemini Developer
API, so retain the tested Vertex route.
[Vertex model card](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/omni-1-1-flash),
[Reference generation](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/video/generate-videos-from-references).

Live Model Garden lookups returned HTTP 200 for Omni 1.1 Flash Preview,
`veo-3.1-fast-generate-001` (GA), and `veo-3.1-lite-generate-001` (public preview).
Only Omni was generated in this test. Catalog visibility alone does not prove
generation permission or available quota for Veo.

Reported usage and published rates yield:

| Category | Tokens | USD per million | Estimated USD |
|---|---:|---:|---:|
| Text input | 103 | 1.50 | 0.0001545 |
| Video output | 23,168 | 17.50 | 0.4054400 |
| Thought output | 421 | 9.00 | 0.0037890 |
| **Total** | **23,692** | | **0.4093835** |

720p output is priced at 5,792 video tokens per second, approximately $0.10136
per generated second before input and thought usage. These are Google Cloud
API charges, separate from Jimeng credits. The local USD ledger reconciles the
planning reservation to this usage estimate; Cloud billing has not been checked.
[Published pricing](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing).

## Fit with the existing factory

Google can serve as another clip-generation provider alongside the Canvas
adapter. Hypit can continue to handle reference planning/editing, while the
existing renderer, narration and delivery stages consume downloaded clips.
No production module, provider default or frozen contract was changed by this
pilot.

Before production integration:

1. Test an actual Shopify reference image and a short seed segment, measuring
   garment accuracy, motion, timing and unwanted generated text.
2. Add a provider adapter with parameter discovery, dollar estimates, persisted
   interaction IDs, recovery, terminal error handling and verified downloads.
3. Account for the model's documented duration limits and 24 fps output when
   allocating shots and producing the existing 30 fps final exports.
4. Make native generated audio an explicit choice; retain the existing
   ElevenLabs/Vertex narration and music path when separately authored audio is
   required.
5. Verify quotas before selecting production concurrency. One successful request
   does not establish five simultaneous jobs or unattended reliability.
6. Handle OAuth expiry explicitly in the worker/dashboard: this pilot needed
   user verification before it could proceed.

## Local evidence

All run artifacts are under
`data/production/v-vertex-video-pilot-20260916/`:

- `run_test.py`: isolated pilot, with receipt checks that block duplicate submits.
- `preflight.json`, `model-access.json`: credential/access results.
- `attempt-01-invalid-delivery/`: confirmed failed configuration attempt.
- `request.json`, `receipt.json`, `response-*.json`: corrected request and recovery
  information; media bytes omitted from JSON response evidence.
- `qc-report.json`, `contact-sheet.jpg`, `cost-estimate.json`, `test-report.json`.
- `upload-receipt.json`, `process-ownership.json`, `cleanup-receipt.json`.
- `Google-Vertex_Omni-1.1-Flash_Checkerboard-Tank_API-Test_720p_4s_v1.mp4`.

The pilot script compiled and the live path was exercised. No full offline test
suite was rerun for this isolated diagnostic. Nothing was published to social
platforms.
