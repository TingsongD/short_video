# Narration and music credentials

## Current project support

The production voice provider remains ElevenLabs (`eleven_v3`); the channel voice
still needs selection and a live audition. Hypit can import generated audio files
as separate narration/music tracks and render them locally with the picture.
Google credentials can now be loaded, but Google TTS/music generation adapters
are not connected to the automated production command yet.

## Private configuration

The shared Python configuration loader reads this repository's root `.env`.
Credential precedence is **nonempty process environment > nonempty `.env` value
> `config/secrets.toml`**. Empty placeholders preserve an existing working value.
The loader does not modify either file or export credentials to child processes.
Run commands from any working directory; it never searches another directory's
`.env`. Only the root `.env` is loaded; `.env.local` is not an additional source.

Use `.env.example` as a field reference. Save edits in the editor before checking
access. The file uses standard dotenv quotes, comments and optional `export`
prefixes. Values are literal: shell commands and `${VARIABLE}` expressions are
not executed or expanded. Invalid entries report line numbers without printing
their contents. Parser dependency: `python-dotenv==1.2.3`, installed by `make setup`.

`.env` and `.env.*` are ignored by Git; `.env.example` is the non-secret template.
The user explicitly selected `.env` for this setup; it is an additional private
source alongside the earlier TOML convention. The existing ElevenLabs credential
stays usable while the new file is empty.

## Google routes to verify

`GEMINI_TTS_VERTEX_API_KEY` is a project-specific variable name. Loading it does
not select a Google endpoint or establish permission to use every model.

| Route | Documented authentication and model examples |
| --- | --- |
| Gemini API / AI Studio | API key in `x-goog-api-key`; Interactions endpoint on `generativelanguage.googleapis.com`. Music guide lists `lyria-3.5` and `lyria-3-clip-preview`. |
| Standard Vertex AI / Agent Platform | Cloud project and authenticated identity. The supplied music guide uses a Bearer token and project-scoped Interactions endpoint on `aiplatform.googleapis.com`; its model examples are `lyria-3-clip-preview` and `lyria-3-pro-preview`. |
| Vertex express mode | A compatible express-mode key can initialize `genai.Client(vertexai=True, api_key=...)`. The example establishes express authentication, not Lyria access for this account. |

Google's Gemini music guide documents 44.1 kHz stereo MP3. Lyria 3 Clip produces
30 seconds; Lyria 3.5 targets longer music with duration guided by the prompt.
For background music, request instrumental-only audio and trim/fade the accepted
result to the actual narration timeline. It is separate from Gemini TTS: Google's
speech guide documents voice selection and a mono 24 kHz PCM-to-WAV example.

The provider adapter must select the verified API route/model, preserve response
metadata, decode the actual returned audio format and validate duration/streams
before handing local media to Hypit. Keep generation spending explicit and reuse
accepted files for edits. Listing a model does not prove paid generation access.

## Verification status — 2026-09-15

The user saved `.env` and confirmed Vertex AI. Cloud project and `us-central1`
region are configured privately. The mixed-case ElevenLabs field was normalized
to `ELEVENLABS_API_KEY`, preserving its value; account verification returned 200.

The Google key passes Vertex `countTokens` checks through both the express and
project-scoped routes. Project-scoped checks for `gemini-2.5-flash-tts` and
`gemini-2.5-pro-tts` also return 200. These establish token-counting access, not
successful speech synthesis, quota availability or final audio quality.

Model Garden listing rejects API-key authentication with 401
`CREDENTIALS_MISSING`; the project-scoped Interactions list check also returns
401 with that key. Cloud CLI reauthorization through the user's Chrome is now
complete. A fresh OAuth token succeeds on both checks (HTTP 200). The model
listing returns 27 entries, including Gemini 2.5 Flash/Pro TTS, with no next page.
The Interactions list returns an empty result successfully. This establishes
read access, not permission or quota to create a music generation.

Direct Model Garden lookups return HTTP 200 for `lyria-3-clip-preview` and
`lyria-3-pro-preview`, even though neither appears in the list response.
Lookups for `lyria-3.5` and `lyria-002` return 404 on the same catalog route;
that result alone does not establish availability on other inference routes.
Native Cloud CLI storage owns the credentials. Access tokens were used only in
memory; no OAuth code or token is copied to project configuration or receipts.

The supplied Cloud music guide lists Lyria 3 Clip/Pro preview models, matching
the successful direct catalog lookups. The separate Gemini API guide lists
Lyria 3.5. Lyria 3.5 access through this Vertex project has not been established.
The subsequent authorized generation test below verifies Flash TTS and Lyria 3
Clip. Automated Google provider adapters remain pending.
Sanitized receipts: `data/production/google-audio-setup/verification.json`.

## Authorized live audio test — 2026-09-15

The user requested one Vertex TTS and background-music test. Both requests used
native Cloud CLI OAuth, returned HTTP 200 and produced local files. Exactly two
generation POSTs were made, with no retries or replacement generations.

| Sample | Model | Actual output |
| --- | --- | --- |
| English narration, Kore voice | `gemini-2.5-flash-tts`, `us-central1` | 14.531 seconds, 24 kHz mono PCM wrapped as WAV |
| Instrumental morning-coffee cue | `lyria-3-clip-preview`, global Interactions | 28.813 seconds, 44.1 kHz stereo MP3; requested 30-second clip |

Both files decode fully and contain non-silent audio. The narration completed
with `STOP`; music completed with a recoverable Interaction ID. A separate
16.531-second local preview mixes the narration over quieter music, reduces
music further during speech, and adds fades. Its decoded peak is -4.5 dBFS.
Original audio files are preserved. Listening quality, exact spoken-text
fidelity and the absence of vocals in the music require operator review.

List-price usage estimate: **US$0.043666**, comprising $0.003666 for 72 input text
tokens and 363 output audio tokens, plus $0.04 for one Lyria 3 Clip. This is not
settled billing. The ledger reservations were reconciled to these estimates.
Sources: [Google TTS pricing](https://cloud.google.com/text-to-speech/pricing)
and [Vertex music pricing](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing).

Files and receipts: `data/production/v-vertex-audio-pilot-20260915/`, including
`narration.wav`, `background-music.mp3`, `narration-with-music.mp3`,
`test-report.json`, request/response receipts and `audio-qc.json`. The local pilot
runner refuses to submit again when a receipt exists. Credentials remain outside
these artifacts. This test does not switch the production voice provider or
modify the existing Hypit edit. The narration is below the production 15-second
minimum; G7/G8/G12 remain unsigned.

Sources checked on 2026-09-15:

- [Gemini music generation](https://ai.google.dev/gemini-api/docs/music-generation)
- [Cloud music generation](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/music/generate-music)
- [Gemini speech generation](https://ai.google.dev/gemini-api/docs/speech-generation)
- [Vertex express-mode authentication example](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/samples/googlegenaisdk-vertexai-express-mode)
- [Vertex express REST operations](https://docs.cloud.google.com/gemini-enterprise-agent-platform/reference/express-mode/api-reference)
- [Gemini TTS through Google Cloud](https://docs.cloud.google.com/text-to-speech/docs/gemini-tts)
