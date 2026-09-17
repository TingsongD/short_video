"""Reviewed search batches, local receipts, and contract-compatible discovery.

An interrupted HTTP request is never retried automatically. Received responses
can be reprocessed offline using the same run ID. All writes are atomic and a
provider-wide lock prevents two radar processes submitting the same batch.
"""
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from modules.common.schema import validate
from .cluster import cluster_confirmed, group_clusters
from .report import build_report, write_report
from .viral_client import SEARCH_PATH, ViralError
from .viral_records import normalize, records


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".radar-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


@contextmanager
def run_lock(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".lock").open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ViralError("Another Viral Outliers scan is active") from None
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def run_dir(root, run_id):
    if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", run_id):
        raise ViralError("Run ID must contain only letters, digits, underscores or hyphens (max 80)")
    return Path(root) / run_id


def fingerprint(plan):
    return hashlib.sha256(json.dumps(plan, sort_keys=True, allow_nan=False).encode()).hexdigest()


def prepare(root, run_id, niche_configs, thresholds, *, platforms=None, pages=1,
            page_size=100, now=None):
    """No network or credits. Current documented unit price is verified at scan."""
    folder = run_dir(root, run_id)
    platforms = list(dict.fromkeys(platforms or ["youtube", "tiktok"]))
    if not platforms or any(p not in ("youtube", "tiktok") for p in platforms):
        raise ViralError("Choose youtube and/or tiktok")
    if type(pages) is not int or not 1 <= pages <= 5:
        raise ViralError("Pages per query must be between 1 and 5")
    if type(page_size) is not int or not 1 <= page_size <= 100:
        raise ViralError("Page size must be between 1 and 100")
    if not niche_configs or any(not n.get("keywords") for n in niche_configs):
        raise ViralError("Every selected niche needs at least one search keyword")
    criteria = {k: thresholds[k] for k in
                ("breakout_subs_ratio", "max_video_age_days", "cluster_min_channels")}
    if criteria["breakout_subs_ratio"] != 2 or not 1 <= criteria["max_video_age_days"] <= 30:
        raise ViralError("Viral Outliers requires the reviewed >2 rule and a 1–30 day window")
    # F10 selection modes — explicit, persisted, no hidden follower gate.
    mode = thresholds.get("selection_mode", "follower")
    if mode not in ("follower", "baseline", "either", "both"):
        raise ViralError("selection_mode must be follower|baseline|either|both")
    criteria["selection_mode"] = mode
    if "baseline_threshold" in thresholds:
        bt = thresholds["baseline_threshold"]
        if not isinstance(bt, (int, float)) or bt <= 0:
            raise ViralError("baseline_threshold must be positive")
        criteria["baseline_threshold"] = bt
    if "cohort_median_views" in thresholds:
        cm = thresholds["cohort_median_views"]
        if not isinstance(cm, (int, float)) or cm <= 0:
            raise ViralError("cohort_median_views must be positive")
        criteria["cohort_median_views"] = cm
    criteria["platforms"] = platforms
    selected = [{"name": n["name"], "keywords": list(dict.fromkeys(n["keywords"]))}
                for n in niche_configs]
    jobs = []
    for niche in selected:
        for query in niche["keywords"]:
            if not isinstance(query, str) or not query.strip() or len(query) > 200:
                raise ViralError("Search keywords must contain 1–200 characters")
            for platform in platforms:
                for page in range(1, pages + 1):
                    jobs.append({"niche": niche["name"], "body": {
                        "query": query, "platforms": [platform], "timeFrame": "one_month",
                        "sortBy": "views_desc", "page": page, "pageSize": page_size,
                    }})
    plan = {"version": 1, "run_id": run_id, "niches": selected, "criteria": criteria,
            "jobs": jobs, "credits_per_search": 1, "usd_per_credit": 0.01,
            "credit_quote": len(jobs), "usd_estimate": round(len(jobs) * 0.01, 2)}
    with run_lock(root):
        path = folder / "plan.json"
        if path.exists():
            old = json.loads(path.read_text())
            comparable = {k: v for k, v in old.items() if k != "prepared_at"}
            if comparable != plan:
                raise ViralError("This run ID already has a different plan; use a new run ID")
            return old
        plan["prepared_at"] = (now or datetime.now(timezone.utc)).isoformat()
        save_json(path, plan)
    return plan


