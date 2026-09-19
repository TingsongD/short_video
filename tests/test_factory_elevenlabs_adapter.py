"""ElevenLabsAdapter (elevenlabs): durable sync route against a fake transport.

No network or paid APIs — the transport double returns canned payloads.
"""
import base64
import json

import pytest

from modules.factory.providers.elevenlabs import ElevenLabsAdapter
from modules.factory.testing.fakes import ProviderError

PRICING = {"credits_per_character": 1, "valid_until": "2099-01-01T00:00:00Z",
           "evidence": "fixture tariff"}
REQ = {"model": "eleven_v3", "voice_id": "voice9", "text": "good boy wins",
       "language": "en", "settings": {}}


def _doc(text, audio=b"ID3" + b"\x00" * 2048, normalized=None):
    raw = {"characters": list(text),
           "character_start_times_seconds": [0.0] * len(text),
           "character_end_times_seconds": [0.1] * len(text)}
    body = {"audio_base64": base64.b64encode(audio).decode(),
            "alignment": raw}
    if normalized is not None:
        body["normalized_alignment"] = normalized
    return json.dumps(body).encode()


def _transport(doc):
    def call(method, url, payload, headers):
        return 200, {"x-character-count": "13"}, doc
    return call


def _adapter(tmp_path, doc):
    return ElevenLabsAdapter(tmp_path / "tts", transport=_transport(doc),
                             account="fixture-account", pricing=PRICING)


def test_normalized_alignment_accepted_after_paid_response(tmp_path):
    """The provider spells numerals/contractions out in the normalized
    alignment ("2" -> "two"); a paid success must not be rejected for it."""
    normalized = {"characters": list("good boy wins"),
                  "character_start_times_seconds": [0.0] * 13,
                  "character_end_times_seconds": [0.1] * 13}
    doc = _doc("good boy wins", normalized=normalized)
    _meta, audio, receipt = _adapter(tmp_path, doc).execute(dict(REQ))
    assert audio and receipt["alignment"]["characters"] == list(
        "good boy wins")


def test_normalized_differs_from_raw_text_still_accepted(tmp_path):
    """Raw '2 dogs' normalized to 'two dogs' — the spoken form is the
    normalized alignment; the request text only needs to match one
    representation."""
    req = dict(REQ, text="2 dogs")
    normalized = {"characters": list("two dogs"),
                  "character_start_times_seconds": [0.0] * 8,
                  "character_end_times_seconds": [0.1] * 8}
    doc = _doc("2 dogs", normalized=normalized)
    _meta, audio, receipt = _adapter(tmp_path, doc).execute(req)
    assert receipt["alignment"]["characters"] == list("two dogs")


def test_neither_alignment_matching_still_rejected(tmp_path):
    doc = _doc("a wholly different sentence")
    with pytest.raises(ProviderError):
        _adapter(tmp_path, doc).execute(dict(REQ))


def test_mismatched_alignment_lengths_rejected(tmp_path):
    bad = {"characters": list("good boy wins"),
           "character_start_times_seconds": [0.0],
           "character_end_times_seconds": [0.1] * 13}
    doc = _doc("good boy wins", normalized=bad)
    with pytest.raises(ProviderError):
        _adapter(tmp_path, doc).execute(dict(REQ))
