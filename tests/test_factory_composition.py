"""F22: composition compiler — deterministic SVML/SVS/SVRun, explicit
bindings, caption escaping, diagnostics, hosted-call audit, revision
chain, check/plan gate."""
import json

import pytest

from modules.factory.artifacts.registry import ArtifactStore
from modules.factory.composition import (CompositionService, HypitGate,
                                         audit_imports, audit_plan)
from modules.factory.store import Database
from modules.factory.testing.fixtures import _color_mp4

NOW = "2026-09-17T00:00:00Z"
CLOCK = {"fps": 30, "width": 1080, "height": 1920}


@pytest.fixture
def stack(tmp_path):
    db = Database(tmp_path / "f.db")
    arts = ArtifactStore(tmp_path / "arts", db)
    svc = CompositionService(db, arts, tmp_path / "comps")
    return db, arts, svc, tmp_path


def _clip(arts, tmp, seconds, key, color=None):
    p = tmp / f"{key}.mp4"
    _color_mp4(p, seconds,
               color=color or f"0x{abs(hash(key)) % 0xffffff:06x}")
    return arts.intake_bytes(p.read_bytes(), provenance="manual",
                             source_key=key, requested_kind="video")


def _segments(arts, tmp, count=6, fps=30, dur=4.0):
    """Six 4 s shots = 720 frames + a 180-frame tail → 900 total."""
    segs = []
    pos = 0
    for i in range(count):
        art = _clip(arts, tmp, dur, f"clip{i}")
        frames = int(dur * fps)
        segs.append({"id": f"s{i}", "kind": "picture",
                     "artifact_id": art.id, "sha256": art.sha256,
                     "src": f"assets/{art.id}.mp4",
                     "in_frame": pos, "out_frame": pos + frames,
                     "source_in_s": 0.0, "source_out_s": dur})
        pos += frames
    tail = _clip(arts, tmp, 6.0, "tail")
    segs.append({"id": "s6", "kind": "picture",
                 "artifact_id": tail.id, "sha256": tail.sha256,
                 "src": f"assets/{tail.id}.mp4",
                 "in_frame": pos, "out_frame": pos + 180,
                 "source_in_s": 0.0, "source_out_s": 6.0})
    return segs


def test_compile_canonical_900_frames(stack):
    db, arts, svc, tmp = stack
    out = svc.compile("comp-a", "exp1", "A", "plan-1",
                      _segments(arts, tmp), [], CLOCK, now=NOW)
    comp = out["composition"]
    assert comp["total_frames"] == 900
    assert comp["status"] == "draft" and out["diagnostics"] == []
    assert len(comp["bindings"]) == 7
    assert all(b["artifact_id"] and b["sha256"] for b in
               comp["bindings"])
    svml = open(out["files"]["video.svml"]).read()
    assert 'end="30.000s"' in svml
    assert "norm-s0" in svml and "src-s6" in svml


def test_compile_deterministic(stack):
    db, arts, svc, tmp = stack
    segs = _segments(arts, tmp)
    a = svc.compile("comp-a", "exp1", "A", "plan-1", segs, [], CLOCK,
                    now=NOW)
    b = svc.compile("comp-a", "exp1", "A", "plan-1", segs, [], CLOCK,
                    now=NOW)
    assert b.get("reused_revision") is True
    assert a["composition"]["content_hash"] == \
        b["composition"]["content_hash"]
    # same variant key across comp ids is also identical bytes
    c = svc.compile("comp-a2", "exp1", "A", "plan-1", segs, [], CLOCK,
                    now=NOW)
    assert c["composition"]["files"]["video.svml"] == \
        a["composition"]["files"]["video.svml"]


def test_caption_escaping(stack):
    db, arts, svc, tmp = stack
    caps = [{"id": "c1", "placement": "heading",
             "text": "Don't say \"it's\" <free> & ready — cafés ✓",
             "start_frame": 0, "end_frame": 60}]
    out = svc.compile("comp-a", "exp1", "A", "plan-1",
                      _segments(arts, tmp), caps, CLOCK, now=NOW)
    svml = open(out["files"]["video.svml"]).read()
    assert "&apos;" in svml            # named entity, not &#x27;
    assert "&#x27;" not in svml
    assert "&quot;" in svml and "&lt;" in svml and "&amp;" in svml
    assert "cafés" in svml             # unicode passes through
    cap_bindings = [b for b in out["composition"]["bindings"]
                    if b["role"] == "caption"]
    assert cap_bindings[0]["sha256"]


