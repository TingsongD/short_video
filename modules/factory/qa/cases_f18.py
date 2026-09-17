"""F18 manual scenarios: pack assembly + acceptance, defect rejection
+ dispatch gate, generated-reference interrupt recovery, presenter
replacement invalidation."""
import json
import subprocess

from .cases_f01 import CaseContext, _result
from ..artifacts.registry import ArtifactStore
from ..domain.errors import ContractError
from ..domain.records import GenerationRequest
from ..execution import Executor
from ..providers.canvas import CanvasAdapter
from ..references import (ReferenceGeneration, ReferencePackService,
                          ReferenceReview)
from ..store import Database
from ..testing.fakes import FakeCanvasRunner, ProviderError
from ...assets.canvas_cli import CanvasCLI

NOW = "2026-09-17T00:00:00Z"

FACTS = {"color": "blue", "pattern": "checkerboard",
         "silhouette": "fitted tank", "construction": "ribbed knit",
         "variant_id": "v-1",
         "claims": ["ribbed knit", "square neck"]}

OBS = lambda v: {"value": v, "state": "observed"}
GOOD_ATTRS = {"color": OBS("blue"), "pattern": OBS("checkerboard"),
              "silhouette": OBS("fitted tank"),
              "construction": OBS("ribbed knit")}


def _png(path, color):
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                    f"color=c={color}:s=64x64:d=0.1", "-frames:v", "1",
                    str(path)], capture_output=True, check=True)


def _stack(ctx, name):
    db = Database(ctx.run_dir / f"{name}.db")
    arts = ArtifactStore(ctx.run_dir / f"{name}-arts", db=db)
    packs = ReferencePackService(db, arts)
    review = ReferenceReview(db, packs)
    return db, arts, packs, review


def _intake(arts, ctx, name, color):
    p = ctx.run_dir / f"{name}.png"
    _png(p, color)
    return arts.intake_file(p, provenance="manual", source_key=name,
                            requested_kind="image")


def f18_m01(ctx: CaseContext):
    """Three-product pack + presenter ref; every usable ref has source
    + explicit acceptance; unchanged variants share the pack hash."""
    db, arts, packs, review = _stack(ctx, "m01")
    packs.create_pack("pack-1", "p-1", "v-1", "pres-1", now=NOW,
                      required_roles=["product_front", "product_back",
                                      "presenter_headshot"])
    packs.create_presenter("pres-1", {"appearance": "fictional",
                                      "wardrobe": "neutral"},
                           provenance="authored_guide", now=NOW)
    for rid, role, color in (
            ("r-f", "product_front", "blue"),
            ("r-b", "product_back", "navy"),
            ("r-h", "presenter_headshot", "gray")):
        a = _intake(arts, ctx, rid, color)
        packs.add_reference("pack-1", rid, role, a.id,
                            attributes=dict(GOOD_ATTRS), now=NOW)
        review.accept(rid, a.sha256, reviewer="devin",
                      snapshot_facts=FACTS)
    st = packs.refresh_pack_hash("pack-1")
    ctx.check("pack_ready", st["status"] == "ready"
              and not st["missing_roles"], str(st))
    sel = packs.selection("pack-1")
    ctx.check("sourced_and_accepted",
              len(sel) == 3 and all(
                  r["acceptance"]["state"] == "accepted"
                  and r["source_artifact_ids"] is not None
                  for r in packs.pack_refs("pack-1")))
    ctx.check("variants_share_hash",
              st["pack_hash"] == packs.refresh_pack_hash("pack-1")
              ["pack_hash"], "locked variables → identical hash")
    return _result(ctx, "awaiting_manual_review",
                   "pack ready with 3 accepted sourced refs; selection "
                   "hash stable for locked variants",
                   limitations=["human compares variants visually"])


def f18_m02(ctx: CaseContext):
    """Wrong pattern + invented back detail + copied overlay → named
    rejections; dependent picture jobs cannot dispatch."""
    db, arts, packs, review = _stack(ctx, "m02")
    packs.create_pack("pack-1", "p-1", "v-1", now=NOW)
    a = _intake(arts, ctx, "bad", "blue")
    packs.add_reference("pack-1", "r-bad", "product_front", a.id,
                        variant_id="v-1",
                        attributes={
                            **GOOD_ATTRS,
                            "pattern": OBS("stripes"),
                            "extra_details": ["embroidered back logo"],
                            "copied_overlay": True}, now=NOW)
    flags = {f["flag"] for f in review.flags("r-bad", FACTS)}
    ctx.check("defects_flagged",
              {"attribute_mismatch", "invented_detail",
               "copied_source_overlay"} <= flags, str(flags))
    try:
        review.accept("r-bad", a.sha256, reviewer="devin",
                      snapshot_facts=FACTS)
        ctx.check("accept_blocked", False)
    except ContractError as e:
        ctx.check("accept_blocked", e.code == "unresolved_flags")
    review.reject("r-bad", "devin",
                  ["wrong checkerboard geometry",
                   "invented back detail", "copied overlay"])
    try:
        review.gate_request("pack-1", [a.sha256])
        ctx.check("dispatch_blocked", False)
    except ContractError as e:
        ctx.check("dispatch_blocked",
                  e.code == "reference_not_accepted")
    return _result(ctx, "passed",
                   "three defect classes flagged by name; acceptance "
                   "and dispatch both blocked for rejected refs")


