"""M7 voice: ElevenLabs TTS + duration gate.

`transport` is injectable: (url, headers, payload_dict) -> audio bytes.
Text is re-cleaned through M5's voicetext before sending (defensive — the
shot_list's voice_text should already be clean).
"""
import json
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

from modules.script.voicetext import clean

API = "https://api.elevenlabs.io/v1/text-to-speech"


class ElevenLabsTTS:
    def __init__(self, api_key, voice_id, model="eleven_v3", transport=None):
        if not voice_id:
            raise ValueError("voice_id not pinned — see docs/voice-selection.md")
        self.api_key = api_key
        self.voice_id = voice_id
        self.model = model
        self.transport = transport or self._http

    def _http(self, url, headers, payload):
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(),
            headers={**headers, "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read()

    def build_request(self, text):
        url = (
            f"{API}/{self.voice_id}?"
            + urllib.parse.urlencode({"output_format": "mp3_44100_128"})
        )
        payload = {
            "text": clean(text),
            "model_id": self.model,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        }
        headers = {"xi-api-key": self.api_key}
        return url, headers, payload

    def synthesize(self, text, out_path):
        url, headers, payload = self.build_request(text)
        audio = self.transport(url, headers, payload)
        p = Path(out_path)
        p.write_bytes(audio)
        return p


def audio_duration_s(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, timeout=30,
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "ffprobe failed")
    return float(json.loads(out.stdout)["format"]["duration"])


def duration_ok(path, min_s, max_s):
    return min_s <= audio_duration_s(path) <= max_s