def test_missing_asset_diagnostic(stack):
    db, arts, svc, tmp = stack
    segs = _segments(arts, tmp)
    segs[2]["artifact_id"] = "art:gone"
    out = svc.compile("comp-a", "exp1", "A", "plan-1", segs, [],
                      CLOCK, now=NOW)
    assert out["composition"]["status"] == "failed"
    assert any(d["code"] == "missing_asset"
               and d["at"] == "segment[s2]"
               for d in out["diagnostics"])


def test_stale_selection_diagnostic(stack):
    db, arts, svc, tmp = stack
    segs = _segments(arts, tmp)
    segs[1]["sha256"] = "0" * 64       # stale hash ≠ artifact
    out = svc.compile("comp-a", "exp1", "A", "plan-1", segs, [],
                      CLOCK, now=NOW)
    assert any(d["code"] == "stale_selection" and "s1" in d["at"]
               for d in out["diagnostics"])


def test_insufficient_duration_diagnostic(stack):
    db, arts, svc, tmp = stack
    segs = _segments(arts, tmp)
    segs[0]["source_out_s"] = 9.0      # clip only has 4 s
    out = svc.compile("comp-a", "exp1", "A", "plan-1", segs, [],
                      CLOCK, now=NOW)
    assert any(d["code"] == "insufficient_duration"
               for d in out["diagnostics"])


def test_unsupported_effect_routes(stack):
    db, arts, svc, tmp = stack
    segs = _segments(arts, tmp)
    segs[0]["effects"] = ["kenburns"]
    fast = svc.compile("comp-fast", "exp1", "A", "plan-1", segs, [],
                       CLOCK, renderer="ffmpeg_fast", now=NOW)
    assert any(d["code"] == "unsupported_effect"
               for d in fast["diagnostics"])
    hy = svc.compile("comp-hy", "exp1", "A", "plan-1", segs, [],
                     CLOCK, renderer="hypit", now=NOW)
    assert hy["diagnostics"] == []


def test_revision_on_changed_selection(stack):
    db, arts, svc, tmp = stack
    segs = _segments(arts, tmp)
    a = svc.compile("comp-a", "exp1", "A", "plan-1", segs, [], CLOCK,
                    now=NOW)
    new = _clip(arts, tmp, 4.0, "replacement")
    segs[2] = dict(segs[2], artifact_id=new.id, sha256=new.sha256,
                   src=f"assets/{new.id}.mp4")
    b = svc.compile("comp-a", "exp1", "A", "plan-1", segs, [], CLOCK,
                    now=NOW)
    assert b["composition"]["revision"] == 2
    assert b["composition"]["parent_hash"] == \
        a["composition"]["content_hash"]
    # only the changed binding's hash differs
    a_b = {x["binding"]: x["sha256"]
           for x in a["composition"]["bindings"]}
    b_b = {x["binding"]: x["sha256"]
           for x in b["composition"]["bindings"]}
    diffs = [k for k in a_b if a_b[k] != b_b.get(k)]
    assert diffs == ["src-s2"]


def test_hosted_import_audit():
    svml = '<svml><import as="g" from="@hypit/video-gen@1"/></svml>'
    diags = audit_imports(svml)
    assert diags and diags[0]["code"] == "hosted_component"


def test_plan_audit_rejects_hosted_step():
    diags = audit_plan({"steps": [{"name": "make-clip",
                                   "kind": "generation"}]})
    assert diags and diags[0]["code"] == "hosted_step"
    assert audit_plan({"steps": [{"name": "render",
                                  "kind": "render"}]}) == []


def test_gate_check_and_plan(stack):
    db, arts, svc, tmp = stack
    out = svc.compile("comp-a", "exp1", "A", "plan-1",
                      _segments(arts, tmp), [], CLOCK, now=NOW)

    class R:
        def __init__(self, rc, out):
            self.returncode, self.stdout, self.stderr = rc, out, ""

    calls = []

    def fake(argv):
        calls.append(argv)
        if argv[0] == "check":
            return R(0, '{"ok": true}')
        return R(0, '{"steps": [{"name": "render", "kind": "render"}]}')

    gate = HypitGate(runner=fake)
    chk = gate.check(out["files"]["video.svml"])
    assert chk["ok"] is True
    pl = gate.plan(out["files"]["render.svrun"])
    assert pl["ok"] is True
    assert calls[0] == ["check", out["files"]["video.svml"]]

    def hostile(argv):
        return R(0, '{"steps": [{"name": "gen", "kind": "provider"}]}')

    bad = HypitGate(runner=hostile).plan(out["files"]["render.svrun"])
    assert bad["ok"] is False
    assert bad["diagnostics"][0]["code"] == "hosted_step"
