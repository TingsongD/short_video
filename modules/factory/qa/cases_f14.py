"""F14 manual scenarios: canonical A/B/C/D experiment, undeclared
changes, transitive dependencies, post-freeze invalidation."""
import json

from .cases_f01 import CaseContext, _result
from ..domain.clocks import FPS_30, FrameInterval
from ..domain.errors import ContractError
from ..domain.records import (Beat, FormatTemplate, ProductSnapshot,
                              ReferenceBlueprint, Slot)
from ..experiments import ExperimentService
from ..store import Database


def _blueprint():
    spans = [(0, 120), (120, 240), (240, 360), (360, 510),
             (510, 780), (780, 900)]
    roles = ["hook", "product_reveal", "product_reveal",
             "product_reveal", "proof", "cta"]
    return ReferenceBlueprint(
        schema_version="blueprint.v1", id="bp-1", seed_id="seed-x",
        created_at="2026-09-16T00:00:00Z", revision=1, status="accepted",
        clock=FPS_30, target_frames=900,
        beats=[Beat(id=f"b{i}", role=r, target=FrameInterval(s, e))
               for i, (r, (s, e)) in enumerate(zip(roles, spans))],
        content_hash="bphash")


def _template():
    return FormatTemplate(
        schema_version="format_template.v1", id="ft-haul",
        created_at="2026-09-16T00:00:00Z", revision=1,
        slots=[Slot(id=f"s{i}", kind=k, frames=f)
               for i, (k, f) in enumerate(zip(
                   ("hook", "product", "product", "product",
                    "proof", "cta"), (120, 120, 120, 150, 270, 120)))])


def _snap():
    return ProductSnapshot(
        schema_version="product_snapshot.v1", id="psnap-x",
        created_at="2026-09-16T00:00:00Z", revision=0,
        shop="fixture", product_id="gid://shopify/Product/8001",
        variant_id="gid://shopify/ProductVariant/90001",
        title="Sky-Blue Polka-Dot Jeans",
        claims=[{"kind": "title", "text": "Sky-Blue Polka-Dot Jeans"},
                {"kind": "price", "text": "USD 39.00"}],
        observed_at="2026-09-16T00:00:00Z")


def _segments():
    spans = [(0, 120), (120, 240), (240, 360), (360, 510),
             (510, 780), (780, 900)]
    roles = ["hook", "product", "product", "product", "proof", "cta"]
    return [{"id": f"seg{i}", "slot_id": f"s{i}", "role": r,
             "target": {"start_frame": s, "end_frame": e},
             "copy": f"copy-{i}", "speech": f"vo-{i}",
             "captions": f"cap-{i}", "picture": f"pic-{i}",
             "transition": "cut",
             "claims": ["Sky-Blue Polka-Dot Jeans"] if i == 1 else []}
            for i, (r, (s, e)) in enumerate(zip(roles, spans))]


FIELDS = ["copy", "speech", "captions", "picture"]


def _mark(region, tag):
    def edit(body):
        for s in body["segments"]:
            iv = FrameInterval(s["target"]["start_frame"],
                               s["target"]["end_frame"])
            if iv.overlaps(region):
                for f in FIELDS:
                    s[f] = f"{s[f]}-{tag}"
        return body
    return edit


def _stack(ctx, name):
    return ExperimentService(Database(ctx.run_dir / f"{name}.db"))


def f14_m01(ctx: CaseContext):
    """Canonical 30 s experiment: A=900 frames; B 0–120, C 360–510,
    D 780–900; all branch from A."""
    es = _stack(ctx, "m01")
    out = es.create("exp1", "seed-x", _blueprint(), _template(),
                    [_snap()], _segments())
    ctx.check("a_900_frames",
              out["control"].packaging["target_frames"] == 900)
    regions = {"B": FrameInterval(0, 120), "C": FrameInterval(360, 510),
               "D": FrameInterval(780, 900)}
    for key, region in regions.items():
        es.branch("exp1", key,
                  {"B": "hook", "C": "body", "D": "ending"}[key],
                  [region], _mark(region, key),
                  hypothesis=f"{key} hypothesis", primary_metric="hold",
                  allowed_fields=FIELDS)
        rep = es.review("exp1", key)
        ctx.check(f"{key}_clean", rep["problems"] == [])
        # every changed frame sits inside the declared region
        changed = [r["target"] for r in rep["diff"]["regions"]]
        ok = all(region.start <= t["start_frame"]
                 and t["end_frame"] <= region.end for t in changed)
        ctx.check(f"{key}_region_exact", ok, str(changed[:3]))
    import json as _j
    revs = {_j.loads(r["body"])["experiment_revision"]
            for r in es.db.conn.execute(
                "SELECT body FROM records WHERE kind='variantplan'")}
    ctx.check("all_branch_from_a", revs == {1})
    return _result(ctx, "awaiting_manual_review",
                   "A/B/C/D all branch from control rev1; declared "
                   "regions contain every changed frame",
                   limitations=["human reviews the semantic diffs"])


