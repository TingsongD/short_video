"""F21 manual scenarios: canonical nine-job graph, branch isolation,
restart resume, duration-limit split/manual coverage."""
import json

from .cases_f01 import CaseContext, _result
from ..artifacts.registry import ArtifactStore
from ..domain.errors import ContractError
from ..execution import Executor
from ..production import ProductionService
from ..scheduler.scheduler import Scheduler
from ..store import Database
from ..testing.clock import FakeClock
from ..testing.fakes import (FakeGenerationAdapter, FakeProvider,
                             JIMENG_MODELS)
from ..testing.fixtures import _color_mp4
from ..testing.ids import IdFactory

NOW = "2026-09-17T00:00:00Z"


def _stack(ctx, name):
    db = Database(ctx.run_dir / f"{name}.db")
    sched = Scheduler(db, worker_id="w1", lease_s=300)
    prov = FakeProvider("jimeng_canvas", ctx.run_dir / f"{name}-remote",
                        IdFactory(ctx.run_dir / f"{name}-ids.json"),
                        FakeClock())
    clip = ctx.run_dir / f"{name}.mp4"
    _color_mp4(clip, 4.0)
    payload = clip.read_bytes()
    prov.payload_fn = lambda oid: payload
    adapter = FakeGenerationAdapter(
        "jimeng_canvas", prov, JIMENG_MODELS, "jimeng_credits",
        "native_quote", {"seedance_2.0_fast_vip": {4: 30, 8: 54}})
    arts = ArtifactStore(ctx.run_dir / f"{name}-arts", db)
    svc = ProductionService(db, scheduler=sched,
                            executor=Executor(db, provider=prov),
                            adapter=adapter, artifacts=arts)
    return db, sched, prov, arts, svc


def _takes():
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


def _run_all(svc, limit=300):
    n = 0
    while svc.run_next() is not None and n < limit:
        n += 1
    return n


def f21_m01(ctx: CaseContext):
    """Canonical experiment, fake providers: nine unique picture
    requests, four complete selections, shared work billed once."""
    db, sched, prov, arts, svc = _stack(ctx, "m01")
    out = svc.plan("plan-1", "exp1", 1, _takes(), "jimeng_canvas",
                   "seedance_2.0_fast_vip", [4, 8], now=NOW)
    svc.submit("plan-1")
    _run_all(svc)
    stats = out["plan"]["stats"]
    ctx.check("nine_unique",
              stats["unique_pictures"] == 9
              and stats["takes"] == 24)
    ctx.check("billed_once",
              len(prov.state.doc["operations"]) == 9
              and len(prov.state.doc.get("charges", [])) == 9
              and out["plan"]["total_price"] ==
              {"jimeng_credits": 270})
    st = svc.status("plan-1")["readiness"]
    ctx.check("four_selections",
              all(f"rev:{v}" in st["done"] for v in "abcd"))
    ctx.check("explainable",
              bool(out["plan"]["plan_hash"]) and
              stats["shared_pictures"] == 6)
    return _result(ctx, "passed",
                   "9 unique pictures / 6 shared, 9 charges, four "
                   "variant selections complete")


def f21_m02(ctx: CaseContext):
    """Reject C's changed shot after A/B valid: only C's dependent work
    blocks; shared assets and other variants intact."""
    db, sched, prov, arts, svc = _stack(ctx, "m02")
    svc.plan("plan-1", "exp1", 1, _takes(), "jimeng_canvas",
             "seedance_2.0_fast_vip", [4, 8], now=NOW)
    svc.submit("plan-1")
    _run_all(svc)
    ckey = next(k for k, n in svc._nodes("plan-1").items()
                if n["kind"] == "picture" and n["consumers"] == ["c"])
    svc.reject_work("plan-1", ckey, reason="shot_rejected")
    ctx.check("only_c_blocked",
              svc._node("plan-1", "rev:c")["status"] == "blocked"
              and svc._node("plan-1", "cmp:c")["status"] == "blocked"
              and svc._node("plan-1", "del:c")["status"] == "blocked")
    others_ok = all(svc._node("plan-1", f"rev:{v}")["status"] == "done"
                    for v in "abd")
    ctx.check("others_intact", others_ok,
              "a/b/d selections stay accepted")
    shared = [n for n in svc._nodes("plan-1").values()
              if n["kind"] == "picture" and len(n["consumers"]) > 1]
    ctx.check("shared_untouched",
              all(n["status"] in ("downloaded", "accepted")
                  for n in shared))
    return _result(ctx, "passed",
                   "C's chain blocked alone; 6 shared works + a/b/d "
                   "selections intact")


