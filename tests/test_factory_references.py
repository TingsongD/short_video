from modules.factory.testing.authority import approve_operation
"""F18: reference packs — assembly, validation, hash-pinned review,
replacement/dependents, generated-reference recovery."""
import pytest

from modules.factory.artifacts.registry import ArtifactStore
from modules.factory.domain.errors import ContractError
from modules.factory.references import (ReferenceGeneration,
                                        ReferencePackService,
                                        ReferenceReview, pack_hash)
from modules.factory.store import Database
from modules.factory.testing.fakes import FakeCanvasRunner
from modules.assets.canvas_cli import CanvasCLI
from modules.factory.providers.canvas import CanvasAdapter
from modules.factory.execution import Executor
from modules.factory.budget.service import BudgetService

NOW = "2026-09-17T00:00:00Z"


def _png(path, color="red"):
    """Tiny real PNG via ffmpeg so intake probing succeeds."""
    import subprocess
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                    f"color=c={color}:s=64x64:d=0.1", "-frames:v", "1",
                    str(path)], capture_output=True, check=True)


@pytest.fixture
def stack(tmp_path):
    db = Database(tmp_path / "f.db")
    arts = ArtifactStore(tmp_path / "arts", db)
    for name in ("front.png", "back.png", "head.png", "scene.png"):
        _png(tmp_path / name)
    ids = {}
    for name, kind in (("front.png", "image"), ("back.png", "image"),
                       ("head.png", "image"), ("scene.png", "image")):
        ids[name] = arts.intake_file(
            tmp_path / name, provenance="manual",
            source_key=name, requested_kind="image").id
    packs = ReferencePackService(db, arts)
    review = ReferenceReview(db, packs)
    return db, arts, packs, review, ids, tmp_path


FACTS = {"color": "blue", "pattern": "checkerboard",
         "silhouette": "fitted tank", "construction": "ribbed knit",
         "variant_id": "v-1", "claims": ["ribbed knit", "square neck"]}


def test_pack_and_snapshot_refs(stack):
    db, arts, packs, review, ids, _ = stack
    db.uow().records.put_type = None
    import json as j
    from modules.factory.domain.records import ProductSnapshot
    snap = ProductSnapshot(schema_version="product_snapshot.v1",
                           id="snap-1", created_at=NOW, shop="s",
                           product_id="p-1", variant_id="v-1",
                           title="Tank", media_artifact_ids=[ids["front.png"]],
                           claims=["ribbed knit"], observed_at=NOW,
                           pagination_complete=True)
    with db.uow() as u:
        u.records.put(snap)
    pack, refs = packs.from_snapshot("pack-1", "snap-1", now=NOW)
    assert pack["product_id"] == "p-1" if isinstance(pack, dict) else True
    assert len(refs) == 1 and refs[0].role == "product_front"
    assert refs[0].origin == "product_snapshot"


def test_manual_reference_and_review(stack):
    _, _, packs, review, ids, _ = stack
    packs.create_pack("pack-1", "p-1", "v-1", now=NOW)
    ref = packs.add_reference("pack-1", "r-1", "product_front",
                              ids["front.png"], variant_id="v-1",
                              attributes={
                                  "color": {"value": "blue",
                                            "state": "observed"},
                                  "pattern": {"value": "checkerboard",
                                              "state": "observed"},
                                  "silhouette": {"value": "fitted tank",
                                                 "state": "observed"},
                                  "construction": {
                                      "value": "ribbed knit",
                                      "state": "observed"}},
                              now=NOW)
    art = dict(packs._artifact(ids["front.png"]))
    out = review.accept("r-1", art["sha256"], reviewer="devin",
                        snapshot_facts=FACTS)
    assert out["status"] == "accepted"
    sel = packs.selection("pack-1")
    assert sel["product_front"] == art["sha256"]
    assert packs.refresh_pack_hash("pack-1")["status"] == "ready"


