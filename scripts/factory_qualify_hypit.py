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


def qualify(root, rich=False):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=False)
    db = Database(root / "factory.db")
    artifacts = ArtifactStore(root / "artifacts", db)
    source = root / "source.mp4"
    _color_mp4(source, 1.0, size="360x640")
    art = artifacts.intake_file(source, provenance="manual", source_key="local-hypit-fixture", requested_kind="video")
    clock={"fps":30,"width":360,"height":640}
    segments=[{"id":"s1","kind":"picture","artifact_id":art.id,"sha256":art.sha256,
               "in_frame":0,"out_frame":30,"source_in_s":0,"source_out_s":1}]
    captions=[]
    expected_frames=30
    if rich:
        from modules.factory.testing.fixtures import _png
        from modules.factory.audio import pcm
        red=root/"red.mp4";blue=root/"blue.mp4";source=root/"two-colors.mp4"
        _color_mp4(red,1.25,rate=24,color="red",audio=False)
        _color_mp4(blue,1.25,rate=24,color="blue",audio=False)
        subprocess.run(["ffmpeg","-v","error","-y","-i",str(red),"-i",str(blue),
                        "-filter_complex","[0:v][1:v]concat=n=2:v=1:a=0[v]","-map","[v]",str(source)],check=True)
        video=artifacts.intake_file(source,provenance="manual",source_key="offset-fixture",requested_kind="video")
        still=root/"green.png";_png(still,color="0x00ff00")
        image=artifacts.intake_file(still,provenance="manual",source_key="still-fixture",requested_kind="image")
        voice=artifacts.intake_bytes(pcm.write_wav(pcm.sine(.5)),provenance="manual",source_key="delayed-voice",requested_kind="audio")
        clock={"fps":24,"width":360,"height":640,"total_frames":48};expected_frames=48
        segments=[{"id":"s1","kind":"picture","artifact_id":video.id,"sha256":video.sha256,
                   "in_frame":0,"out_frame":24,"source_in_s":1.25,"source_out_s":2.5,
                   "transition_out":"crossfade","transition_frames":6,"effects":["kenburns"]},
                  {"id":"s2","kind":"picture","artifact_id":image.id,"sha256":image.sha256,
                   "in_frame":24,"out_frame":48,"source_in_s":0,"source_out_s":1},
                  {"id":"voice","kind":"audio","artifact_id":voice.id,"sha256":voice.sha256,
                   "in_frame":12,"out_frame":24,"source_in_s":0,"source_out_s":.5,"gain":.5}]
        captions=[{"id":"cap1","text":"Own copy","start_frame":6,"end_frame":18}]
    out = CompositionService(db, artifacts, root / "compositions").compile(
        "comp-local","exp-local","A","plan-local",segments,captions,clock,now=utcnow())
    if out["diagnostics"]:
        raise RuntimeError(str(out["diagnostics"]))
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
        assert video["width"] == 360 and video["height"] == 640 and int(video["nb_frames"]) == expected_frames
        if rich:
            def pixel(frame):
                r=subprocess.run(["ffmpeg","-v","error","-i",str(final),"-vf",f"select=eq(n\\,{frame}),crop=2:2:40:40",
                                  "-frames:v","1","-f","rawvideo","-pix_fmt","rgb24","pipe:1"],capture_output=True,check=True)
                return list(r.stdout[:3])
            first,blend,last=pixel(0),pixel(26),pixel(40)
            assert first[2]>200 and first[0]<30,first
            assert blend[1]>10 and blend[2]>10,blend
            assert last[1]>200 and last[2]<30,last
            samples=pcm.decode(final,48000)
            silent=pcm.measure(samples[:18000],48000)
            active=pcm.measure(samples[28000:42000],48000)
            assert silent["peak_dbfs"] is None or silent["peak_dbfs"] < -60
            assert active["rms_dbfs"] > -30
            evidence["timeline_checks"]={"source_offset_pixel":first,"crossfade_pixel":blend,"still_pixel":last,
                                          "delayed_audio":active,"initial_silence":silent}
        evidence["status"] = "passed"
        print(json.dumps({"status": "passed", "frames": expected_frames, "hosted_requests": 0}), flush=True)
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
    parser.add_argument("--rich",action="store_true")
    args=parser.parse_args()
    qualify(args.root,args.rich)
