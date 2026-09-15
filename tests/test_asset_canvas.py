"""Canvas contract tests: real adapter, mocked official CLI process boundary."""
import copy
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from modules.assets.canvas import CanvasAssets, STATE_NAME
from modules.assets.canvas_cli import CanvasCLI, CanvasError
from modules.assets.canvas_models import choose_model, generation_parameters
from modules.assets.canvas_state import read_state
from modules.assets.__main__ import collect
from modules.assets.intake import scan_folder, validate_file
from modules.assets.manifest import build_manifest, write_manifest

FIXTURES = Path(__file__).parent / "fixtures"
DOC = json.loads((FIXTURES / "contracts/shot_list.sample.json").read_text())
SETTINGS = {"video_model": "fast-test", "image_model": "image-test"}


def shot_list():
    doc = copy.deepcopy(DOC)
    doc["video_id"] = "canvas-test"
    for s in doc["shots"]:
        s["duration_s"] = 3
    return doc


def catalog(kind):
    flags = [{"flag": "--prompt", "required": True, "maxLength": 2000},
             {"flag": "--ratio", "values": ["9:16", "16:9"]},
             {"flag": "--resolution", "values": ["720P"] if kind == "video" else ["2K"]},
             {"flag": "--count", "min": 1, "max": 1}]
    if kind == "video":
        flags.append({"flag": "--duration", "min": 4, "max": 15, "step": 1})
    return [{"model": "fast-test" if kind == "video" else "image-test", "type": kind,
             "aliases": ["seedance-test-fast"] if kind == "video" else [],
             "modes": [{"name": "t2v" if kind == "video" else "t2i", "flags": flags}]}]


def protocol():
    # The minimal public CLI command/flag contract, with no secrets or live calls.
    groups = {
        "canvas": {"create": ["project-id"], "ls": ["cursor"]},
        "node": {"create": [], "quote": ["node-id"], "confirm": ["credit-ceiling"],
                 "run": ["submit-id", "credit-token"], "show": ["node-id"]},
        "operation": {"status": ["project-id"], "wait": ["timeout"]},
        "resource": {"download": ["output"]},
    }
    out = []
    for name, children in groups.items():
        subs = [{"name": k, "flags": [{"name": f} for f in v]} for k, v in children.items()]
        if name == "node":
            subs[0]["subcommands"] = [
                {"name": kind, "flags": [{"name": f} for f in
                 ["node-id", "update-id", "duration", "model", "mode"]]}
                for kind in ["image", "video"]]
        out.append({"name": name, "subcommands": subs})
    return {"subcommands": out}