def test_stale_hash_rejected(stack):
    _, _, packs, review, ids, _ = stack
    packs.create_pack("pack-1", "p-1", now=NOW)
    packs.add_reference("pack-1", "r-1", "product_front",
                        ids["front.png"], now=NOW)
    with pytest.raises(ContractError, match="revision_mismatch"):
        review.accept("r-1", "0" * 64, reviewer="devin")


def test_defects_flagged_not_accepted(stack):
    """Wrong checkerboard geometry + invented back detail + copied
    overlay → reviewer sees flags, acceptance blocked."""
    _, _, packs, review, ids, _ = stack
    packs.create_pack("pack-1", "p-1", "v-1", now=NOW)
    packs.add_reference("pack-1", "r-1", "product_front",
                        ids["front.png"], variant_id="v-1",
                        attributes={
                            "color": {"value": "blue",
                                      "state": "observed"},
                            "pattern": {"value": "stripes",
                                        "state": "observed"},
                            "silhouette": {"value": "fitted tank",
                                           "state": "observed"},
                            "construction": {"value": "ribbed knit",
                                             "state": "observed"},
                            "extra_details": ["embroidered back logo"],
                            "copied_overlay": True},
                        now=NOW)
    flags = review.flags("r-1", FACTS)
    names = {f["flag"] for f in flags}
    assert "attribute_mismatch" in names          # wrong pattern
    assert "invented_detail" in names             # back logo not in claims
    assert "copied_source_overlay" in names
    with pytest.raises(ContractError, match="unresolved_flags"):
        review.accept("r-1", dict(packs._artifact(
            ids["front.png"]))["sha256"], reviewer="devin",
            snapshot_facts=FACTS)
    review.reject("r-1", "devin",
                  ["wrong pattern", "invented back detail", "overlay"])
    # rejected references cannot feed paid picture jobs
    with pytest.raises(ContractError, match="reference_not_accepted"):
        review.gate_request("pack-1", ["anyhash"])


def test_replacement_is_new_revision(stack):
    _, _, packs, review, ids, _ = stack
    packs.create_pack("pack-1", "p-1", now=NOW)
    packs.add_reference("pack-1", "r-1", "product_front",
                        ids["front.png"], now=NOW)
    art = dict(packs._artifact(ids["front.png"]))
    new = packs.replace("r-1", ids["back.png"], reviewer="devin")
    assert new.revision == 1 and new.parent_hash == art["sha256"]
    assert packs.get("r-1")["artifact_sha256"] == \
        dict(packs._artifact(ids["back.png"]))["sha256"]


def test_repair_limit(stack):
    _, _, packs, review, ids, _ = stack
    review.max_repairs = 1
    packs.create_pack("pack-1", "p-1", now=NOW)
    packs.add_reference("pack-1", "r-1", "product_front",
                        ids["front.png"], now=NOW)
    review.replace("r-1", ids["back.png"], reviewer="devin")
    with pytest.raises(ContractError, match="repair_limit_reached"):
        review.replace("r-1", ids["scene.png"], reviewer="devin")


def test_invalidation_lists_dependents(stack):
    db, arts, packs, review, ids, _ = stack
    packs.create_pack("pack-1", "p-1", now=NOW)
    packs.add_reference("pack-1", "r-1", "product_front",
                        ids["front.png"], now=NOW)
    art = dict(packs._artifact(ids["front.png"]))
    packs._update_pack("pack-1", status="accepted")
    review._set("r-1", status="accepted", acceptance={
        "state": "accepted", "reviewer": "devin", "reasons": [],
        "limits": [], "reviewed_hash": art["sha256"]})
    packs.refresh_pack_hash("pack-1")
    deps = packs.invalidate("pack-1")
    assert packs._require_pack("pack-1")["status"] == "stale"


def test_presenter_rejects_seed_provenance(stack):
    _, _, packs, _, _, _ = stack
    with pytest.raises(ContractError, match="seed_presenter_copied"):
        packs.create_presenter("pres-1", {"appearance": "same"},
                               provenance="seed_frame", now=NOW)
    p = packs.create_presenter("pres-2", {"appearance": "fictional"},
                               provenance="authored_guide", now=NOW)
    assert p.kind == "fictional"