def load_plan(root, run_id):
    path = run_dir(root, run_id) / "plan.json"
    if not path.exists():
        raise ViralError("No prepared search batch; run radar plan first")
    plan = json.loads(path.read_text())
    if plan.get("version") != 1 or plan.get("run_id") != run_id:
        raise ViralError("Unsupported or mismatched saved search plan")
    # Validate saved input too: manual edits must not bypass pricing, platform,
    # parameter, or strict-ratio checks established during prepare.
    def require(condition):
        if not condition:
            raise ValueError

    try:
        jobs = plan["jobs"]
        criteria = plan["criteria"]
        require(isinstance(jobs, list) and jobs)
        require(plan["credits_per_search"] == 1 and plan["usd_per_credit"] == 0.01)
        require(plan["credit_quote"] == len(jobs))
        require(plan["usd_estimate"] == round(len(jobs) * 0.01, 2))
        require(criteria["breakout_subs_ratio"] == 2)
        require(1 <= criteria["max_video_age_days"] <= 30)
        require(type(criteria["cluster_min_channels"]) is int and criteria["cluster_min_channels"] >= 2)
        require(criteria["platforms"] and set(criteria["platforms"]) <= {"youtube", "tiktok"})
        if "selection_mode" in criteria:
            require(criteria["selection_mode"] in
                    ("follower", "baseline", "either", "both"))
        if "baseline_threshold" in criteria:
            require(isinstance(criteria["baseline_threshold"], (int, float))
                    and criteria["baseline_threshold"] > 0)
        if "cohort_median_views" in criteria:
            require(isinstance(criteria["cohort_median_views"], (int, float))
                    and criteria["cohort_median_views"] > 0)
        by_niche = {n["name"]: n["keywords"] for n in plan["niches"]}
        for job in jobs:
            body = job["body"]
            require(set(body) == {"query", "platforms", "timeFrame", "sortBy", "page", "pageSize"})
            require(isinstance(body["query"], str) and body["query"].strip() and len(body["query"]) <= 200)
            require(body["query"] in by_niche[job["niche"]])
            require(len(body["platforms"]) == 1 and body["platforms"][0] in criteria["platforms"])
            require(body["timeFrame"] == "one_month" and body["sortBy"] == "views_desc")
            require(type(body["page"]) is int and 1 <= body["page"] <= 5)
            require(type(body["pageSize"]) is int and 1 <= body["pageSize"] <= 100)
    except (ValueError, KeyError, TypeError):
        raise ViralError("Invalid saved search plan; prepare a new reviewed batch") from None
    return plan


def execute(root, run_id, client, *, credit_ceiling=None, ledger=None):
    with run_lock(root):
        return _execute(root, run_id, client, credit_ceiling, ledger)


def check_charge(headers, expected):
    charged = headers.get("x-credits-charged")
    if charged is not None:
        try:
            if float(charged) != expected:
                raise ValueError
        except (TypeError, ValueError):
            raise ViralError("Unexpected provider credit charge; inspect state.json before continuing") from None


