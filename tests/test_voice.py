"""M7: TTS request shape, duration gate, text cleaning (test_tts_mock,
test_duration_gate, test_text_clean)."""
import json
from pathlib import Path

import pytest

from modules.voice.tts import ElevenLabsTTS, audio_duration_s, duration_ok

FIXTURES = Path(__file__).parent / "fixtures" / "media"


class Rec:
    def __init__(self):
        self.calls = []

    def __call__(self, url, headers, payload):
        self.calls.append({"url": url, "headers": headers, "payload": payload})
        return Path(FIXTURES / "good_voice.mp3").read_bytes()


def test_request_payload_correct(tmp_path):
    rec = Rec()
    tts = ElevenLabsTTS("ek_test", "voice-abc", model="eleven_v3", transport=rec)
    tts.synthesize("If someone says these three phrases, walk away.",
                   tmp_path / "voice.mp3")
    call = rec.calls[0]
    assert call["url"].startswith(
        "https://api.elevenlabs.io/v1/text-to-speech/voice-abc"
    )
    assert call["headers"]["xi-api-key"] == "ek_test"
    assert call["payload"]["model_id"] == "eleven_v3"
    assert "walk away" in call["payload"]["text"]
    assert (tmp_path / "voice.mp3").stat().st_size > 0


def test_empty_voice_id_rejected():
    with pytest.raises(ValueError, match="voice_id"):
        ElevenLabsTTS("k", "")


def test_duration_gate_bounds():
    assert duration_ok(FIXTURES / "good_voice.mp3", 15, 60)   # 20s fixture
    assert not duration_ok(FIXTURES / "short_voice.mp3", 15, 60)  # 8s


def test_audio_duration_probe():
    assert audio_duration_s(FIXTURES / "good_voice.mp3") == pytest.approx(20.0, abs=0.5)


def test_markdown_emoji_stripped_before_send(tmp_path):
    rec = Rec()
    tts = ElevenLabsTTS("k", "v1", transport=rec)
    tts.synthesize("**Bold** hook 🚀 — it's 3 things.", tmp_path / "v.mp3")
    sent = rec.calls[0]["payload"]["text"]
    assert "*" not in sent and "🚀" not in sent
    assert "three" in sent and "it is" in sent