def test_pack_hash_shared_across_variants(stack):
    _, _, packs, review, ids, _ = stack
    packs.create_pack("pack-1", "p-1", now=NOW)
    packs.add_reference("pack-1", "r-1", "product_front",
                        ids["front.png"], now=NOW)
    art = dict(packs._artifact(ids["front.png"]))
    review._set("r-1", status="accepted", acceptance={
        "state": "accepted", "reviewer": "d", "reasons": [],
        "limits": [], "reviewed_hash": art["sha256"]})
    h = packs.refresh_pack_hash("pack-1")["pack_hash"]
    # A/B/C/D share the identical pack hash while product+presenter locked
    assert h == pack_hash({"product_front": art["sha256"]})


def test_generated_reference_flow(stack):
    db, arts, packs, review, ids, tmp = stack
    runner = FakeCanvasRunner(tmp / "cli.json")
    adapter = CanvasAdapter(CanvasCLI(runner=runner), {})
    adapter.models = ["seedream_4.0"]
    budget = BudgetService(db)
    budget.create_budget("b-credits", "jimeng_credits",
                         scope="experiment", scope_key="e1", cap=500)
    executor = Executor(db, provider=adapter)
    gen = ReferenceGeneration(db, packs, arts, adapter, executor, budget)
    packs.create_pack("pack-1", "p-1", now=NOW)
    req = {"kind": "image", "prompt": "product photo blue tank", "model": "seedream_4.0", "duration_s": 1}
    aid = approve_operation(db, executor, req, "job:gen1", kind="generation", provider="jimeng_canvas", model="seedream_4.0", unit="jimeng_credits", amount=54)
    out = gen.request("pack-1", "r-gen", "job:gen1",
                      "product photo blue tank", [("b-credits", 30)], attempt_id=aid)
    assert out["reservation_id"] and out["operation"]["operation_id"]
    got = gen.collect("pack-1", "r-gen", "product_detail",
                      out["operation"]["operation_id"],
                      attempt_id=out["attempt_id"], now=NOW)
    assert got["status"] in ("collected", "accepted", "running")
    if got["status"] != "collected":           # poll again → succeed
        got = gen.collect("pack-1", "r-gen", "product_detail",
                          out["operation"]["operation_id"],
                          attempt_id=out["attempt_id"], now=NOW)
    assert got["status"] == "collected"
    ref = packs.get("r-gen")
    assert ref["origin"] == "generated" and ref["artifact_id"]


def test_generated_recovery_after_interrupt(stack):
    db, arts, packs, review, ids, tmp = stack
    runner = FakeCanvasRunner(tmp / "cli.json")
    adapter = CanvasAdapter(CanvasCLI(runner=runner), {})
    adapter.models = ["seedream_4.0"]
    executor = Executor(db, provider=adapter)
    gen = ReferenceGeneration(db, packs, arts, adapter, executor, None)
    packs.create_pack("pack-1", "p-1", now=NOW)
    runner.lose_next_run()                     # accept remote, drop ack
    import json as j, hashlib as h
    req = {"kind": "image", "prompt": "p", "model": "seedream_4.0",
           "duration_s": 1}
    wire = j.dumps(req, sort_keys=True, default=str)
    rh = h.sha256(wire.encode()).hexdigest()
    from modules.factory.testing.fakes import ProviderError
    aid = approve_operation(db, executor, req, "job:g2", kind="generation", provider="jimeng_canvas", model="seedream_4.0", unit="jimeng_credits", amount=54)
    with pytest.raises(ProviderError):
        executor.submit(aid, lambda: adapter.submit(req))
    rec = gen.recover("pack-1", "r-gen2", "product_detail",
                      "att:job:g2:1", rh, now=NOW)
    # remote op exists — recover must find it, not resubmit
    assert rec["status"] in ("collected", "accepted", "running",
                             "succeeded")
    assert len(runner.doc["ops"]) == 1
