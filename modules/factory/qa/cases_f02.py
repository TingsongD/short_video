"""F02 manual scenarios: contract validation, revision immutability,
legacy conversion refusal."""
import os

from .cases_f01 import CaseContext, _result
from ..domain import (Artifact, AssetUse, Beat, ContractError,
                      FrameInterval, RationalRate, ReferenceBlueprint,
                      accept, revise)
from ..domain.to_legacy import convert_or_refuse

SCHEMAS = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                       "schemas")
NOW = "2026-09-16T12:00:00Z"


def _beats(total, n):
    step = total // n
    out, cur = [], 0
    for i in range(n):
        end = cur + step if i < n - 1 else total
        out.append(Beat(id=f"b{i+1}", role="body",
                        source=FrameInterval(cur, end),
                        target=FrameInterval(cur, end)))
        cur = end
    return out


def _bp(bid, beats, target):
    return ReferenceBlueprint(
        schema_version="reference_blueprint.v1", id=bid, created_at=NOW,
        seed_id="seed:demo", revision=1, clock=RationalRate(30, 1),
        target_frames=target, beats=beats)


def f02_m01(ctx: CaseContext):
    six = _bp("bp:six", _beats(900, 6), 900)
    twenty = _bp("bp:twenty", _beats(5091, 20), 5091)
    ctx.check("six_beat_900_frames", six.validate() == []
              and sum(b.target.length for b in six.beats) == 900)
    ctx.check("twenty_take_5091_frames", twenty.validate() == []
              and sum(b.target.length for b in twenty.beats) == 5091)
    return _result(ctx, "awaiting_manual_review",
                   "30 s/6-beat and 169.7 s/20-take blueprints validate; "
                   "frame totals 900 and 5091 at 30 fps",
                   limitations=["human inspects beat table readability"])


def f02_m02(ctx: CaseContext):
    beats = _beats(900, 6)
    beats[2] = Beat(id="b3", role="body", source=FrameInterval(120, 300),
                    target=FrameInterval(149, 300))   # overlaps b2's target
    errs = _bp("bp:bad", beats, 900).validate()
    ctx.check("overlap_typed", any(e.code == "frame_overlap" for e in errs),
              ",".join(e.code for e in errs))
    a = Artifact(schema_version="artifact.v1", id="a:x", created_at=NOW,
                 sha256="a" * 64, kind="video", provenance="mystery")
    ctx.check("provenance_typed",
              any(e.field == "provenance" for e in a.validate()))
    try:
        RationalRate(30, 0)
        ctx.check("zero_denominator_typed", False)
    except ContractError as e:
        ctx.check("zero_denominator_typed",
                  e.code == "invalid_frame_rate")
    return _result(ctx, "passed",
                   "overlap, provenance and zero-denominator errors each "
                   "carry field-specific codes; no silent correction")


def f02_m03(ctx: CaseContext):
    bp = _bp("bp:rev", _beats(900, 6), 900)
    accept(bp)
    frozen = bp.content_hash
    try:
        accept(bp)
        ctx.check("in_place_reaccept_refused", False)
    except ContractError:
        ctx.check("in_place_reaccept_refused", True)
    child = revise(bp, "hook punch-up", reason_ref="review:r9")
    child.beats[0] = Beat(id="b1", role="hook",
                          source=FrameInterval(0, 150),
                          target=FrameInterval(0, 150))
    accept(child)
    ctx.check("child_revision", child.revision == 2
              and child.parent_hash == frozen)
    ctx.check("parent_superseded", bp.status == "superseded")
    ctx.check("child_hash_differs", child.content_hash != frozen)
    return _result(ctx, "awaiting_manual_review",
                   "accepted revision frozen; edit produced revision 2 "
                   "naming parent hash and reason",
                   limitations=["downstream price/review invalidation "
                                "verified once F03 store exists"])


def f02_m04(ctx: CaseContext):
    def uses(prov, n=5):
        us, arts = [], {}
        for i in range(n):
            a = Artifact(schema_version="artifact.v1", id=f"a:{prov}{i}",
                         created_at=NOW, sha256=f"{i:064d}", kind="video",
                         provenance=prov, local_path=f"c{i}.mp4")
            arts[a.id] = a
            us.append(AssetUse(schema_version="asset_use.v1", id=f"u{i}",
                               created_at=NOW, artifact_id=a.id,
                               source=FrameInterval(i * 60, (i + 1) * 60)))
        return us, arts

    us, arts = uses("jimeng_canvas")
    payload, _ = convert_or_refuse(
        "vid-jimeng", us, arts,
        os.path.join(SCHEMAS, "asset_manifest.schema.json"))
    ctx.check("jimeng_validates", len(payload["assets"]) == 5)

    us2, arts2 = uses("google_vertex", n=20)  # wrong enum + 20 takes
    try:
        convert_or_refuse("vid-vertex", us2, arts2,
                          os.path.join(SCHEMAS, "asset_manifest.schema.json"))
        ctx.check("incompatible_refused", False)
    except ContractError as e:
        ctx.check("incompatible_refused",
                  e.code == "legacy_conversion_refused"
                  and "mislabel" in str(e) and "shot_count" in str(e))
    return _result(ctx, "passed",
                   "compatible Jimeng manifest validates against the frozen "
                   "schema; Vertex/20-take refuses with explicit reasons")


def implementations():
    return {"F02-M01": f02_m01, "F02-M02": f02_m02,
            "F02-M03": f02_m03, "F02-M04": f02_m04}