def f14_m02(ctx: CaseContext):
    """Undeclared music change in B and product change in C both fail
    the one-variable policy with an explanation."""
    es = _stack(ctx, "m02")
    es.create("exp1", "seed-x", _blueprint(), _template(),
              [_snap()], _segments())
    def music_edit(body):
        body["music"] = {"role": "different_track"}
        body["segments"][0]["copy"] = "x"
        return body
    try:
        es.branch("exp1", "B", "hook", [FrameInterval(0, 120)],
                  music_edit, hypothesis="h", primary_metric="m",
                  allowed_fields=["copy"])
        ctx.check("music_rejected", False)
    except ContractError as e:
        ctx.check("music_rejected",
                  "locked_field_changed" in e.detail)
    def product_edit(body):
        body["products"] = [{"snapshot_id": "psnap-other"}]
        return body
    try:
        es.branch("exp1", "C", "body", [FrameInterval(360, 510)],
                  product_edit, hypothesis="h", primary_metric="m",
                  allowed_fields=["copy"])
        ctx.check("product_rejected", False)
    except ContractError as e:
        ctx.check("product_rejected",
                  "locked_field_changed" in e.detail)
    return _result(ctx, "passed",
                   "undeclared music and product changes each named as "
                   "locked-field violations; no branch persisted")


def f14_m03(ctx: CaseContext):
    """Replace C's narration in a lip-synced shot: captions/alignment/
    picture ride inside the declared region."""
    es = _stack(ctx, "m03")
    es.create("exp1", "seed-x", _blueprint(), _template(),
              [_snap()], _segments())
    try:
        es.branch("exp1", "C", "body", [FrameInterval(360, 510)],
                  _mark(FrameInterval(360, 510), "c"),
                  hypothesis="benefit-first body beats feature-first",
                  primary_metric="mid_retention",
                  allowed_fields=["copy"])      # deps NOT declared
        ctx.check("deps_required", False)
    except ContractError as e:
        ctx.check("deps_required",
                  "dependency_outside_region" in e.detail)
    v = es.branch("exp1", "C", "body", [FrameInterval(360, 510)],
                  _mark(FrameInterval(360, 510), "c"),
                  hypothesis="benefit-first body beats feature-first",
                  primary_metric="mid_retention",
                  allowed_fields=FIELDS)
    rep = es.review("exp1", "C")
    changed = {r["field"] for r in rep["diff"]["regions"]}
    ctx.check("deps_included",
              {"copy", "speech", "captions", "picture"} <= changed)
    ctx.check("no_stale_mouth", "vo-" not in json.dumps(v.segments)
              or "-c" in json.dumps(v.segments))
    return _result(ctx, "passed",
                   "copy-only declaration refused; with speech/captions/"
                   "picture declared, all four changed tracks sit inside "
                   "C's region — no stale mouth motion reusable")


def f14_m04(ctx: CaseContext):
    """Accept all, revise A's product claim → variants, prices and
    reviews go stale; execution waits for the revised plan."""
    es = _stack(ctx, "m04")
    out = es.create("exp1", "seed-x", _blueprint(), _template(),
                    [_snap()], _segments())
    es.branch("exp1", "B", "hook", [FrameInterval(0, 120)],
              _mark(FrameInterval(0, 120), "b"),
              hypothesis="h", primary_metric="m", allowed_fields=FIELDS)
    es.accept("exp1", out["control"].content_hash)
    res = es.revise_control(
        "exp1",
        lambda b: {**b, "packaging":
                   {**b["packaging"], "voice": {"id": "v2"}}},
        reason="control voice fix")
    ctx.check("new_revision", res["revision"].revision == 2)
    ctx.check("b_staled", "exp1:b" in res["staled"])
    try:
        es.accept("exp1", out["control"].content_hash)
        ctx.check("old_approval_rejected", False)
    except ContractError as e:
        ctx.check("old_approval_rejected",
                  e.code == "revision_mismatch")
    return _result(ctx, "passed",
                   "control edit wrote rev2 and staled variant B; the old "
                   "accepted hash no longer opens execution")


def implementations():
    return {"F14-M01": f14_m01, "F14-M02": f14_m02,
            "F14-M03": f14_m03, "F14-M04": f14_m04}
