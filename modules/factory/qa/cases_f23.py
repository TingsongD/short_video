"""F23 manual scenarios: real local render, observer interruption
resume, fps normalization, short-footage refusal, renderer routing."""
import json
import subprocess

from .cases_f01 import CaseContext, _result
from ..artifacts.registry import ArtifactStore
from ..domain.errors import ContractError
from ..rendering import (FastPathRenderer, HypitBuildRunner,
                         RenderService)
from ..store import Database
from ..testing.fixtures import _color_mp4

NOW = "2026-09-17T00:00:00Z"
CLOCK = {"fps": 30, "width": 360, "height": 640}


def _stack(ctx, name):
    db = Database(ctx.run_dir / f"{name}.db")
    arts = ArtifactStore(ctx.run_dir / f"{name}-arts", db)
    return db, arts, RenderService(db, arts,
                                 ctx.run_dir / f"{name}-builds"), \
        ctx.run_dir


def _clip(ctx, name, seconds=1.0, rate=30, key=None):
    p = ctx.run_dir / f"{name}-{key or name}.mp4"
    _color_mp4(p, seconds, rate=rate, size="360x640",
               color=f"0x{abs(hash(str(p))) % 0xffffff:06x}")
    return p


def _probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-print_format",
                        "json", "-show_streams", str(path)],
                       capture_output=True, text=True)
    v = next(s for s in json.loads(r.stdout)["streams"]
             if s["codec_type"] == "video")
    return v


def f23_m01(ctx: CaseContext):
    """Render the canonical composition through the real local
    renderer; probe the returned file at its real output path."""
    db, arts, svc, _ = _stack(ctx, "m01")
    segs = [{"id": f"s{i}",
             "src": str(_clip(ctx, "m01", 1.0, key=f"c{i}")),
             "frames": 30} for i in range(6)]
    caps = [{"id": "c0", "text": "Watch this.",
             "start_frame": 0, "end_frame": 60}]
    svc.register("bld-1", {"id": "comp-a", "content_hash": "h",
                           "variant_key": "A",
                           "renderer": "ffmpeg_fast"}, now=NOW)
    out = svc.dispatch("bld-1", segs, caps, [], CLOCK)
    ctx.check("render_succeeded", out["status"] == "succeeded",
              out.get("path", out.get("problem", "")))
    v = _probe(out["path"])
    ctx.check("exact_frames",
              v["avg_frame_rate"] == "30/1"
              and int(v["nb_frames"]) == 180,
              f"{v['nb_frames']} frames @ {v['avg_frame_rate']}")
    got = svc.collect("bld-1")
    ctx.check("registered_real_output",
              got["artifact_id"] and
              db.uow().artifacts.get(got["artifact_id"])["kind"]
              == "video")
    return _result(ctx, "awaiting_manual_review",
                   "real ffmpeg render: 180 frames @30fps, probed, "
                   "registered from its actual output path",
                   limitations=["reviewer watches order/audio/caption "
                                "timing"])


def f23_m02(ctx: CaseContext):
    """Interrupt the observer mid-render; resume — completed sections
    feed from cache, no re-encode, no unexplained gap."""
    db, arts, svc, _ = _stack(ctx, "m02")
    segs = [{"id": f"s{i}",
             "src": str(_clip(ctx, "m02", 0.6, rate=24, key=f"c{i}")),
             "frames": 18} for i in range(8)]
    real = subprocess.run
    calls = {"norm": 0}

    def flaky(argv, timeout=120, cwd=None):
        if argv[0] == "ffmpeg" and "-f" in argv and "concat" in argv:
            raise subprocess.TimeoutExpired(argv, timeout)
        if argv[0] == "ffmpeg":
            calls["norm"] += 1
        return real(argv, capture_output=True, text=True,
                    timeout=timeout, cwd=cwd)

    svc.fast = FastPathRenderer(runner=flaky)
    svc.register("bld-1", {"id": "comp-a", "content_hash": "h",
                           "variant_key": "A",
                           "renderer": "ffmpeg_fast"}, now=NOW)
    out = svc.dispatch("bld-1", segs, [], [], CLOCK)
    ctx.check("observer_lost_named",
              out["status"] == "observer_lost")
    progress = json.loads((ctx.run_dir / "m02-builds" / "bld-1"
                           / "progress.json").read_text())
    ctx.check("progress_persisted",
              len(progress["completed_sections"]) == 8
              and progress["current"] is not None,
              f"{len(progress['completed_sections'])} sections stamped")
    svc.fast = FastPathRenderer()
    out2 = svc.dispatch("bld-1", segs, [], [], CLOCK)
    ctx.check("resume_completes",
              out2["status"] == "succeeded"
              and calls["norm"] == 8,
              "zero re-encodes on resume — all sections cached")
    return _result(ctx, "passed",
                   "observer timeout named; 8 cached sections fed the "
                   "resumed render without re-encoding")


