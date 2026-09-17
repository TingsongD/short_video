"""Validation-record evidence per runbook §6.

Records land under <workspace>/evidence/<module>/<run-id>/record.json.
`status` may be `awaiting_manual_review` until a reviewer attaches a
verdict; `record_manual_verdict` requires reviewer identity, timestamp and
artifact revision — a human step, not an auto-pass.
"""
import hashlib
import json
import re
from pathlib import Path

from ..testing.clock import utcnow_iso

from ..events.redact import redact, SECRET_PATTERNS


def new_record(case_id, module_id, mode, expected, fixture_version,
               source_revision=None):
    return {
        "schema_version": "factory.validation.v1",
        "module_id": module_id,
        "case_id": case_id,
        "mode": mode,
        "status": "not_run",
        "source_revision": source_revision,
        "dirty_diff_sha256": None,
        "untracked_manifest_sha256": None,
        "checkpoint_report": None,
        "fixture_version": fixture_version,
        "started_at": utcnow_iso(),
        "finished_at": None,
        "reviewer": None,
        "expected": expected,
        "actual": None,
        "assertions": [],
        "artifacts": [],
        "provider_submission_count": 0,
        "budget_evidence": None,
        "limitations": [],
        "cleanup_receipt": None,
    }


def save(workspace_path, record):
    out = (Path(workspace_path) / "evidence" / record["module_id"]
           / record["run_id"] if "run_id" in record else
           Path(workspace_path) / "evidence" / record["module_id"])
    out.mkdir(parents=True, exist_ok=True)
    target = out / (record.get("run_id", "record") + ".json"
                    if "run_id" in record else "record.json")
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(redact(record), indent=1, sort_keys=True))
    tmp.replace(target)
    return target


def record_manual_verdict(record, reviewer, verdict, artifact_revision,
                          notes=""):
    if verdict not in ("pass", "fail", "blocked", "not_applicable"):
        raise ValueError("verdict must be pass/fail/blocked/not_applicable")
    if not reviewer:
        raise ValueError("manual verdict requires a reviewer identity")
    if not artifact_revision:
        raise ValueError("manual verdict requires the reviewed artifact revision")
    record["reviewer"] = reviewer
    record["manual_verdict"] = {
        "verdict": verdict, "artifact_revision": artifact_revision,
        "notes": notes, "at": utcnow_iso()}
    record["status"] = ("passed" if verdict == "pass" else verdict)
    record["finished_at"] = utcnow_iso()
    return record


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
