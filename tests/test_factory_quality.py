"""F24: technical QC, changed-region gate, hash-bound reviews,
stale acceptance, bounded repair."""
import json
import subprocess

import pytest

from modules.factory.artifacts.registry import ArtifactStore
from modules.factory.domain.errors import ContractError
from modules.factory.quality import (QualityService, RegionGate,
                                     TechnicalQC)
from modules.factory.rendering import FastPathRenderer
from modules.factory.reviews import ReviewPack, required_evidence
from modules.factory.store import Database
from modules.factory.testing.fixtures import _color_mp4, _moving_mp4

NOW = "2026-09-17T00:00:00Z"
CLOCK = {"fps": 30, "width": 360, "height": 640}
EXPECTED = {"frames": 60, "fps": 30, "width": 360, "height": 640,
            "has_audio": False}


@pytest.fixture
def stack(tmp_path):
    db = Database(tmp_path / "f.db")
    qc = QualityService(db, technical=TechnicalQC(),
                        region_gate=RegionGate())
    return db, qc, tmp_path


def _clip(tmp, name, seconds=1.0, rate=30, color="0x3366cc"):
    p = tmp / f"{name}.mp4"
    (_color_mp4 if color == "0x000000" else _moving_mp4)(p, seconds, rate=rate, color=color, size="360x640")
    return p


def _render(tmp, name, seg_specs):
    ws = tmp / name
    segs = [{"id": f"s{i}", "src": str(p), "frames": f}
            for i, (p, f) in enumerate(seg_specs)]
    return FastPathRenderer().render(ws, segs, [], [], CLOCK)


def test_technical_clean(stack):
    db, qc, tmp = stack
    final = _render(tmp, "good", [(_clip(tmp, "a", 1.0), 30),
                                  (_clip(tmp, "b", 1.0), 30)])
    out = qc.inspect("chk-1", final, EXPECTED)
    assert out["verdict"] == "pass"
    assert out["report"]["frames"] == 60


def test_technical_wrong_frame_count(stack):
    db, qc, tmp = stack
    final = _render(tmp, "cnt", [(_clip(tmp, "a", 1.0), 30)])
    out = qc.inspect("chk-1", final, EXPECTED)      # expects 60
    assert out["verdict"] == "fail"
    assert any(f["code"] == "wrong_frame_count"
               for f in out["report"]["findings"])


def test_technical_black_section(stack):
    db, qc, tmp = stack
    black = _clip(tmp, "blk", 1.0, color="0x000000")
    final = _render(tmp, "mixed", [(_clip(tmp, "a", 1.0), 30),
                                   (black, 30)])
    out = qc.inspect("chk-1", final,
                     {**EXPECTED, "frames": 60})
    codes = {f["code"] for f in out["report"]["findings"]}
    assert "black_section" in codes
    loc = next(f for f in out["report"]["findings"]
               if f["code"] == "black_section")
    assert "s" in loc["at"]            # carries a time location


def test_technical_corrupt(stack):
    db, qc, tmp = stack
    bad = tmp / "bad.mp4"
    bad.write_bytes(b"not-a-video")
    out = qc.inspect("chk-1", bad, EXPECTED)
    assert out["verdict"] == "fail"


def test_region_gate_intermediates(stack):
    db, qc, tmp = stack
    same = {"0-30": "a"*64, "30-60": "b"*64}
    diff = {"0-30": "a"*64, "30-60": "c"*64}        # undeclared change
    out = qc.gate.compare_intermediates(
        same, diff, [{"start_frame": 0, "end_frame": 30},
                     {"start_frame": 30, "end_frame": 60}])
    assert not out["ok"]
    assert out["diffs"][0]["region"] == "30-60"
    assert out["diffs"][0]["code"] == "undeclared_change"


def test_region_gate_finals_real(stack):
    """A vs B: declared change inside B's region passes; an injected
    difference outside declared regions fails with its location."""
    db, qc, tmp = stack
    shared1, shared2 = _clip(tmp, "sh1", 1.0), _clip(tmp, "sh2", 1.0)
    a = _render(tmp, "va", [(shared1, 30), (shared2, 30)])
    # B differs in declared region [0,30): different first shot
    b = _render(tmp, "vb", [(_clip(tmp, "b-alt", 1.0,
                                   color="0xcc3333"), 30),
                            (shared2, 30)])
    unchanged = [{"start_frame": 30, "end_frame": 60}]
    out = qc.check_regions("chk-r", a, b, unchanged, 30)
    assert out["verdict"] == "pass"
    assert out["regions"][0]["ssim"] >= 0.98
    # C also changed the tail (undeclared) → gate catches it
    c = _render(tmp, "vc", [(_clip(tmp, "c-alt", 1.0,
                                   color="0xcc3333"), 30),
                            (_clip(tmp, "c-tail", 1.0,
                                   color="0x33cc33"), 30)])
    bad = qc.check_regions("chk-r2", a, c, unchanged, 30)
    assert bad["verdict"] == "fail"
    assert bad["diffs"][0]["region"] == "30-60"


