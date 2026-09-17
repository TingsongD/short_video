"""Behavior regressions from the independent factory review (R38/R40)."""
import json
import pytest

from modules.factory.store import Database
from modules.factory.domain.errors import ContractError


def test_durable_events_never_expose_nested_credentials(tmp_path):
    db = Database(tmp_path / "factory.db")
    with db.uow() as u:
        u.events.append("experiment:test", "error", {
            "refresh_token": "synthetic-refresh",
            "nested": [{"confirmationToken": "synthetic-confirmation"}],
            "message": "credential sk_" + "a" * 40,
            "code": "transport_timeout",
        })
    events = db.uow().events.since("experiment:test", 0)
    wire = json.dumps(events)
    assert "synthetic-refresh" not in wire
    assert "synthetic-confirmation" not in wire
    assert "a" * 40 not in wire
    assert "transport_timeout" in wire


def test_acceptance_requires_evidence_even_for_existing_file(tmp_path):
    from modules.factory.quality.service import QualityService
    final = tmp_path / "bad.mp4"
    final.write_bytes(b"not a video")
    with pytest.raises(ContractError, match="acceptance_blocked"):
        QualityService(Database(tmp_path / "factory.db")).accept(final, [])


def test_real_transports_are_disabled_by_default():
    from modules.factory.integrations.drive import GdriveCLI
    from modules.factory.integrations.publisher import UploadPostPublisher
    for transport in (GdriveCLI, UploadPostPublisher):
        with pytest.raises(ContractError, match="live_disabled"):
            transport()


def test_live_mode_does_not_enable_unspecified_capability():
    from modules.factory.execution.policy import ExecutionPolicy
    policy = ExecutionPolicy("live", frozenset({"drive"}))
    policy.require_live("drive")
    with pytest.raises(ContractError, match="live_disabled"):
        policy.require_live("publish")


def test_missing_render_handler_cannot_complete_job(tmp_path):
    from modules.factory.domain.records import Job, WorkItem
    from modules.factory.production.plan import ProductionService
    from modules.factory.scheduler import Scheduler
    db = Database(tmp_path / "factory.db")
    with db.uow() as u:
        u.records.put(WorkItem(schema_version="work_item.v1", id="p:cmp:a",
                              created_at="", plan_id="p", node_key="cmp:a",
                              kind="compose", consumers=["a"]))
    scheduler = Scheduler(db)
    scheduler.submit_plan([Job(schema_version="job.v1", id="p:cmp:a",
                               created_at="", logical_key="p:cmp:a",
                               phase="render", status="ready")])
    outcome = ProductionService(db, scheduler=scheduler).run_next()
    assert outcome["error"] == "handler_unavailable"
    assert db.uow().jobs.get("p:cmp:a")["status"] != "succeeded"