def _execute(root, run_id, client, ceiling, ledger):
    folder = run_dir(root, run_id)
    plan = load_plan(root, run_id)
    state_path = folder / "state.json"
    state = (json.loads(state_path.read_text()) if state_path.exists() else
             {"plan_hash": fingerprint(plan), "requests": {}, "status": "prepared"})
    if state["plan_hash"] != fingerprint(plan):
        raise ViralError("The saved plan changed after execution began; review it before a new run")
    if state["status"] == "charge_needs_review":
        raise ViralError("Provider credit charge needs review; no further searches submitted")
    for req in state["requests"].values():
        if req["status"] == "outcome_unknown":
            raise ViralError("A previous request has an unknown outcome. Inspect state.json; it will not be resubmitted")
        client.checked((req["http_status"], req["headers"], req["payload"]))
        records(req["payload"])
        check_charge(req["headers"], plan["credits_per_search"])
    pending = [(str(i), job) for i, job in enumerate(plan["jobs"]) if str(i) not in state["requests"]]
    if pending:
        if type(ceiling) is not int or ceiling < plan["credit_quote"]:
            raise ViralError(f"Review plan.json, then supply --credit-ceiling {plan['credit_quote']} "
                             "or higher for this entire batch")
        pricing = client.pricing()
        if (pricing["credits_per_search"] != plan["credits_per_search"] or
                pricing["usd_per_credit"] != plan["usd_per_credit"]):
            raise ViralError("Live pricing differs from the prepared quote; review pricing before a new plan")
        remaining_cost = len(pending) * plan["credits_per_search"]
        if client.credits() < remaining_cost:
            raise ViralError(f"Insufficient available API credits: need {remaining_cost} for the remaining "
                             "searches. No search submitted; check subscription billing/credit allocation")
        if ledger is None:
            raise ViralError("A cost ledger is required before submitting searches")
        ledger.entries = ledger._load()
        ledger.authorize("viral-outliers", remaining_cost * pricing["usd_per_credit"])
    for key, job in pending:
        # A crash at any point after this save leaves a non-retryable request.
        # Nominal dollars are conservatively reserved; headers below track the
        # provider's actual credit charge separately (no invented refunds).
        state["status"] = "running"
        req = {"status": "outcome_unknown", "reserved_credits": plan["credits_per_search"],
               "submitted_at": datetime.now(timezone.utc).isoformat()}
        state["requests"][key] = req
        save_json(state_path, state)
        ledger.entries = ledger._load()
        nominal = plan["credits_per_search"] * plan["usd_per_credit"]
        ledger.authorize("viral-outliers", nominal)
        ledger.record("viral-outliers", nominal, units=plan["credits_per_search"],
                      unit_type="credits_reserved", note=f"Radar {run_id}/{key}; conservative reservation, see receipt")
        try:
            status, headers, payload = client.request("POST", SEARCH_PATH, job["body"])
        except Exception:
            raise ViralError("Search outcome unknown; saved request will not be retried automatically") from None
        safe_headers = {k.lower(): v for k, v in headers.items()
                        if k.lower() in ("x-credits-charged", "x-credits-balance")}
        req.update(status="received", http_status=status, headers=safe_headers, payload=payload,
                   received_at=datetime.now(timezone.utc).isoformat())
        save_json(state_path, state)
        client.checked((status, safe_headers, payload))
        records(payload)
        # A provider price overrun is recorded and stops the rest of the batch.
        try:
            check_charge(safe_headers, plan["credits_per_search"])
        except ViralError:
            state["status"] = "charge_needs_review"
            save_json(state_path, state)
            raise
    if state["status"] == "charge_needs_review":
        raise ViralError("Provider credit charge needs review; no further searches submitted")
    report, observations = report_from_receipts(plan, state)
    validate(report, "niche_report.schema.json")
    write_report(report, folder, "niche_report")
    save_json(folder / "observations.json", observations)
    state["status"] = "complete"
    save_json(state_path, state)
    return report


def report_from_receipts(plan, state):
    grouped = {n["name"]: [] for n in plan["niches"]}
    seen = {name: set() for name in grouped}
    observations = []
    for key, job in enumerate(plan["jobs"]):
        receipt = state["requests"][str(key)]
        now = datetime.fromisoformat(receipt["received_at"])
        for row in records(receipt["payload"]):
            video, observation = normalize(row, now, plan["criteria"])
            observation.update(niche=job["niche"], request=str(key))
            if video and video["platform"] not in job["body"]["platforms"]:
                observation["reasons"].append("unexpected_platform_for_query")
                video = None
            if video:
                identity = (video["platform"], video["video_id"])
                if identity in seen[job["niche"]]:
                    observation["reasons"].append("duplicate_video")
                else:
                    seen[job["niche"]].add(identity)
                    grouped[job["niche"]].append(video)
            observations.append(observation)
    clusters = []
    for niche in plan["niches"]:
        groups = group_clusters(grouped[niche["name"]], niche["keywords"])
        for topic, videos in groups.items():
            clusters.append({"niche": niche["name"], "topic": topic, "videos": videos,
                             "confirmed": cluster_confirmed(videos, plan["criteria"]["cluster_min_channels"])})
        if not groups:
            clusters.append({"niche": niche["name"], "videos": [], "confirmed": False})
    now = max(datetime.fromisoformat(r["received_at"]) for r in state["requests"].values())
    report = build_report(clusters, now, grouped, 0)
    report["scan_meta"].update(
        provider="viral-outliers", run_id=plan["run_id"], eligibility="views / followers > 2",
        credits_reserved=len(state["requests"]) * plan["credits_per_search"],
        provider_credit_headers=[r["headers"] for r in state["requests"].values()],
        coverage="bounded keyword search pages; not an exhaustive platform scan",
        search_requests=len(plan["jobs"]), observations=len(observations),
        review_reasons=dict(Counter(reason for o in observations for reason in o["reasons"])),
    )
    return report, observations


def preview(client, thresholds, now=None):
    now = now or datetime.now(timezone.utc)
    observations = [normalize(row, now, thresholds)[1] for row in records(client.trending())]
    return {"provider": "viral-outliers", "mode": "free_preview", "credits_spent": 0,
            "observed_at": now.isoformat(), "posts": len(observations),
            "ratio_matches": sum(o["ratio_pass"] for o in observations),
            "review_reasons": dict(Counter(reason for o in observations for reason in o["reasons"])),
            "production_handoff": False, "observations": observations}
