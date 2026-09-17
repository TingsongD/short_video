from modules.factory.testing.authority import approve_production
"""F21: unique-work production plan — canonical 9-job graph, dedupe,
duration splits, branch isolation, pricing-once, resume, manual
coverage."""
import json

import pytest

from modules.factory.artifacts.registry import ArtifactStore
from modules.factory.domain.errors import ContractError
from modules.factory.execution import Executor
from modules.factory.planning.asset_graph import (
    build_graph, canonical_request_key, expand_take)
from modules.factory.production import ProductionService
from modules.factory.scheduler.scheduler import Scheduler
from modules.factory.store import Database
from modules.factory.testing.clock import FakeClock
from modules.factory.testing.fakes import (FakeGenerationAdapter,
                                           FakeProvider,
                                           JIMENG_MODELS)
from modules.factory.testing.fixtures import _color_mp4
from modules.factory.testing.ids import IdFactory

NOW = "2026-09-17T00:00:00Z"


def _takes():
    """Canonical: 4 variants × 6 slots. B changes s1, C changes s4,
    D changes s6 → 6 shared + 3 unique = 9 picture works."""
    changed = {"b": "s1", "c": "s4", "d": "s6"}
    out = []
    for v in "abcd":
        for i in range(1, 7):
            slot = f"s{i}"
            prompt = (f"{v}-alt-{i}" if changed.get(v) == slot
                      else f"shared-{i}")
            out.append({"variant": v, "slot": slot, "duration_s": 4.0,
                        "request": {"prompt": prompt,
                                    "settings": {"aspect": "9:16"},
                                    "refs": ["ref-h1"],
                                    "audio": "seg-h1"}})
    return out


@pytest.fixture
def stack(tmp_path):
    db = Database(tmp_path / "f.db")
    sched = Scheduler(db, worker_id="w1", lease_s=300)
    provider = FakeProvider("jimeng_canvas", tmp_path / "remote",
                            IdFactory(tmp_path / "ids.json"),
                            FakeClock())
    clip = tmp_path / "clip.mp4"
    _color_mp4(clip, 4.0)
    payload = clip.read_bytes()
    provider.payload_fn = lambda oid: payload
    adapter = FakeGenerationAdapter(
        "jimeng_canvas", provider, JIMENG_MODELS, "jimeng_credits",
        "native_quote", {"seedance_2.0_fast_vip": {4: 30, 8: 54}})
    arts = ArtifactStore(tmp_path / "arts", db)
    svc = ProductionService(db, scheduler=sched,
                            executor=Executor(db, provider=provider),
                            adapter=adapter, artifacts=arts, selector=lambda n:"accept")
    return db, sched, provider, adapter, arts, svc


def test_expand_within_limit():
    fit = expand_take(4.0, [4, 8])
    assert fit["status"] == "ok"
    assert fit["allocations"][0]["duration_s"] == 4


def test_expand_over_max_splits_declared():
    fit = expand_take(12.0, [4, 8])
    assert fit["status"] == "ok"
    assert [a["duration_s"] for a in fit["allocations"]] == [8, 4]
    assert all(a["split"] for a in fit["allocations"])
    assert "declared split" in fit["split_reason"]


def test_expand_remainder_is_trimmed():
    fit = expand_take(11.0, [4,8])
    assert fit["status"] == "ok"
    assert fit["allocations"][-1]["over_s"] == 1


def test_expand_smallest_covering_duration():
    fit = expand_take(5.0, [4, 8])
    assert fit["allocations"][0]["duration_s"] == 8
    assert fit["allocations"][0]["over_s"] == 3.0


