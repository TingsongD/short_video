"""MusicAdapter (generated_music): durable sync route against a fake transport.

No network or paid APIs — the transport double returns canned MP3 bytes.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from modules.factory.domain.errors import ContractError
from modules.factory.providers.music import MusicAdapter
from modules.factory.testing.fakes import ProviderError

MP3 = b"ID3" + b"\x00" * 4096
PRICING = {"credits_per_second": 30, "valid_until": "2099-01-01T00:00:00Z",
           "evidence": "fixture tariff"}
REQ = {"kind": "music", "model": "music_v1", "prompt": "minimal underscore",
       "music_length_ms": 10000, "instrumental": True}


def _transport(status=200, raw=MP3, headers=None):
    def call(method, url, payload, request_headers):
        body = json.loads(payload)
        assert url == "https://api.elevenlabs.io/v1/music?output_format=mp3_44100_128"
        assert body["model_id"] == "music_v1" and body["force_instrumental"] is True
        return status, headers or {}, raw
    return call


def _adapter(tmp_path, **kw):
    return MusicAdapter(tmp_path / "mus", transport=_transport(**{k: v for k, v in kw.items() if k != "pricing"}),
                        account="fixture-account", pricing=kw.get("pricing", PRICING),
                        model="music_v1")


def test_submit_download_roundtrip(tmp_path):
    adapter = _adapter(tmp_path)
    receipt = adapter.submit(dict(REQ))
    assert receipt["status"] == "succeeded"
    out = adapter.download(receipt["operation_id"])
    assert out["bytes"] == MP3 and out["content_type"] == "audio/mpeg"
    # Idempotent: a second submit reads the receipt, never redispatches.
    again = adapter.submit(dict(REQ))
    assert again["operation_id"] == receipt["operation_id"]


def test_price_quote_contract(tmp_path):
    adapter = _adapter(tmp_path)
    quote = adapter.price(dict(REQ))
    assert quote["unit"] == "elevenlabs_credits" and quote["amount"] == 300
    assert {"kind", "reserve_amount", "rate_basis", "valid_until"} <= quote.keys()


def test_rejections(tmp_path):
    adapter = _adapter(tmp_path)
    for bad in ({"model": "music_v2"}, {"music_length_ms": 1000},
                {"music_length_ms": 700000}, {"prompt": ""}, {"prompt": 1}):
        req = {**REQ, **bad}
        with pytest.raises((ProviderError, ContractError)):
            adapter.execute(req)
    with pytest.raises(ContractError):
        adapter.price({**REQ, "model": "music_v2"})
    with pytest.raises(ContractError):
        adapter.price({**REQ, "music_length_ms": 2500})


def test_remaining_balance_is_never_a_charge(tmp_path):
    """x-credits-remaining is the account balance — exporting it as the
    operation's charge would settle spend that was never incurred."""
    adapter = _adapter(tmp_path, headers={"x-credits-remaining": "95432"})
    _meta, _raw, receipt = adapter.execute(dict(REQ))
    assert receipt["actual_credits"] is None
    adapter = _adapter(tmp_path / "b", headers={"x-credits-charged": "300",
                                              "x-credits-remaining": "95432"})
    _meta, _raw, receipt = adapter.execute(dict(REQ))
    assert receipt["actual_credits"] == 300


def test_http_and_malformed_failures(tmp_path):
    with pytest.raises(ProviderError):
        _adapter(tmp_path / "a").__class__(tmp_path / "a2", transport=_transport(status=429),
                                           account="a", pricing=PRICING).execute(dict(REQ))
    with pytest.raises(ProviderError):
        MusicAdapter(tmp_path / "b", transport=_transport(raw=b"tiny"),
                     account="a", pricing=PRICING).execute(dict(REQ))
