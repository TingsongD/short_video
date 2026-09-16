import argparse
import json

from modules.assets.canvas_cli import CanvasError
from .local import Drive, Local
from .runner import DEFAULT, PREVIOUS, Runner, record_review, repair
from .state import Batch, Pause, ReviewReady, digest, exclusive, read, write


def main():
    parser = argparse.ArgumentParser(description="Sequential MsDressly video production; resumes saved jobs")
    parser.add_argument("--selection-dir", default=str(DEFAULT))
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "run", "dry-run"):
        sub.add_parser(name)
    configure = sub.add_parser("configure")
    configure.add_argument("--jimeng-concurrency", type=int, required=True)
    configure.add_argument("--render-backend", choices=("hypit", "ffmpeg"), required=True)
    evidence = sub.add_parser("review-pack")
    evidence.add_argument("keys", nargs="*")
    balance = sub.add_parser("balance")
    balance.add_argument("credits", type=int)
    balance.add_argument("--evidence", required=True)
    review = sub.add_parser("review")
    review.add_argument("key")
    review.add_argument("--verdict", choices=("passed", "failed"), required=True)
    review.add_argument("--notes", required=True)
    fix = sub.add_parser("repair")
    fix.add_argument("key")
    fix.add_argument("--prompt-file", required=True)
    picture = sub.add_parser("fit-picture")
    picture.add_argument("key")
    picture.add_argument("--comparison", required=True)
    args = parser.parse_args()
    if args.command == "status":
        # Atomic state files permit read-only status while a controller owns the lock.
        batch = Batch(args.selection_dir)
        n = batch.active_number()
        print(json.dumps({"status": batch.data["status"], "active": n,
            "jimeng_reserved_for_submissions": batch.spent(), "cap": batch.data["approval"]["jimeng"],
            "execution": batch.data.get("execution", {}), "pause_reason": batch.data.get("pause_reason"),
            "videos": [{"number": v["number"], "state": v["state"], "review_required": v.get("review_required"),
                        "review_queue": v.get("review_queue", []), "delivery": v.get("delivery", {}).get("web_url")}
                       for v in batch.data["videos"].values()]}, indent=2))
        return 0
    try:
        with exclusive(__import__("pathlib").Path(args.selection_dir) / "batch-plan"):
            batch = Batch(args.selection_dir)
            n = batch.active_number()
            if args.command == "configure":
                batch.configure(args.jimeng_concurrency, args.render_backend)
                print("Execution settings saved; credit ceilings and one-video-at-a-time delivery are unchanged.")
            elif args.command == "review-pack":
                from .runner import ROOT
                if n is None:
                    raise Pause("All videos are complete; no active artifacts to review")
                keys = args.keys or batch.video(n).get("review_queue", [])
                if not keys:
                    raise Pause("No ready artifacts to prepare")
                local = Local(batch.directory(n))
                print(local.run([ROOT / "vendor/speech-qc/.venv/bin/python", ROOT / "scripts/batch_review_pack.py",
                                 batch.directory(n), *keys], timeout=600))
            elif args.command == "balance":
                batch.record_balance(args.credits, args.evidence)
                print("Observed balance recorded; the original batch cap remains unchanged.")
            elif args.command == "review":
                record_review(batch, n, args.key, args.verdict, args.notes)
                print("Inspection recorded for this exact artifact.")
            elif args.command == "repair":
                from pathlib import Path
                repair(batch, n, args.key, Path(args.prompt_file).read_text())
                print("Correction prepared and quoted within the reserved allowance.")
            elif args.command == "fit-picture":
                from .picture import fit_picture
                result = fit_picture(batch, n, args.key, args.comparison)
                print(json.dumps({"file": result["file"], "frames": result["frames"], "max_anchor_residual_s": result["max_anchor_residual_s"], "paid_calls": 0}))
            elif args.command == "dry-run":
                local = Local(batch.folder / "dry-run")
                receipt = read(PREVIOUS / "drive-delivery/upload-receipt.json")
                final = PREVIOUS / receipt["source_file"]
                remote = Drive(local, receipt["folder_id"]).info(receipt["drive_file_id"])
                checks = [digest(final) == receipt["sha256"], digest(final, "md5") == remote.get("MD5"),
                          remote.get("Size") == str(final.stat().st_size), remote.get("Name") == receipt["delivery_name"],
                          receipt["folder_id"] in remote.get("Parents", "").split(", ")]
                cleanup = local.cleanup()
                if not all(checks) or cleanup["state"] != "verified":
                    raise Pause("Dry-run delivery or cleanup verification failed")
                write(batch.folder / "dry-run-evidence.json", {"passed": True, "paid_requests": 0, "uploads": 0,
                      "existing_drive_file": receipt["drive_file_id"], "sha256": digest(final), "cleanup": cleanup})
                print("Dry run passed: existing final verified in Drive, zero generation, zero uploads, cleanup verified.")
            else:
                while n is not None:
                    Runner(batch, n).run()
                    n = batch.active_number()
                batch.data["status"] = "complete"
                batch.save()
                print("All selected videos delivered and cleaned.")
    except ReviewReady as error:
        print(json.dumps({"status": "review_ready", "reason": str(error), "resume_immediately_after_review": True}))
        return 3
    except (Pause, CanvasError) as error:
        print(json.dumps({"status": "paused", "reason": str(error)}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