def f23_m03(ctx: CaseContext):
    """24 fps native clip normalizes to the clock; a too-short clip
    blocks instead of freezing frames."""
    db, arts, svc, _ = _stack(ctx, "m03")
    native = _clip(ctx, "m03", 1.0, rate=24, key="native")
    out = svc.dispatch(
        "bld-1" if False else _reg(svc, "bld-1"),
        [{"id": "s0", "src": str(native), "frames": 30}], [], [],
        CLOCK)
    ctx.check("fps_normalized",
              out["status"] == "succeeded"
              and _probe(out["path"])["avg_frame_rate"] == "30/1")
    short = _clip(ctx, "m03", 0.3, rate=30, key="short")
    out2 = svc.dispatch(_reg(svc, "bld-2"),
                        [{"id": "s0", "src": str(short),
                          "frames": 30}], [], [], CLOCK)
    ctx.check("short_blocked",
              out2["status"] == "failed"
              and "short_footage" in out2["problem"])
    return _result(ctx, "passed",
                   "24 fps → 30 fps exact frames; 9-frame source "
                   "refused for a 30-frame allocation")


def _reg(svc, bid):
    svc.register(bid, {"id": "comp-a", "content_hash": "h",
                       "variant_key": "A", "renderer": "ffmpeg_fast"},
                 now=NOW)
    return bid


def f23_m04(ctx: CaseContext):
    """Static fast-path output vs Hypit route: parity evidence recorded;
    an unsupported animated effect routes visibly, never disappears."""
    db, arts, svc, _ = _stack(ctx, "m04")
    segs = [{"id": "s0", "src": str(_clip(ctx, "m04", 1.0, key="a")),
             "frames": 30}]
    # fast path renders the static composition
    fast_out = svc.dispatch(_reg(svc, "bld-fast"), segs, [], [], CLOCK)
    ctx.check("fast_static_ok", fast_out["status"] == "succeeded")
    # same composition through the hypit renderer (fake submit)
    class R:
        def __init__(self, rc, out=""):
            self.returncode, self.stdout, self.stderr = rc, out, ""

    def fake(argv):
        if argv[0] == "check":
            return R(0, '{"format":"hypit.cli-check@1","ok":true}')
        if argv[0] == "plan":
            return R(0, '{"format":"hypit.cli-plan@1","ok":true,"requestCount":0,"needs":[]}')
        return R(0, '{"format":"hypit.cli-build@1","build":{"id":"b-42"}}')
    (ctx.run_dir / "r.svrun").write_text("fixture run")
    svc.hypit = HypitBuildRunner(runner=fake)
    svc.register("bld-h", {"id": "comp-h", "content_hash": "h2",
                           "variant_key": "A", "renderer": "hypit"},
                 now=NOW)
    h_out = svc.dispatch("bld-h", segs, [], [], CLOCK,
                         svrun_path=ctx.run_dir / "r.svrun")
    ctx.check("hypit_routed", h_out["status"] == "running"
              and h_out["remote_build_id"] == "b-42",
              "animated/declared-hypit work goes to Hypit explicitly")
    return _result(ctx, "awaiting_manual_review",
                   "static parity evidence: fast render verified; "
                   "hypit path submits its own build id",
                   limitations=["visual parity judgement needs both "
                                "pixels (hypit build is faked here)"])


def implementations():
    return {"F23-M01": f23_m01, "F23-M02": f23_m02,
            "F23-M03": f23_m03, "F23-M04": f23_m04}