class FakeProcess:
    def __init__(self):
        self.calls, self.nodes, self.operations, self.projects = [], {}, {}, {}
        self.price, self.logged_in, self.user_id = 10, True, 123
        self.pending, self.lose_submit, self.reject_shot = False, False, None
        self.bad_json, self.quote_error, self.download_failure = False, False, False

    def __call__(self, cmd, **kwargs):
        assert kwargs.get("capture_output") is True
        assert "--format" in cmd and "--non-interactive" in cmd
        args = cmd[cmd.index("--region") + 2:]
        self.calls.append(args)
        def flag(name):
            return args[args.index("--" + name) + 1]
        group = args[0]
        if self.bad_json:
            return SimpleNamespace(returncode=0, stdout="not JSON token=DO-NOT-LOG")
        if group == "version":
            data = {"version": "1.0.1", "commit": "83aeb67"}
        elif group == "schema":
            data = protocol()
        elif args[:2] == ["auth", "status"]:
            data = {"loggedIn": self.logged_in, "region": "cn", "environment": "prod"}
        elif args[:2] == ["auth", "account"]:
            data = {"userId": self.user_id, "isVip": True}
        elif group == "model":
            data = {"items": catalog(flag("type"))}
        elif args[:2] == ["canvas", "create"]:
            pid = flag("project-id")
            project = {"projectId": pid, "name": args[2], "webUrl": "https://example.test/canvas/" + pid}
            self.projects[pid] = project
            data = {"project": project}
        elif args[:2] == ["canvas", "ls"]:
            data = {"items": list(self.projects.values()), "hasMore": False}
        elif args[:2] == ["node", "create"]:
            assert "--run" not in args
            nid = flag("node-id")
            # Canvas 1.0.1 rejects other IDs locally, before saving the draft.
            assert re.fullmatch(r"node_[0-9a-hjkmnp-tv-z]{10}", nid), "invalid Canvas Node ID"
            g = {k: flag(k) for k in ["model", "mode", "prompt", "ratio", "resolution"]}
            g["outputCount"] = int(flag("count"))
            if args[2] == "video":
                g["durationSeconds"] = float(flag("duration"))
            self.nodes[nid] = {"nodeId": nid, "type": args[2], "generation": g, "resources": []}
            data = {"node": self.nodes[nid]}
        elif args[:2] == ["node", "show"]:
            nid = flag("node-id")
            data = {"nodes": [{"result": "FOUND", "nodeId": nid, "node": self.nodes[nid]}]}
        elif args[:2] == ["node", "quote"]:
            ids = [args[i + 1] for i, x in enumerate(args) if x == "--node-id"]
            items = [{"nodeId": n, "maxCredits": self.price} for n in ids]
            if self.quote_error:
                items[-1] = {"nodeId": ids[-1], "error": {"serviceCode": 500}}
            data = {"items": items, "totalMaxCredits": self.price * len(ids), "confirmable": True}
        elif args[:2] == ["node", "confirm"]:
            data = {"creditConfirmationToken": "PRIVATE-CREDIT-TOKEN", "creditCeiling": int(flag("credit-ceiling"))}
        elif args[:2] == ["node", "run"]:
            nid, sid = flag("node-id"), flag("submit-id")
            assert sid not in self.operations, "duplicate paid submission"
            rejected = nid == self.reject_shot
            resource = "d86a3a49-967b-4152-aee6-" + sid[-12:]
            self.operations[sid] = {"operationRef": sid, "state": "succeeded",
                                    "resources": [{"resourceId": resource, "state": "succeeded"}]}
            self.nodes[nid]["resources"] = [{"resourceId": resource, "submitId": sid,
                                            "type": self.nodes[nid]["type"], "status": "success"}]
            data = {"items": [{"nodeId": nid, "submitId": sid, "state": "REJECTED" if rejected else "ACCEPTED"}]}
            if self.lose_submit:
                raise subprocess.TimeoutExpired(cmd, 60, output="PRIVATE-CREDIT-TOKEN")
        elif group == "operation":
            data = copy.deepcopy(self.operations.get(args[2], {"operationRef": args[2], "state": "unknown", "resources": []}))
            if self.pending:
                data["state"], data["resources"] = "running", []
        elif args[:2] == ["resource", "download"]:
            if self.download_failure:
                raise OSError("download error with PRIVATE-CREDIT-TOKEN")
            node = next(n for n in self.nodes.values() if any(r["resourceId"] == args[2] for r in n["resources"]))
            filename = "good_video.mp4" if node["type"] == "video" else "good_image.png"
            target = Path(flag("output")) / filename
            shutil.copy(FIXTURES / "media" / filename, target)
            data = {"path": str(target), "size": target.stat().st_size,
                    "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}
        else:
            raise AssertionError(args)
        return SimpleNamespace(returncode=0, stdout=json.dumps({"schemaVersion": "1", "ok": True, "data": data}))


@pytest.fixture
def setup(tmp_path):
    process = FakeProcess()
    assets = CanvasAssets(CanvasCLI(runner=process), tmp_path, SETTINGS)
    return assets, process


def paid_calls(process):
    return [c for c in process.calls if c[:2] == ["node", "run"]]


def test_prepare_quotes_all_shots_without_generating_and_reuses_nodes(setup):
    assets, p = setup
    first = assets.prepare(shot_list())
    assert first["quote"]["totalMaxCredits"] == len(DOC["shots"]) * 10
    assert not paid_calls(p)
    assets.prepare(shot_list())
    assert len([c for c in p.calls if c[:2] == ["canvas", "create"]]) == 1
    assert len(p.nodes) == len(DOC["shots"])
    path = assets.path("canvas-test")
    assert path.stat().st_mode & 0o777 == 0o600
    assert "TOKEN" not in path.read_text()


def test_full_generation_downloads_correct_types_provenance_and_complete_manifest(setup):
    assets, p = setup
    assets.prepare(shot_list())
    result = assets.generate("canvas-test", 100)
    assert result["complete"]
    assert result["reserved_credits"] == len(DOC["shots"]) * 10
    manifest = json.loads((assets.path("canvas-test").parent / "manifest.json").read_text())
    assert manifest["complete"] and all(a["source"] == "jimeng" for a in manifest["assets"])
    assert [a["kind"] for a in manifest["assets"]] == [s["asset_type"] for s in DOC["shots"]]
    before = len(paid_calls(p))
    assets.generate("canvas-test", 100)
    assert len(paid_calls(p)) == before
    assert "PRIVATE-CREDIT-TOKEN" not in assets.path("canvas-test").read_text()


def test_ceiling_and_unquotable_shots_block_before_confirm(setup):
    assets, p = setup
    assets.prepare(shot_list())
    with pytest.raises(CanvasError, match="ceiling"):
        assets.generate("canvas-test", 1)
    assert not any(c[:2] == ["node", "confirm"] for c in p.calls)
    p.quote_error = True
    with pytest.raises(CanvasError, match="quote_incomplete"):
        assets.generate("canvas-test", 1000)
    assert not paid_calls(p)


def test_interrupted_submission_recovers_same_id_without_second_charge(setup):
    assets, p = setup
    assets.prepare(shot_list(), [0])
    p.lose_submit = True
    with pytest.raises(CanvasError) as e:
        assets.generate("canvas-test", 10)
    assert "PRIVATE" not in str(e.value)
    assert read_state(assets.path("canvas-test"))["shots"][0]["state"] == "unknown"
    with pytest.raises(CanvasError, match="already_active"):
        assets.generate("canvas-test", 10)
    restarted = CanvasAssets(assets.cli, assets.base, SETTINGS)
    assert restarted.resume("canvas-test")["complete"]
    assert len(paid_calls(p)) == 1


def test_pending_job_stops_batch_and_status_does_not_write(setup):
    assets, p = setup
    assets.prepare(shot_list())
    p.pending = True
    result = assets.generate("canvas-test", 100)
    assert len(paid_calls(p)) == 1 and not result["complete"]
    before = assets.path("canvas-test").read_bytes()
    p.pending = False
    assert assets.status("canvas-test")["shots"][0]["state"] == "succeeded"
    assert assets.path("canvas-test").read_bytes() == before
    assets.resume("canvas-test")
    assert len(paid_calls(p)) == 1
    assert assets.generate("canvas-test", 100)["complete"]
    assert len(paid_calls(p)) == len(DOC["shots"])


def test_wait_timeout_without_partial_data_reads_same_submission_status(setup):
    assets, process = setup
    def wait_timeout(cmd, **kwargs):
        args = cmd[cmd.index("--region") + 2:]
        if args[:2] == ["operation", "wait"]:
            process.calls.append(args)
            return SimpleNamespace(returncode=20, stdout=json.dumps({
                "schemaVersion": "1", "ok": False,
                "error": {"code": "cli.operation_wait_timeout",
                          "requiredAction": "resume", "operationRef": args[2]}}))
        return process(cmd, **kwargs)
    assets.cli.runner = wait_timeout
    assets.prepare(shot_list(), [0])
    process.pending = True
    result = assets.generate("canvas-test", 10, wait_seconds=5)
    assert result["shots"][0]["state"] == "running"
    process.pending = False
    assert assets.resume("canvas-test", wait_seconds=5)["complete"]
    assert len(paid_calls(process)) == 1
    submit_id = paid_calls(process)[0][paid_calls(process)[0].index("--submit-id") + 1]
    assert all(c[2] == submit_id for c in process.calls if c[0] == "operation")


def test_download_failure_recovers_without_regeneration(setup):
    assets, p = setup
    assets.prepare(shot_list(), [0])
    p.download_failure = True
    with pytest.raises(CanvasError):
        assets.generate("canvas-test", 10)
    p.download_failure = False
    assert assets.resume("canvas-test")["complete"]
    assert len(paid_calls(p)) == 1


def test_edited_draft_and_input_changes_require_explicit_new_generation(setup):
    assets, p = setup
    assets.prepare(shot_list())
    changed = shot_list()
    changed["shots"][0]["prompt_jimeng"] = "a changed prompt"
    with pytest.raises(CanvasError, match="generation_changed"):
        assets.prepare(changed)
    next(iter(p.nodes.values()))["generation"]["prompt"] = "edited in browser"
    with pytest.raises(CanvasError, match="draft_changed"):
        assets.generate("canvas-test", 100)
    assert not paid_calls(p)


def test_partial_batch_rejection_preserves_completed_outputs(setup):
    assets, p = setup
    assets.prepare(shot_list())
    job = read_state(assets.path("canvas-test"))
    p.reject_shot = job["shots"][1]["node_id"]
    result = assets.generate("canvas-test", 100)
    assert [s["state"] for s in result["shots"][:2]] == ["downloaded", "rejected"]
    assert len(paid_calls(p)) == 2
    assets.resume("canvas-test")
    assert len(paid_calls(p)) == 2


def test_local_assets_are_reused_without_spending(setup):
    assets, p = setup
    assets.prepare(shot_list(), [0])
    folder = assets.path("canvas-test").parent
    shutil.copy(FIXTURES / "media/good_video.mp4", folder / "shot-00.mp4")
    assert assets.generate("canvas-test", 0)["complete"]
    assert not paid_calls(p)


def test_missing_cli_expired_login_wrong_account_and_malformed_response(setup):
    def missing(*a, **k):
        raise FileNotFoundError()
    with pytest.raises(CanvasError, match="cli_missing"):
        CanvasCLI(runner=missing).doctor()
    assets, p = setup
    p.logged_in = False
    with pytest.raises(CanvasError, match="login_required"):
        assets.prepare(shot_list())
    p.logged_in = True
    assets.prepare(shot_list())
    p.user_id = 999
    with pytest.raises(CanvasError, match="account_mismatch"):
        assets.generate("canvas-test", 100)
    p.bad_json = True
    with pytest.raises(CanvasError, match="invalid_response") as e:
        assets.cli.doctor()
    assert "DO-NOT-LOG" not in str(e.value)


def test_native_validation_error_on_stderr_preserves_code_without_leaking_message():
    error = {"schemaVersion": "1", "ok": False,
             "error": {"code": "cli.invalid_command", "requiredAction": "none",
                       "message": "PRIVATE-TOKEN",
                       "validation": {"reasonCode": "CLI_NODE_ID_INVALID"}}}
    def rejected(*args, **kwargs):
        return SimpleNamespace(returncode=2, stdout="", stderr=json.dumps(error))
    with pytest.raises(CanvasError, match="cli.invalid_command") as caught:
        CanvasCLI(runner=rejected).call("node", "create", "video")
    assert "PRIVATE" not in str(caught.value)


@pytest.mark.parametrize("returncode,stdout,stderr", [
    (2, "", "not JSON PRIVATE-TOKEN"),
    (0, "", '{"schemaVersion":"1","ok":true,"data":{"unexpected":true}}'),
    (2, "not JSON", '{"schemaVersion":"1","ok":false,"error":{"code":"other"}}'),
])
def test_error_stream_never_hides_malformed_stdout_or_supplies_success(returncode, stdout, stderr):
    def response(*args, **kwargs):
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)
    with pytest.raises(CanvasError, match="invalid_response") as caught:
        CanvasCLI(runner=response).call("version")
    assert "PRIVATE" not in str(caught.value)


