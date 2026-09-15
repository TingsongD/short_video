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

The new `.env` existed but was zero bytes on disk when inspected. No Google key
was available, so no Google authentication or model access has been verified.
The existing privately configured ElevenLabs account remains available. Save the
new credentials and identify AI Studio versus Vertex before the Google access
check. No TTS or music generation was submitted during configuration setup.

Sources checked on 2026-09-15:

- [Gemini music generation](https://ai.google.dev/gemini-api/docs/music-generation)
- [Cloud music generation](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/music/generate-music)
- [Gemini speech generation](https://ai.google.dev/gemini-api/docs/speech-generation)
- [Vertex express-mode authentication example](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/samples/googlegenaisdk-vertexai-express-mode)
