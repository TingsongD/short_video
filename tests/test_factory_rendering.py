"""F23: render execution — real local fast-path render, section cache
resume, 24→30 fps normalization, short-footage refusal, hypit build
observer/retrieve semantics, actual-output registration."""
import json
import subprocess

import pytest

from modules.factory.artifacts.registry import ArtifactStore
from modules.factory.domain.errors import ContractError
from modules.factory.domain.records import Composition
from modules.factory.rendering import (FastPathRenderer,
                                       HypitBuildRunner, RenderService)
from modules.factory.store import Database
from modules.factory.testing.fixtures import _color_mp4

NOW = "2026-09-17T00:00:00Z"
CLOCK = {"fps": 30, "width": 360, "height": 640}


@pytest.fixture
def stack(tmp_path):
    db = Database(tmp_path / "f.db")
    arts = ArtifactStore(tmp_path / "arts", db)
    svc = RenderService(db, arts, tmp_path / "builds")
    return db, arts, svc, tmp_path


def _comp(renderer="ffmpeg_fast"):
    return {"id": "comp-a", "content_hash": "h1", "variant_key": "A",
            "renderer": renderer}


def _clip(tmp, name, seconds=1.0, rate=30, color="0x3366cc"):
    p = tmp / f"{name}.mp4"
    _color_mp4(p, seconds, rate=rate, color=color, size="360x640")
    return p


def _probe_frames(path, runner=None):
    r = (runner or subprocess.run)(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_streams", str(path)],
        capture_output=True, text=True)
    info = json.loads(r.stdout)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    return v


def test_real_fast_render(stack):
    db, arts, svc, tmp = stack
    segs = [{"id": f"s{i}", "src": str(_clip(tmp, f"c{i}", 1.0)),
             "frames": 30} for i in range(3)]
    b = svc.register("bld-1", _comp(), now=NOW)
    out = svc.dispatch("bld-1", segs, [], [], CLOCK)
    assert out["status"] == "succeeded"
    v = _probe_frames(out["path"])
    assert v["avg_frame_rate"] == "30/1"
    assert int(v["nb_frames"]) == 90
    got = svc.collect("bld-1")
    art = db.uow().artifacts.get(got["artifact_id"])
    assert art["kind"] == "video"


def test_24fps_normalizes_without_drift(stack):
    db, arts, svc, tmp = stack
    src = _clip(tmp, "native24", 1.0, rate=24)      # 24 fps native
    segs = [{"id": "s0", "src": str(src), "frames": 30}]
    svc.register("bld-1", _comp(), now=NOW)
    out = svc.dispatch("bld-1", segs, [], [], CLOCK)
    assert out["status"] == "succeeded"
    v = _probe_frames(out["path"])
    assert v["avg_frame_rate"] == "30/1"
    assert int(v["nb_frames"]) == 30


def test_short_footage_refuses(stack):
    db, arts, svc, tmp = stack
    src = _clip(tmp, "short", 0.5, rate=30)         # 15 frames only
    segs = [{"id": "s0", "src": str(src), "frames": 30}]
    svc.register("bld-1", _comp(), now=NOW)
    out = svc.dispatch("bld-1", segs, [], [], CLOCK)
    assert out["status"] == "failed"
    assert "short_footage" in out["problem"]


def test_section_cache_resume(stack):
    """Interrupt at the concat step; resume completes from verified
    cached sections without re-encoding them."""
    db, arts, svc, tmp = stack
    segs = [{"id": f"s{i}", "src": str(_clip(tmp, f"c{i}", 1.0)),
             "frames": 30} for i in range(4)]
    real = subprocess.run
    calls = {"norm": 0}

    def flaky(argv, timeout=120, cwd=None):
        if argv[0] == "ffmpeg" and "-f" in argv \
                and "concat" in argv:
            raise subprocess.TimeoutExpired(argv, timeout)
        if argv[0] == "ffmpeg":
            calls["norm"] += 1
        return real(argv, capture_output=True, text=True,
                    timeout=timeout, cwd=cwd)

    svc.fast = FastPathRenderer(runner=flaky)
    svc.register("bld-1", _comp(), now=NOW)
    out = svc.dispatch("bld-1", segs, [], [], CLOCK)
    assert out["status"] == "observer_lost"
    b = svc._build("bld-1")
    assert b["status"] == "observer_lost"
    progress = json.loads(
        (tmp / "builds" / "bld-1" / "progress.json").read_text())
    assert len(progress["completed_sections"]) == 4
    # resume with a healthy runner: sections are cached, not re-encoded
    norm_before = calls["norm"]
    svc.fast = FastPathRenderer()
    out2 = svc.dispatch("bld-1", segs, [], [], CLOCK)
    assert out2["status"] == "succeeded"
    assert calls["norm"] == norm_before     # zero re-encodes
    v = _probe_frames(out2["path"])
    assert int(v["nb_frames"]) == 120