def test_duration_rounds_up_and_unsupported_combination_fails_before_writes(setup):
    assets, p = setup
    doc = shot_list()
    doc["shots"][0]["duration_s"] = 5.2
    assets.prepare(doc, [0])
    assert next(iter(p.nodes.values()))["generation"]["durationSeconds"] == 6
    doc["video_id"] = "too-long"
    doc["shots"][0]["duration_s"] = 20
    before = len(p.projects)
    with pytest.raises(CanvasError, match="duration_above"):
        assets.prepare(doc, [0])
    assert len(p.projects) == before
    selected = choose_model(catalog("video"), "video", "fast-test")
    with pytest.raises(CanvasError, match="unsupported_resolution"):
        generation_parameters(shot_list()["shots"][0], selected, "1080P")


def test_image_cannot_satisfy_video_even_with_mp4_filename(tmp_path):
    path = tmp_path / "shot-00.mp4"
    shutil.copy(FIXTURES / "media/good_image.png", path)
    assert not validate_file(path, "video")[0]
    doc = build_manifest("v-test", tmp_path, 1, {0: "video"})
    assert not doc["complete"] and doc["missing_shots"] == [0]
    assert write_manifest(doc, tmp_path) is None
    assert not (tmp_path / "manifest.json").exists()


def test_wrong_kind_candidate_does_not_hide_valid_candidate(tmp_path):
    shutil.copy(FIXTURES / "media/good_image.png", tmp_path / "shot-00.jimeng.png")
    shutil.copy(FIXTURES / "media/good_video.mp4", tmp_path / "shot-00.mp4")
    assert scan_folder(tmp_path, {0: "video"})[0]["file"] == "shot-00.mp4"


