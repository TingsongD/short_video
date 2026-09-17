"""Offline native Hypit check → plan → build → retrieve → owned cleanup.

Use a fresh --root. This fixture contains no generation or hosted endpoints.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from modules.factory.store import Database
from modules.factory.store.uow import utcnow
from modules.factory.artifacts.registry import ArtifactStore
from modules.factory.composition import CompositionService, HypitGate
from modules.factory.rendering import HypitBuildRunner
from modules.factory.testing.fixtures import _color_mp4


def qualify(root):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=False)
    db = Database(root / "factory.db")
    artifacts = ArtifactStore(root / "artifacts", db)
    source = root / "source.mp4"
    _color_mp4(source, 1.0, size="360x640")
    art = artifacts.intake_file(source, provenance="manual", source_key="local-hypit-fixture", requested_kind="video")
    out = CompositionService(db, artifacts, root / "compositions").compile(
        "comp-local", "exp-local", "A", "plan-local", [{"id": "s1", "kind": "picture", "artifact_id": art.id,
        "sha256": art.sha256, "in_frame": 0, "out_frame": 30, "source_in_s": 0, "source_out_s": 1}],
        [], {"fps": 30, "width": 360, "height": 640}, now=utcnow())
    source = Path(out["files"]["render.svrun"])
    workspace = source.parent
    profile = workspace / "hypit.runtime.json"
    profile.write_text(json.dumps({"format": "hypit.runtime-local@1", "dataRoot": ".hypit/runtimes/local",
        "endpoints": {"media.local": {"use": "@hypit/provider-media-local", "config": {"defaultConcurrency": 1}},
        "hyperframes.local": {"use": "@hypit/provider-hyperframes-local", "config": {"workers": 1, "defaultConcurrency": 1, "browserCapacity": 1}}}}))
    launcher = str(ROOT / "scripts/hypit.sh")
    subprocess.run([launcher, "runtime", "use", str(profile), "--workspace", str(workspace), "--json"],
                   capture_output=True, text=True, timeout=30, check=True)
    evidence = {"scope": "offline-local-render", "hosted_requests": 0, "workspace": str(workspace)}
    try:
        gate = HypitGate()
        plan = gate.plan(source)
        evidence["check"] = gate.check(source)
        evidence["plan"] = plan
        if not plan["ok"] or not evidence["check"]["ok"]:
            raise RuntimeError("local_plan_failed")
        runner = HypitBuildRunner()
        build = runner.submit(source)
        evidence["build"] = build
        print(json.dumps({"build_id": build["build_id"], "state": "submitted"}), flush=True)
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            observed = runner.observe(build["build_id"], workspace)
            if observed["status"] in ("succeeded", "failed"):
                break
            time.sleep(1)
        evidence["observed"] = observed
        if observed["status"] != "succeeded":
            raise RuntimeError("local_build_" + observed["status"])
        final = runner.retrieve(build["build_id"], "final.video", root / "fixture-final.mp4", workspace)
        result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height,nb_frames,r_frame_rate",
                                 "-of", "json", str(final)], capture_output=True, text=True, timeout=30, check=True)
        evidence["probe"] = json.loads(result.stdout)
        video = next(s for s in evidence["probe"]["streams"] if s.get("width"))
        assert video["width"] == 360 and video["height"] == 640 and int(video["nb_frames"]) == 30
        evidence["status"] = "passed"
        print(json.dumps({"status": "passed", "frames": 30, "hosted_requests": 0}), flush=True)
    finally:
        cleanup = subprocess.run([launcher, "runtime", "down", "--runtime", str(profile), "--workspace", str(workspace), "--json"],
                                 capture_output=True, text=True, timeout=30)
        evidence["cleanup"] = {"returncode": cleanup.returncode}
        (root / "qualification.json").write_text(json.dumps(evidence, indent=2))
        print(json.dumps({"owned_runtime_stopped": cleanup.returncode == 0}), flush=True)
    return evidence


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    qualify(parser.parse_args().root)
