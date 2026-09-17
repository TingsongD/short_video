"""F22 manual scenarios: canonical four-variant compile, caption
escaping, hosted-call gate, deterministic revision chain."""
import json
import subprocess

from .cases_f01 import CaseContext, _result
from ..artifacts.registry import ArtifactStore
from ..composition import (CompositionService, HypitGate, audit_imports)
from ..store import Database
from ..testing.fixtures import _color_mp4

NOW = "2026-09-17T00:00:00Z"
CLOCK = {"fps": 30, "width": 1080, "height": 1920}


def _stack(ctx, name):
    db = Database(ctx.run_dir / f"{name}.db")
    arts = ArtifactStore(ctx.run_dir / f"{name}-arts", db)
    return db, arts, CompositionService(db, arts,
                                        ctx.run_dir / f"{name}-comps")


def _clip(arts, ctx, name, seconds, key):
    p = ctx.run_dir / f"{name}-{key}.mp4"
    _color_mp4(p, seconds, color=f"0x{abs(hash(key)) % 0xffffff:06x}")
    return arts.intake_bytes(p.read_bytes(), provenance="manual",
                             source_key=key, requested_kind="video")


CHANGED_SLOT = {"B": "s0", "C": "s3", "D": "s6"}


def _segments(arts, ctx, name, variant=""):
    """7 shots → 900 frames. Shared slots use the SAME clip artifact
    across variants; the variant's declared slot gets a unique clip."""
    changed = CHANGED_SLOT.get(variant)
    segs, pos = [], 0
    for i in range(7):
        dur = 4.0 if i < 6 else 6.0
        frames = int(dur * 30) if i < 6 else 180
        slot = f"s{i}"
        key = (f"{name}-{variant}-{slot}" if slot == changed
               else f"{name}-{slot}")
        art = _clip(arts, ctx, name, dur, key)
        segs.append({"id": slot, "kind": "picture",
                     "artifact_id": art.id, "sha256": art.sha256,
                     "in_frame": pos, "out_frame": pos + frames,
                     "source_in_s": 0.0, "source_out_s": dur})
        pos += frames
    return segs


def _real_gate():
    return HypitGate()


def f22_m01(ctx: CaseContext):
    """Compile all four variants; real hypit check/plan; only intended
    regions differ."""
    db, arts, svc = _stack(ctx, "m01")
    comps, svmls = {}, {}
    for v in "ABCD":
        segs = _segments(arts, ctx, "m01", variant=v)
        out = svc.compile(f"comp-{v.lower()}", "exp1", v, "plan-1",
                          segs, [], CLOCK, now=NOW)
        comps[v], svmls[v] = out["composition"], \
            open(out["files"]["video.svml"]).read()
    ctx.check("all_900_frames",
              all(c["total_frames"] == 900 for c in comps.values()))
    ctx.check("explicit_bindings",
              all(len(c["bindings"]) == 7 and all(
                  b["artifact_id"] and b["sha256"]
                  for b in c["bindings"]) for c in comps.values()))
    # B/C/D differ from A only through their changed segment bindings
    a_b = {b["binding"]: b["sha256"] for b in comps["A"]["bindings"]}
    for v in "BCD":
        v_b = {b["binding"]: b["sha256"] for b in comps[v]["bindings"]}
        diffs = sum(1 for k in a_b if a_b[k] != v_b[k])
        ctx.check(f"variant_{v}_one_diff", diffs == 1,
                  f"{diffs} binding diffs vs control")
    # real pinned-runtime check/plan on variant A
    gate = _real_gate()
    files = {"svml": ctx.run_dir / "m01-comps" / "comp-a" / "r1" /
             "video.svml",
             "svrun": ctx.run_dir / "m01-comps" / "comp-a" / "r1" /
             "render.svrun"}
    chk = gate.check(files["svml"])
    ctx.check("hypit_check", chk["ok"],
              json.dumps(chk.get("diagnostics", "valid"))[:120])
    pl = gate.plan(files["svrun"])
    ctx.check("hypit_plan_local_only", pl["ok"],
              "every planned need is a local @hypit capability")
    return _result(ctx, "passed",
                   "4 variants × 900 frames, explicit bindings, real "
                   "hypit check + plan audit clean")


