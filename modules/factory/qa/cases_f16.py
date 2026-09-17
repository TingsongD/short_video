"""F16 manual scenarios: Canvas adapter readiness/prep, partial
acceptance + interrupt, auth-expiry/download resume, live gate."""
from .cases_f01 import CaseContext, _result
from ...assets.canvas_cli import CanvasCLI, CanvasError
from ..providers.canvas import CanvasAdapter
from ..testing.fakes import FakeCanvasRunner

REQS = [{"prompt": f"shot {i} product move", "duration_s": 4,
         "model": "seedance_2.0_fast_vip"} for i in range(5)]


def _stack(ctx, name, **kw):
    runner = FakeCanvasRunner(ctx.run_dir / f"{name}.json", **kw)
    return runner, CanvasAdapter(CanvasCLI(runner=runner), {})


def f16_m01(ctx: CaseContext):
    """Readiness + prepare/quote through the fake runner; inspect IDs,
    native pricing, safe output."""
    runner, ad = _stack(ctx, "m01")
    ready = ad.readiness()
    ctx.check("readiness",
              ready["ready"] and ready["userId"] == "u-1"
              and ready["region"] == "cn", str(ready))
    prep = ad.prepare(REQS[0])
    prep2 = ad.prepare(REQS[0])
    ctx.check("recoverable_prep",
              prep == prep2 and len(runner.doc["nodes"]) == 1,
              "restart-safe: same IDs, one node")
    quote = ad.prepare_quote(REQS[0])
    ctx.check("native_quote",
              quote["max_credits"] == 54
              and ad.unit == "jimeng_credits",
              f"{quote['max_credits']} {ad.unit}")
    ctx.check("no_dispatch_without_authority",
              runner.doc["ops"] == {},
              "prepare+quote create no paid operation")
    return _result(ctx, "awaiting_manual_review",
                   "readiness/prepare/quote recoverable; pricing native "
                   "credits; zero ops before dispatch authority",
                   limitations=["human inspects IDs + quote evidence"])


def f16_m02(ctx: CaseContext):
    """Accept 2 of 5 jobs, interrupt the runner; accepted IDs preserved,
    others not mislabeled, recovery makes no duplicates."""
    runner, ad = _stack(ctx, "m02")
    accepted = [ad.submit(REQS[i]) for i in range(2)]
    ctx.check("two_accepted",
              len(accepted) == 2
              and all(a["status"] == "accepted" for a in accepted))
    runner.expire_login()              # interrupt the runner
    # 'restart': new adapter + runner on the same state file
    ad2 = CanvasAdapter(
        CanvasCLI(runner=FakeCanvasRunner(
            ctx.run_dir / "m02.json")), {})
    # recovery: reconcile prior accepts; submit remaining three
    rec = [ad2.reconcile(operation_id=a["operation_id"])
           for a in accepted]
    ctx.check("accepted_ids_preserved",
              all(r is not None and r["operation_id"] == a["operation_id"]
                  for r, a in zip(rec, accepted)))
    rest = [ad2.submit(REQS[i]) for i in range(2, 5)]
    remote = FakeCanvasRunner(ctx.run_dir / "m02.json")
    ctx.check("no_duplicate_submissions",
              len(remote.doc["ops"]) == 5
              and len({o["submitId"] for o in
                       remote.doc["ops"].values()}) == 5,
              f"{len(remote.doc['ops'])} ops, "
              f"{len(remote.doc['nodes'])} nodes")
    statuses = {o["operation_id"]: o["status"] for o in
                (accepted + rest)}
    ctx.check("no_mislabeled_running",
              set(statuses.values()) == {"accepted"},
              "post-restart submits are 'accepted', never guessed 'running'")
    return _result(ctx, "passed",
                   "2 accepted ops preserved across interrupt; recovery "
                   "submitted the remaining 3 with no duplicate")


def f16_m03(ctx: CaseContext):
    """Expire login during observation, reconnect, resume a failed
    download; wrong-account reconnect rejected."""
    runner, ad = _stack(ctx, "m03")
    out = ad.submit(REQS[0])
    ad.observe(out["operation_id"])    # poll 1
    ad.observe(out["operation_id"])    # poll 2 → SUCCEEDED
    runner.set_fault("download_fails")
    try:
        ad.download(out["operation_id"])
        ctx.check("download_fails_named", False)
    except Exception as e:
        ctx.check("download_fails_named",
                  "transport_error" in str(e), str(e))
    ctx.check("retry_not_regenerate",
              len(runner.doc["ops"]) == 1,
              "failed download created no new operation")
    runner.expire_login()
    obs = ad.readiness()
    ctx.check("expired_named", obs["reason"] == "login_required")
    runner.reconnect(user_id="u-2")    # wrong account
    ad.expected_user = "u-1"
    ctx.check("wrong_account_rejected",
              ad.readiness()["reason"] == "account_mismatch")
    runner.reconnect(user_id="u-1")    # correct account
    runner.doc["faults"].remove("download_fails")
    runner._save()
    dl = ad.download(out["operation_id"])
    ctx.check("same_op_resumed",
              dl["operation_id"] == out["operation_id"]
              and dl["sha256"], "original op ID, bytes verified")
    return _result(ctx, "passed",
                   "expired login named; wrong-account rejected; "
                   "download retried on the same accepted op")


def f16_m04(ctx: CaseContext):
    """Live readiness/one-shot qualification — funded scope only."""
    return _result(ctx, "awaiting_manual_review",
                   "live gate: requires an existing valid authorization "
                   "with available balance; offline fake success does "
                   "not qualify the route",
                   limitations=["funded scope absent — live qualification "
                                "remains blocked by design"])


def implementations():
    return {"F16-M01": f16_m01, "F16-M02": f16_m02,
            "F16-M03": f16_m03, "F16-M04": f16_m04}
