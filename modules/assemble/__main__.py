"""CLI:
  python -m modules.assemble build <video_id>   — mpt_task.json from local artifacts
  python -m modules.assemble run <batch.json>   — invoke MPT CLI (real run)
  python -m modules.assemble qc <final.mp4> [--voice-s N]
"""
import argparse
import json
import sys
from pathlib import Path

from modules.common.config import DATA_DIR, system

from .qc import extract_frame, qc_video
from .runner import run_batch
from .task_builder import build_task, write_batch, write_task


def main(argv=None):
    p = argparse.ArgumentParser(description="M8 Assembly (MoneyPrinterTurbo)")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("video_id")
    b.add_argument("--subject", default="")
    r = sub.add_parser("run")
    r.add_argument("batch")
    q = sub.add_parser("qc")
    q.add_argument("video")
    q.add_argument("--voice-s", type=float, default=None)
    q.add_argument("--frame-at", type=float, default=1.0)
    args = p.parse_args(argv)

    if args.cmd == "build":
        d = DATA_DIR / "production" / args.video_id
        shot_list = json.loads((d / "shot_list.json").read_text())
        manifest = json.loads((d / "assets" / "manifest.json").read_text())
        task = build_task(args.video_id, shot_list, manifest,
                          system()["assembly"], args.subject)
        out = write_task(task, video_dir=d)
        print(f"mpt_task: {out}")
        return 0

    if args.cmd == "run":
        res = run_batch(args.batch)
        print(f"mpt exit={res['returncode']} log={res['log']}")
        return res["returncode"]

    cfg = system()["assembly"]
    w, h = (int(x) for x in cfg["resolution"].split("x"))
    ok, failures = qc_video(args.video, expected_res=(w, h),
                            voice_duration=args.voice_s)
    if ok:
        frame = extract_frame(args.video, at_s=args.frame_at)
        print(f"QC pass; subtitle spot-check frame: {frame}")
        return 0
    print("QC FAIL: " + "; ".join(failures), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