def test_empty_collect_and_no_implicit_stock(tmp_path):
    from modules.assets.queue import render_cards
    render_cards(shot_list(), base=tmp_path)
    result = collect("canvas-test", tmp_path)
    assert result["assets"] == [] and result["missing_shots"]
    assert not (tmp_path / "canvas-test/assets/manifest.json").exists()


def test_discrete_duration_catalog_preserves_cli_integer_values():
    items = catalog("video")
    items[0]["modes"][0]["flags"][-1] = {"flag": "--duration", "values": ["5", "10"]}
    shot = shot_list()["shots"][0] | {"duration_s": 5.2}
    params = generation_parameters(shot, choose_model(items, "video"))
    assert params["duration"] == 10 and type(params["duration"]) is int


def test_nonfinite_duration_and_active_other_video_block_new_work(setup):
    assets, process = setup
    invalid = shot_list()
    invalid["shots"][0]["duration_s"] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        assets.prepare(invalid)
    assert not process.projects
    assets.prepare(shot_list(), [0])
    process.pending = True
    assets.generate("canvas-test", 10)
    other = shot_list() | {"video_id": "another-video"}
    assets.prepare(other, [0])
    with pytest.raises(CanvasError, match="already_active"):
        assets.generate("another-video", 10)
    assert len(paid_calls(process)) == 1


def test_manual_replacement_of_rejected_shot_allows_remaining_batch_without_replay(setup):
    assets, process = setup
    assets.prepare(shot_list())
    job = read_state(assets.path("canvas-test"))
    process.reject_shot = job["shots"][1]["node_id"]
    assets.generate("canvas-test", 100)
    replacement = assets.path("canvas-test").parent / "shot-01.mp4"
    shutil.copy(FIXTURES / "media/good_video.mp4", replacement)
    assert assets.generate("canvas-test", 100)["complete"]
    submitted = len(paid_calls(process))
    assert submitted == len(DOC["shots"])
    replacement.unlink()
    assert not assets.status("canvas-test")["complete"]
    with pytest.raises(CanvasError, match="needs_review"):
        assets.generate("canvas-test", 100)
    assert len(paid_calls(process)) == submitted
