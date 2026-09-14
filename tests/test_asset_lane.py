"""M6: selector file + Lane A bridge stub + Pexels fallback
(test_selectors_file, test_pexels_fallback)."""
import json
import shutil
from pathlib import Path

import pytest

from modules.assets import jimeng_bridge
from modules.assets.jimeng_bridge import BridgeUnavailable, JimengBridge, load_selectors
from modules.assets.manifest import build_manifest
from modules.assets.pexels import PexelsClient

FIXTURES = Path(__file__).parent / "fixtures" / "media"


def test_selectors_file_parses_with_required_keys():
    cfg = load_selectors()
    assert cfg["site_url"].startswith("https://jimeng.jianying.com")
    for key in ("login_check", "prompt_textarea", "submit_button",
                "result_item", "download_button"):
        assert cfg["selectors"][key]


def test_bridge_unavailable_without_url():
    b = JimengBridge(bridge_url="")
    with pytest.raises(BridgeUnavailable):
        b.submit_prompt("prompt", "/tmp", 0)


def test_bridge_flow_with_fake_post(tmp_path):
    calls = []

    def fake_post(payload):
        calls.append(payload)
        if payload["action"] == "exists":
            return {"ok": True, "found": True}
        if payload["action"] == "download":
            Path(payload["save_as"]).write_bytes(b"mp4")
            return {"ok": True}
        return {"ok": True}

    b = JimengBridge(bridge_url="http://localhost:9999", post=fake_post)
    out = b.submit_prompt("cinematic shot", tmp_path, shot_idx=0)
    assert out.name == "shot-00.jimeng.mp4"
    assert calls[0]["action"] == "exists"          # login checked first


def _pexels_transport(url):
    if "videos/search" in url:
        return {"videos": [{"video_files": [
            {"link": "https://files.pexels.com/vid-sd.mp4", "height": 720},
            {"link": "https://files.pexels.com/vid-hd.mp4", "height": 1280},
        ]}]}
    return {"photos": [{"src": {"large": "https://img.pexels.com/p.jpg"}}]}


def test_pexels_fallback_writes_file(tmp_path):
    px = PexelsClient(
        "fake-key",
        transport=_pexels_transport,
        downloader=lambda url: Path(FIXTURES / "good_video.mp4").read_bytes(),
    )
    target = tmp_path / "shot-00.stock.mp4"
    assert px.fetch("couple arguing", "video", target)
    doc = build_manifest("v-1", tmp_path, shot_count=1)
    assert doc["assets"][0]["source"] == "stock"


def test_pexels_prefers_portrait_hd(tmp_path):
    px = PexelsClient("k", transport=_pexels_transport,
                      downloader=lambda u: b"x")
    assert px.search_video("t") == "https://files.pexels.com/vid-hd.mp4"


def test_pexels_no_result_returns_false(tmp_path):
    px = PexelsClient("k", transport=lambda u: {"videos": []},
                      downloader=lambda u: b"x")
    assert not px.fetch("nothing", "video", tmp_path / "x.mp4")