def test_inputs_cache_identity(stack):
    """Identical inputs reuse the same normalized section file; changed
    inputs produce a different cache key."""
    db, arts, svc, tmp = stack
    f = FastPathRenderer()
    src = _clip(tmp, "c0", 1.0, rate=24)   # non-exact → real encode
    cache = tmp / "cache"
    cache.mkdir()
    a, _ = f.normalize_section(src, 30, 30, cache)
    b, _ = f.normalize_section(src, 30, 30, cache)
    assert a == b and a.exists()
    c, _ = f.normalize_section(src, 24, 30, cache)
    assert c != a


def test_hypit_build_lifecycle(stack):
    db, arts, svc, tmp = stack
    sent = tmp / "returned.mp4"
    _color_mp4(sent, 1.0, rate=30, size="360x640")

    class R:
        def __init__(self, rc, out=""):
            self.returncode, self.stdout, self.stderr = rc, out, ""

    def fake(argv):
        if argv[0] == "check":
            return R(0, json.dumps({"format": "hypit.cli-check@1", "ok": True}))
        if argv[0] == "plan":
            return R(0, json.dumps({"format": "hypit.cli-plan@1", "ok": True, "requestCount": 0, "needs": []}))
        if argv[0] == "build":
            return R(0, '{"format":"hypit.cli-build@1", "build":{"id":"b-777","work":{"state":"working"},"result":{"state":"missing"}}}')
        if argv[0] == "status":
            return R(0, '{"format":"hypit.cli-status@1", "build":{"id":"b-777","work":{"state":"done","outcome":"complete"},"result":{"state":"complete"}}}')
        if argv[0] == "get":
            dest = argv[argv.index("--to") + 1]
            open(dest, "wb").write(sent.read_bytes())
            return R(0, json.dumps({"format": "hypit.cli-get@1", "build": "b-777", "output": argv[argv.index("--output")+1], "path": dest}))
        return R(1, "bad argv")

    (tmp / "render.svrun").write_text("fixture run")
    (tmp / "r.svrun").write_text("fixture run")
    svc.hypit = HypitBuildRunner(runner=fake)
    svc.register("bld-h", _comp("hypit"), now=NOW)
    out = svc.dispatch("bld-h", [], [], [], CLOCK,
                       svrun_path=tmp / "render.svrun")
    assert out["remote_build_id"] == "b-777"
    assert svc.observe("bld-h")["status"] == "succeeded"
    got = svc.collect("bld-h")
    assert got["artifact_id"]
    row = db.uow().artifacts.get(got["artifact_id"])
    assert row["sha256"] == got["sha256"]


def test_observer_timeout_not_failure(stack):
    db, arts, svc, tmp = stack

    class R:
        def __init__(self, rc, out=""):
            self.returncode, self.stdout, self.stderr = rc, out, ""

    def fake(argv):
        if argv[0] == "check":
            return R(0, json.dumps({"format": "hypit.cli-check@1", "ok": True}))
        if argv[0] == "plan":
            return R(0, json.dumps({"format": "hypit.cli-plan@1", "ok": True, "requestCount": 0, "needs": []}))
        if argv[0] == "build":
            return R(0, '{"format":"hypit.cli-build@1", "build":{"id":"b-1","work":{"state":"working"},"result":{"state":"missing"}}}')
        raise subprocess.TimeoutExpired(argv, 30)

    (tmp / "render.svrun").write_text("fixture run")
    (tmp / "r.svrun").write_text("fixture run")
    svc.hypit = HypitBuildRunner(runner=fake)
    svc.register("bld-h", _comp("hypit"), now=NOW)
    svc.dispatch("bld-h", [], [], [], CLOCK, svrun_path=tmp / "r.svrun")
    obs = svc.observe("bld-h")
    assert obs["status"] == "unknown"           # timeout ≠ failed
    assert svc._build("bld-h")["status"] == "observer_lost"


def test_collect_requires_success(stack):
    db, arts, svc, tmp = stack
    svc.register("bld-1", _comp(), now=NOW)
    with pytest.raises(ContractError, match="not_collectable"):
        svc.collect("bld-1")


def test_output_mismatch_refuses(stack):
    db, arts, svc, tmp = stack
    segs = [{"id": "s0", "src": str(_clip(tmp, "c0", 1.0)),
             "frames": 30}]
    svc.register("bld-1", _comp(), now=NOW)
    svc.dispatch("bld-1", segs, [], [], CLOCK)
    # tamper the recorded sha → collect must refuse
    svc._set("bld-1", output_sha256="0" * 64)
    with pytest.raises(ContractError, match="output_mismatch"):
        svc.collect("bld-1")


def test_caption_ass_content():
    from modules.factory.rendering import captions_ass
    ass = captions_ass([{"text": "Don't stop", "start_frame": 0,
                        "end_frame": 30}])
    assert "Don't stop" in ass
    assert "0:00:00.00" in ass and "0:00:01.00" in ass
    with pytest.raises(ValueError):
        captions_ass([{"text": "bad {\\pos(0,0)}",
                       "start_frame": 0, "end_frame": 10}])