def test_audio_region_leak(stack):
    db, qc, tmp = stack
    from modules.factory.audio import pcm
    base = pcm.sine(2.0)
    other = pcm.gain_db(base, -6.0)     # gain change mid-file
    mixed = base[:22050] + other[22050:]
    region = {"start_s": 1.5, "end_s": 2.0}
    out = qc.gate.compare_audio_region(base, mixed, region)
    assert not out["ok"]
    assert out["code"] == "undeclared_change"
    ok = qc.gate.compare_audio_region(base, base, region)
    assert ok["ok"]


def test_acceptance_hash_bound(stack):
    # Go through public planning, compilation, rendering, collection and review.
    from modules.factory.production import ProductionService
    from modules.factory.composition import CompositionService
    from modules.factory.rendering import RenderService
    db,qc,tmp=stack
    arts=ArtifactStore(tmp/"arts",db)
    source=arts.intake_file(_clip(tmp,"source",2),provenance="manual",source_key="source",requested_kind="video")
    plan=ProductionService(db).plan("plan","exp",1,[{"variant":"A","slot":"main","duration_s":2,"request":{}}],
                                   "manual","import",[2],now=NOW)["plan"]
    segments=[{"id":"s1","kind":"picture","artifact_id":source.id,"sha256":source.sha256,
               "in_frame":0,"out_frame":60,"source_in_s":0,"source_out_s":2}]
    comp=CompositionService(db,arts,tmp/"comps").compile("comp","exp","A","plan",segments,[],CLOCK,
                           renderer="ffmpeg_fast",plan_hash=plan["plan_hash"],now=NOW)["composition"]
    render=RenderService(db,arts,tmp/"builds"); render.register("build",comp,now=NOW)
    out=render.dispatch("build",[{"src":str(arts.path_for(source.id)),"frames":60}],[],[],CLOCK)
    final=out["path"]; art=render.collect("build")
    binding=qc.binding(final,"comp",art["artifact_id"])
    tech=qc.inspect("tech",final,EXPECTED,binding=binding)
    with pytest.raises(ContractError,match="missing_required_review:creative"):
        qc.accept(final,["tech"],binding=binding)
    qc.record_verdict("creative",tech["target_hash"],"creative","pass",binding=binding,reviewer="fixture operator")
    assert qc.accept(final,["tech","creative"],binding=binding)["accepted"]
    stale={**binding,"plan_hash":"stale"}
    with pytest.raises(ContractError,match="stale_composition_binding"):
        qc.accept(final,["tech","creative"],binding=stale)


def test_stale_review_rejected(stack):
    db, qc, tmp = stack
    final = _render(tmp, "st", [(_clip(tmp, "a", 1.0), 30),
                                (_clip(tmp, "b", 1.0), 30)])
    qc.inspect("chk-1", final, EXPECTED)
    # bytes change after the review → review is stale
    final.write_bytes(final.read_bytes() + b"x")
    marked = qc.invalidate_stale(final, ["chk-1"])
    assert marked == ["chk-1"]
    with pytest.raises(ContractError, match="stale_review"):
        qc.accept(final, ["chk-1"])


def test_bounded_repair(stack):
    db, qc, tmp = stack
    qc.max_repairs = 1
    first = qc.request_repair("plan-1", "caption_drift")
    assert first["repair_seq"] == 1
    with pytest.raises(ContractError, match="repair_budget_exceeded"):
        qc.request_repair("plan-1", "again")


def test_required_evidence_coverage():
    segs = [{"id": "s0", "in_frame": 0, "out_frame": 30,
             "role": "product"},
            {"id": "s1", "in_frame": 30, "out_frame": 60,
             "transition_out": "crossfade"}]
    caps = [{"id": "c0", "text": "hi", "start_frame": 5,
             "end_frame": 20}]
    reqs = required_evidence(segs, caps, 30)
    kinds = {r["kind"] for r in reqs}
    assert {"first_frame", "last_frame", "product_check",
            "transition", "caption_join", "caption_text"} <= kinds
    prod = next(r for r in reqs if r["kind"] == "product_check")
    assert prod["frame"] == 15


def test_review_pack_extracts(stack, tmp_path):
    db, qc, tmp = stack
    final = _render(tmp, "pk", [(_clip(tmp, "a", 1.0), 30),
                                (_clip(tmp, "b", 1.0), 30)])
    pack = ReviewPack(tmp / "packs")
    segs = [{"id": "s0", "in_frame": 0, "out_frame": 30}]
    index = pack.build("p1", final, segs, [{"id": "c0", "text": "hi",
                                            "start_frame": 0,
                                            "end_frame": 15}], 30)
    assert all(e["extracted"] for e in index["evidence"])
    assert len(index["evidence"]) >= 4