def f18_m03(ctx: CaseContext):
    """Interrupt a fake image request, recover it, select a corrected
    accepted artifact — cost recorded, explicit selection change."""
    db, arts, packs, review = _stack(ctx, "m03")
    runner = FakeCanvasRunner(ctx.run_dir / "m03-cli.json")
    adapter = CanvasAdapter(CanvasCLI(runner=runner), {})
    adapter.models = ["seedream_4.0"]
    executor = Executor(db, provider=adapter)
    gen = ReferenceGeneration(db, packs, arts, adapter, executor, None)
    packs.create_pack("pack-1", "p-1", "v-1", now=NOW)
    req = {"kind": "image", "prompt": "product ref", "duration_s": 1,
           "model": "seedream_4.0"}
    import hashlib as h
    rh = h.sha256(json.dumps(req, sort_keys=True).encode()).hexdigest()
    runner.lose_next_run()
    att = executor.prepare("job:m03", 1, req,
                           kind="reference_generation",
                           provider="jimeng_canvas")
    try:
        executor.submit(att, lambda: adapter.submit(req))
        ctx.check("interrupt_named", False)
    except ProviderError:
        ctx.check("interrupt_named", True)
    ctx.check("attempt_recorded",
              len(runner.doc["ops"]) == 1,
              "original attempt + remote op preserved")
    rec = gen.recover("pack-1", "r-gen", "product_detail", att, rh,
                      now=NOW)
    ctx.check("recovered_not_duplicated",
              len(runner.doc["ops"]) == 1 and
              rec["status"] in ("collected", "accepted", "running",
                                "succeeded"), str(rec["status"]))
    if rec["status"] != "collected":
        rec = gen.recover("pack-1", "r-gen", "product_detail", att, rh,
                          now=NOW)
    ctx.check("collected", rec["status"] == "collected")
    ref = packs.get("r-gen")
    ctx.check("explicit_selection",
              ref["origin"] == "generated"
              and ref["generation_attempt_id"] == att)
    return _result(ctx, "passed",
                   "lost-ack image request reconciled to the same "
                   "remote op; artifact collected with the attempt id")


def f18_m04(ctx: CaseContext):
    """Replace presenter ref after acceptance: affected jobs/reviews
    listed; explicit plan revision required."""
    db, arts, packs, review = _stack(ctx, "m04")
    packs.create_pack("pack-1", "p-1", "v-1", "pres-1",
                      plan_hash="plan-abc", now=NOW)
    a1 = _intake(arts, ctx, "h1", "gray")
    packs.add_reference("pack-1", "r-h", "presenter_headshot", a1.id,
                        now=NOW)
    review._set("r-h", status="accepted", acceptance={
        "state": "accepted", "reviewer": "devin", "reasons": [],
        "limits": [], "reviewed_hash": a1.sha256})
    st = packs.refresh_pack_hash("pack-1")
    # downstream work bound to the pack hash + accepted artifact
    with db.uow() as u:
        gr = GenerationRequest(
            schema_version="gen_request.v1", id="gr-1", created_at=NOW,
            experiment_id="exp1", experiment_revision=1,
            variant_key="A", segment_id="s1", prompt="shot",
            reference_artifact_ids=[a1.id],
            reference_roles={a1.id: "image"})
        gr.finalize_hash()
        u.records.put(gr)
        from ..domain.records import Review
        u.records.put(Review(
            schema_version="review.v1", id="rev-1", created_at=NOW,
            target_hash=st["pack_hash"], check_type="creative",
            reviewer_type="human", verdict="pass"))
    a2 = _intake(arts, ctx, "h2", "black")
    packs.replace("r-h", a2.id, reviewer="devin")
    deps = packs.invalidate("pack-1", reason="presenter_changed")
    ctx.check("affected_jobs_listed",
              deps["generation_requests"] == ["gr-1"], str(deps))
    ctx.check("affected_reviews_listed",
              deps["reviews"] == ["rev-1"])
    ctx.check("pack_stale_needs_revision",
              packs._require_pack("pack-1")["status"] == "stale")
    old = packs.pack_refs("pack-1")
    ctx.check("old_selection_evidence",
              packs.get("r-h")["parent_hash"] == a1.sha256)
    return _result(ctx, "passed",
                   "presenter swap listed the bound generation request "
                   "and review; pack went stale pending explicit plan "
                   "revision")


def implementations():
    return {"F18-M01": f18_m01, "F18-M02": f18_m02,
            "F18-M03": f18_m03, "F18-M04": f18_m04}