def test_canonical_nine_job_graph(stack):
    db, sched, prov, adapter, arts, svc = stack
    out = svc.plan("plan-1", "exp1", 1, _takes(), "jimeng_canvas",
                   "seedance_2.0_fast_vip", [4, 8], now=NOW)
    stats = out["plan"]["stats"]
    assert stats["takes"] == 24
    assert stats["unique_pictures"] == 9
    assert stats["shared_pictures"] == 6
    pics = [n for n in out["nodes"].values() if n["kind"] == "picture"]
    assert len(pics) == 9
    # 3 slots untouched by any variant → 4 consumers each; the 3 slots
    # one treatment changes still share control requests across the
    # other 3 variants
    all4 = [n for n in pics if len(n["consumers"]) == 4]
    shared = [n for n in pics if len(n["consumers"]) > 1]
    assert len(all4) == 3 and len(shared) == 6
    single = [n for n in pics if len(n["consumers"]) == 1]
    assert sorted(n["consumers"][0] for n in single) == ["b", "c", "d"]
    # charged once per unique work, not per consumer
    assert out["plan"]["total_price"] == {"jimeng_credits": 9 * 30}


def test_request_key_dedupe_and_cache_invalidation():
    base = {"prompt": "p", "settings": {}, "refs": ["r1"],
            "audio": "a1"}
    assert canonical_request_key(base) == canonical_request_key(
        dict(base))
    for field, val in [("prompt", "p2"), ("audio", "a2")]:
        changed = dict(base)
        changed[field] = val
        assert canonical_request_key(changed) != \
            canonical_request_key(base)
    changed = dict(base)
    changed["refs"] = ["r2"]
    assert canonical_request_key(changed) != canonical_request_key(base)


def _run_all(svc, limit=200):
    n = 0
    while svc.run_next() is not None and n < limit:
        n += 1
    return n


def test_run_shared_billed_once(stack):
    db, sched, prov, adapter, arts, svc = stack
    svc.plan("plan-1", "exp1", 1, _takes(), "jimeng_canvas",
             "seedance_2.0_fast_vip", [4, 8], now=NOW)
    approve_production(svc, "plan-1")
    svc.submit("plan-1")
    _run_all(svc)
    # 9 submits total — shared control work billed once
    assert len(prov.state.doc["operations"]) == 9
    charges = prov.state.doc.get("charges", [])
    assert len(charges) == 9
    st = svc.status("plan-1")["readiness"]
    assert len(st["done"]) >= 9 + 9     # pics + downloads
    # four complete selections (review nodes per variant)
    done = {k for k in st["done"]}
    assert all(f"rev:{v}" in done for v in "abcd")


def test_branch_isolation(stack):
    db, sched, prov, adapter, arts, svc = stack
    svc.plan("plan-1", "exp1", 1, _takes(), "jimeng_canvas",
             "seedance_2.0_fast_vip", [4, 8], now=NOW)
    # find C's unique replacement (its request differs from shared)
    nodes = {k: n for k, n in svc._nodes("plan-1").items()
             if n["kind"] == "picture" and n["consumers"] == ["c"]}
    assert len(nodes) == 1
    ckey = next(iter(nodes))
    svc.reject_work("plan-1", ckey, reason="shot_rejected")
    st = svc.status("plan-1")["readiness"]
    assert ckey in st["rejected"]
    # only C's chain blocks; a/b/d review nodes still dispatchable
    assert svc._node("plan-1", "rev:c")["status"] == "blocked"
    assert svc._node("plan-1", "cmp:c")["status"] == "blocked"
    assert svc._node("plan-1", "del:c")["status"] == "blocked"
    assert svc._node("plan-1", "rev:a")["status"] != "blocked"
    # shared control works untouched
    shared = [n for n in svc._nodes("plan-1").values()
              if n["kind"] == "picture" and len(n["consumers"]) > 1]
    assert all(n["status"] != "blocked" for n in shared)


def test_needs_manual_no_under_length_submit(stack):
    db, sched, prov, adapter, arts, svc = stack
    takes = _takes()
    takes[0]["duration_s"] = 0.0      # invalid target requires manual correction
    out = svc.plan("plan-1", "exp1", 1, takes, "jimeng_canvas",
                   "seedance_2.0_fast_vip", [4, 8], now=NOW)
    assert out["plan"]["stats"]["manual_needed"] >= 1
    manual = [n for n in out["nodes"].values()
              if n["status"] == "needs_manual"]
    approve_production(svc, "plan-1")
    svc.submit("plan-1")
    res = svc.run_next()
    while res and res["node"] != manual[0]["node_key"]:
        res = svc.run_next()
    # picture job failed named — never submitted under-length footage
    assert res["outcome"] == "failed"
    assert svc._node("plan-1", manual[0]["node_key"])["status"] == \
        "needs_manual"