def f22_m02(ctx: CaseContext):
    """Captions with apostrophes, quotes, ampersands, angle brackets,
    Unicode → literal visible text, no entity fragments."""
    db, arts, svc = _stack(ctx, "m02")
    text = ("Don't say \"it's\" <free> & ready — cafés 日本語 ✓")
    caps = [{"id": "c1", "placement": "heading", "text": text,
             "start_frame": 0, "end_frame": 90}]
    out = svc.compile("comp-a", "exp1", "A", "plan-1",
                      _segments(arts, ctx, "m02"), caps, CLOCK, now=NOW)
    svml = open(out["files"]["video.svml"]).read()
    ctx.check("no_numeric_entities",
              "&#" not in svml,
              "Hypit 0.1.8 decodes named entities only")
    ctx.check("named_entities_present",
              "&apos;" in svml and "&quot;" in svml
              and "&lt;" in svml and "&amp;" in svml)
    ctx.check("unicode_preserved", "cafés" in svml and "日本語" in svml)
    # the escaped body decodes back to the intended text
    import xml.sax.saxutils as sx
    frag = svml.split('id="c1"', 1)[1].split(">", 1)[1].split("<")[0]
    back = sx.unescape(frag, {"&apos;": "'", "&quot;": '"'})
    ctx.check("roundtrip_text", back == text, back[:60])
    return _result(ctx, "awaiting_manual_review",
                   "markup contains only named entities and decodes to "
                   "the intended text; reviewer watches rendered pixels",
                   limitations=["pixel check needs a render (F23)"])


def f22_m03(ctx: CaseContext):
    """Remove a required clip and inject a hosted-generation import:
    gate blocks with exact locations; no paid calls."""
    db, arts, svc = _stack(ctx, "m03")
    segs = _segments(arts, ctx, "m03")
    segs[2]["artifact_id"] = "art:removed"
    out = svc.compile("comp-a", "exp1", "A", "plan-1", segs, [],
                      CLOCK, now=NOW)
    ctx.check("missing_located",
              out["composition"]["status"] == "failed" and any(
                  d["code"] == "missing_asset"
                  and d["at"] == "segment[s2]"
                  for d in out["diagnostics"]))
    # inject a hosted import into otherwise-valid markup
    good = svc.compile("comp-b", "exp1", "A", "plan-1",
                       _segments(arts, ctx, "m03b"), [], CLOCK, now=NOW)
    svml = open(good["files"]["video.svml"]).read().replace(
        '<import as="film" from="@hypit/film@1"/>',
        '<import as="g" from="@hypit/video-gen@1"/>')
    diags = audit_imports(svml)
    ctx.check("hosted_flagged",
              any(d["code"] == "hosted_component"
                  and "video-gen" in d["detail"] for d in diags))
    return _result(ctx, "passed",
                   "missing asset named at segment[s2]; hosted import "
                   "fails the vocabulary audit — no paid generation")


def f22_m04(ctx: CaseContext):
    """Recompile unchanged inputs → identical revision; change one
    selection → traceable new revision affecting only dependencies."""
    db, arts, svc = _stack(ctx, "m04")
    segs = _segments(arts, ctx, "m04")
    a = svc.compile("comp-a", "exp1", "A", "plan-1", segs, [],
                    CLOCK, now=NOW)
    b = svc.compile("comp-a", "exp1", "A", "plan-1", segs, [],
                    CLOCK, now=NOW)
    ctx.check("recompile_identical",
              b.get("reused_revision") is True
              and b["composition"]["content_hash"] ==
              a["composition"]["content_hash"])
    new = _clip(arts, ctx, "m04", 4.0, "replacement")
    segs[2] = dict(segs[2], artifact_id=new.id, sha256=new.sha256)
    c = svc.compile("comp-a", "exp1", "A", "plan-1", segs, [],
                    CLOCK, now=NOW)
    ctx.check("new_revision",
              c["composition"]["revision"] == 2
              and c["composition"]["parent_hash"] ==
              a["composition"]["content_hash"])
    a_b = {x["binding"]: x["sha256"] for x in
           a["composition"]["bindings"]}
    c_b = {x["binding"]: x["sha256"] for x in
           c["composition"]["bindings"]}
    diffs = [k for k in a_b if a_b[k] != c_b.get(k)]
    ctx.check("only_dependency_changed", diffs == ["src-s2"],
              f"diffs: {diffs}")
    return _result(ctx, "passed",
                   "unchanged inputs reused r1; changed selection → r2 "
                   "with parent hash, only src-s2 binding differs")


def implementations():
    return {"F22-M01": f22_m01, "F22-M02": f22_m02,
            "F22-M03": f22_m03, "F22-M04": f22_m04}
