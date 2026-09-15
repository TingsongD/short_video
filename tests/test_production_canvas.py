"""Production wiring with real Canvas adapter and mocked paid boundaries."""
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from modules.assets.canvas import CanvasAssets
from modules.assets.canvas_cli import CanvasCLI
from modules.assemble.materials import file_hash
from modules.orchestrate import pipeline, stages
from test_asset_canvas import FakeProcess, SETTINGS, paid_calls
from test_failure_drills import make_ctx, good_runner


class LongMediaProcess(FakeProcess):
    def __call__(self, cmd, **kwargs):
        result = super().__call__(cmd, **kwargs)
        if "download" in cmd:
            envelope = json.loads(result.stdout)
            data = envelope["data"]
            path = Path(data["path"])
            if path.suffix == ".mp4":
                temp = path.with_suffix(".long.mp4")
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-stream_loop", "-1",
                                "-i", str(path), "-t", "30", "-c", "copy", str(temp)],
                               capture_output=True, check=True)
                temp.replace(path)
                data.update(size=path.stat().st_size, sha256=file_hash(path))
                result.stdout = json.dumps(envelope)
        return result


def run(ctx, tmp_path):
    return pipeline.run_stages("produce", stages.produce_stages("idea-drill-1", ctx),
                               log_dir=tmp_path / "runs")


def setup(ctx):
    process = LongMediaProcess()
    ctx.update(asset_provider="jimeng-canvas", asset_fallback="none", stop_after="qc",
               canvas_wait_seconds=0,
               canvas_assets=CanvasAssets(CanvasCLI(runner=process), ctx["base_dir"], SETTINGS))
    return process


def test_quote_then_resume_generate_handoff_qc_and_no_duplicate_work(tmp_path):
    vendor_output = tmp_path / "vendor-output"
    vendor_output.mkdir()
    ctx = make_ctx(tmp_path, mpt_runner=good_runner(vendor_output))
    process = setup(ctx)
    first = run(ctx, tmp_path)
    assert first["status"] == "needs_review" and first["stopped_at"] == "assets"
    quote = first["stages"][-1]["details"]["quote"]
    assert quote["totalMaxCredits"] > 0 and not paid_calls(process)
    assert len(ctx["ledger"].entries) == 1  # script only
    ctx["resume"] = True
    assert run(ctx, tmp_path)["status"] == "needs_review"
    assert len(ctx["ledger"].entries) == 1
    ctx["jimeng_credit_ceiling"] = quote["totalMaxCredits"]
    result = run(ctx, tmp_path)
    assert result["status"] == "ok", result
    assert result["stages"][-1]["name"] == "qc"
    folder = ctx["base_dir"] / ctx["video_id"]
    manifest = json.loads((folder / "assets/manifest.json").read_text())
    assert manifest["complete"] and all(a["source"] == "jimeng" for a in manifest["assets"])
    assert file_hash(folder / "final-1.mp4") == file_hash(vendor_output / "final-1.mp4")
    report = json.loads((folder / "qc_report.json").read_text())
    assert report["passed"] and report["voice_duration_s"] == pytest.approx(20)
    assert not ctx["published_dir"].exists()
    assert [e["service"] for e in ctx["ledger"].entries] == ["llm", "elevenlabs"]
    submitted = len(paid_calls(process))
    def unexpected(*a, **kw):
        pytest.fail("valid final should be reused on resume")
    ctx["mpt_runner"] = unexpected
    assert run(ctx, tmp_path)["status"] == "ok"
    assert len(paid_calls(process)) == submitted and len(ctx["ledger"].entries) == 2


def test_assets_review_stop_and_changed_script_block(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.update(stop_after="assets")
    result = run(ctx, tmp_path)
    assert result["status"] == "ok" and result["stages"][-1]["name"] == "assets"
    assert len(ctx["ledger"].entries) == 1
    folder = ctx["base_dir"] / ctx["video_id"]
    assert not (folder / "voice.mp3").exists()
    doc = json.loads((folder / "shot_list.json").read_text())
    doc["shots"][0]["prompt_jimeng"] += " changed"
    (folder / "shot_list.json").write_text(json.dumps(doc))
    ctx["resume"] = True
    failed = run(ctx, tmp_path)
    assert failed["failed_at"] == "hook" and "changed" in failed["stages"][0]["error"]
    assert len(ctx["ledger"].entries) == 1


def test_existing_production_requires_resume_and_stock_is_explicit(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.update(asset_fallback="none", stop_after="assets")
    result = run(ctx, tmp_path)
    assert result["failed_at"] == "assets"
    folder = ctx["base_dir"] / ctx["video_id"]
    assert not list((folder / "assets").glob("*.stock.*"))
    result = run(ctx, tmp_path)
    assert result["failed_at"] == "hook" and "--resume" in result["stages"][0]["error"]
    assert len(ctx["ledger"].entries) == 1


def test_live_clients_are_lazy_for_asset_only_and_resume(monkeypatch):
    from modules.common import config
    from modules.orchestrate.__main__ import _live_production_clients
    monkeypatch.setattr(config, "secrets", lambda: {})
    clients = _live_production_clients({"voice": {"voice_id": "", "model": "test"}})
    assert clients["pexels"] is None
    assert clients["llm"].client is None and clients["tts"].client is None


def test_production_lock_prevents_concurrent_paid_attempts(tmp_path):
    from modules.orchestrate.checkpoint import production_lock
    with production_lock(tmp_path):
        with pytest.raises(RuntimeError, match="already running"):
            with production_lock(tmp_path):
                pytest.fail("second producer entered")
    with production_lock(tmp_path):
        pass