def test_manual_replacement_coverage(stack):
    db, sched, prov, adapter, arts, svc = stack
    takes = [{"variant": "a", "slot": "s1", "duration_s": 11.0,
              "request": {"prompt": "long", "settings": {},
                          "refs": [], "audio": "a1"}}]
    svc.plan("plan-1", "exp1", 1, takes, "jimeng_canvas",
             "seedance_2.0_fast_vip", [], now=NOW)
    node = next(k for k, n in svc._nodes("plan-1").items()
                if n["status"] == "needs_manual")
    # too-short clip rejected
    short = tmp_clip(stack, 5.0, "short")
    with pytest.raises(ContractError, match="insufficient_coverage"):
        svc.replace_manual("plan-1", node, short.id)
    # adequate manual clip accepted and feeds the download node
    ok = tmp_clip(stack, 12.0, "ok")
    out = svc.replace_manual("plan-1", node, ok.id)
    assert out["status"] == "manual"
    dl = svc._node("plan-1", f"dl:{svc._node('plan-1', node)['request_hash']}")
    assert dl["status"] == "downloaded"
    assert dl["artifact_ids"] == [ok.id]


def tmp_clip(stack, seconds, key):
    import tempfile, os
    _, _, _, _, arts, _ = stack
    path = arts.root.parent / f"{key}.mp4"
    _color_mp4(path, seconds)
    return arts.intake_bytes(path.read_bytes(), provenance="manual",
                             source_key=key, requested_kind="video")


def test_resume_survives_restart(stack, tmp_path):
    db, sched, prov, adapter, arts, svc = stack
    svc.plan("plan-1", "exp1", 1, _takes(), "jimeng_canvas",
             "seedance_2.0_fast_vip", [4, 8], now=NOW)
    approve_production(svc, "plan-1")
    svc.submit("plan-1")
    # run exactly the picture+download phase, then "restart"
    for _ in range(9):
        svc.run_next()                 # 9 picture submits
    for _ in range(9):
        svc.run_next()                 # 9 downloads
    done_before = svc.status("plan-1")["readiness"]["done"]
    # rebuild the service over the same DB — saved assets feed on
    svc2 = ProductionService(db, scheduler=Scheduler(db, worker_id="w2",
                                                     lease_s=300),
                             executor=Executor(db, provider=prov),
                             adapter=adapter, artifacts=arts, selector=lambda n:"accept")
    st = svc2.resume("plan-1")["readiness"]
    assert st["done"] == done_before
    _run_all(svc2)
    assert len(prov.state.doc["operations"]) == 9   # nothing resubmitted


def test_five_slot_concurrency(stack):
    db, sched, prov, adapter, arts, svc = stack
    svc.plan("plan-1", "exp1", 1, _takes(), "jimeng_canvas",
             "seedance_2.0_fast_vip", [4, 8], now=NOW)
    approve_production(svc, "plan-1")
    svc.submit("plan-1")
    claimed = []
    for _ in range(7):
        j = sched.claim()
        if j:
            claimed.append(j["id"])
    # jimeng_submit capacity is 5 — six+ claims stop at the pool limit
    assert len(claimed) == 5


def test_download_rejects_generation_shorter_than_allocation(stack):
    db,sched,prov,adapter,arts,svc=stack
    takes=[{'variant':'a','slot':'main','duration_s':8,'request':{'prompt':'fixture'}}]
    svc.plan('plan-short','exp1',1,takes,'jimeng_canvas','seedance_2.0_fast_vip',[4,8],now=NOW)
    approve_production(svc,'plan-short');svc.submit('plan-short')
    outcomes=[]
    for _ in range(30):
        result=svc.run_next()
        if result: outcomes.append(result)
    assert any(r.get('error')=='insufficient_generated_coverage' for r in outcomes)
    assert not any(n['status']=='accepted' for n in svc._nodes('plan-short').values())
