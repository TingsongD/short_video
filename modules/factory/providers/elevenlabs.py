"""ElevenLabs v3 with character alignment; same route as the verified batch."""
import base64
import json
import re
from .synchronous import SynchronousAdapter
from ..execution.context import current_effect
from ..execution.policy import ExecutionPolicy
from ..integrations.http import BoundedHTTP
from ..testing.fakes import ProviderError


class ElevenLabsAdapter(SynchronousAdapter):
    name = "elevenlabs"

    def __init__(self, state_dir, credentials=None, transport=None, policy=None):
        super().__init__(state_dir)
        self.credentials = credentials or (lambda: {})
        self.live = transport is None
        self.policy = policy or ExecutionPolicy()
        self.transport = transport or BoundedHTTP("elevenlabs", self.policy, 64 * 1024 * 1024)

    def execute(self, request):
        if request.get("model") != "eleven_v3" or not re.fullmatch(r"[A-Za-z0-9]+", request.get("voice_id", "")):
            raise ProviderError("tts_route_unqualified")
        if self.live:
            binding = current_effect.get()
            if not binding or binding["provider"] != self.name:
                raise ProviderError("authority_required")
        # Credentials are only resolved while dispatch is executing.
        key = self.credentials().get("ELEVENLABS_API_KEY", "")
        headers = {"xi-api-key": key, "Content-Type": "application/json"}
        payload = {"text": request["text"], "model_id": "eleven_v3",
                   "language_code": request.get("language") or "en", "voice_settings": request.get("settings") or {}}
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{request['voice_id']}/with-timestamps?output_format=mp3_44100_128"
        status, response_headers, raw = self.transport("POST", url, json.dumps(payload).encode(), headers)
        if status != 200:
            raise ProviderError("tts_http_error", http_status=status)
        try:
            doc = json.loads(raw)
            audio = base64.b64decode(doc["audio_base64"], validate=True)
            alignment = doc.get("normalized_alignment") or doc["alignment"]
            count = len(alignment["characters"])
            if not audio or count != len(alignment["character_start_times_seconds"]) or count != len(alignment["character_end_times_seconds"]):
                raise ValueError()
            if "".join(alignment["characters"]) != request["text"]:
                raise ValueError()
        except (KeyError, ValueError, TypeError):
            raise ProviderError("malformed_tts_response") from None
        actual = response_headers.get("x-character-count")
        return {}, audio, {"alignment": alignment, "request_id": response_headers.get("request-id"),
                           "actual_credits": int(actual) if actual is not None else None, "content_type": "audio/mpeg"}