def f21_m03(ctx: CaseContext):
    """Restart after several downloads, before reviews finish: saved
    assets feed remaining jobs automatically."""
    db, sched, prov, arts, svc = _stack(ctx, "m03")
    svc.plan("plan-1", "exp1", 1, _takes(), "jimeng_canvas",
             "seedance_2.0_fast_vip", [4, 8], now=NOW)
    svc.submit("plan-1")
    for _ in range(12):
        svc.run_next()                 # partial progress, then "crash"
    done_before = svc.status("plan-1")["readiness"]["done"]
    # restart: new service + scheduler over the same db
    svc2 = ProductionService(
        db, scheduler=Scheduler(db, worker_id="w2", lease_s=300),
        executor=Executor(db, provider=prov), adapter=svc.adapter,
        artifacts=arts)
    resumed = svc2.resume("plan-1")["readiness"]
    ctx.check("resume_state", resumed["done"] == done_before
              and len(done_before) > 0,
              f"{len(done_before)} nodes persisted")
    _run_all(svc2)
    ctx.check("no_resubmits",
              len(prov.state.doc["operations"]) == 9,
              "saved assets fed remaining jobs; nothing regenerated")
    st = svc2.status("plan-1")["readiness"]
    ctx.check("finished",
              all(f"rev:{v}" in st["done"] for v in "abcd"))
    return _result(ctx, "passed",
                   "restart resumed from durable graph; 9 ops total, "
                   "four selections completed")


def f21_m04(ctx: CaseContext):
    """Allocation over provider limit + offered manual clip: declared
    split or validated manual coverage; never under-length submit."""
    db, sched, prov, arts, svc = _stack(ctx, "m04")
    takes = _takes()
    takes[0]["duration_s"] = 11.0      # 8+3 unsupported → needs_manual
    takes[1]["duration_s"] = 12.0      # 8+4 declared split
    out = svc.plan("plan-1", "exp1", 1, takes, "jimeng_canvas",
                   "seedance_2.0_fast_vip", [4, 8], now=NOW)
    stats = out["plan"]["stats"]
    ctx.check("split_declared", stats["splits"] >= 1,
              "12 s take → 8+4 declared split")
    ctx.check("manual_flagged", stats["manual_needed"] >= 1,
              "11 s take → 8+3 remainder named needs_manual")
    manual = next(k for k, n in svc._nodes("plan-1").items()
                  if n["status"] == "needs_manual")
    # offered clip too short → rejected by coverage check
    short = ctx.run_dir / "short.mp4"
    _color_mp4(short, 5.0)
    sa = arts.intake_bytes(short.read_bytes(), provenance="manual",
                           source_key="short", requested_kind="video")
    try:
        svc.replace_manual("plan-1", manual, sa.id)
        ctx.check("short_rejected", False)
    except ContractError as e:
        ctx.check("short_rejected", e.code == "insufficient_coverage")
    okp = ctx.run_dir / "ok.mp4"
    _color_mp4(okp, 12.0)
    oka = arts.intake_bytes(okp.read_bytes(), provenance="manual",
                            source_key="ok", requested_kind="video")
    res = svc.replace_manual("plan-1", manual, oka.id)
    ctx.check("manual_accepted", res["status"] == "manual"
              and res["artifact_id"] == oka.id)
    svc.submit("plan-1")
    _run_all(svc)
    ctx.check("no_underlength_submit",
              all((op.get("request") or {}).get("duration_s", 4) >= 4
                  for op in prov.state.doc["operations"].values()))
    return _result(ctx, "passed",
                   "over-limit takes declared a split or validated "
                   "manual coverage; no under-length footage submitted")


def implementations():
    return {"F21-M01": f21_m01, "F21-M02": f21_m02,
            "F21-M03": f21_m03, "F21-M04": f21_m04}
