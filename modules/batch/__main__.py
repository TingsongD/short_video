import argparse
import json

from modules.assets.canvas_cli import CanvasError
from .local import Drive, Local
from .runner import DEFAULT, PREVIOUS, Runner, record_review, repair
from .state import Batch, Pause, digest, exclusive, read, write


def main():
    parser = argparse.ArgumentParser(description="Sequential MsDressly video production; resumes saved jobs")
    parser.add_argument("--selection-dir", default=str(DEFAULT))
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "run", "dry-run"):
        sub.add_parser(name)
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
    try:
        with exclusive(__import__("pathlib").Path(args.selection_dir) / "batch-plan"):
            batch = Batch(args.selection_dir)
            n = batch.active_number()
            if args.command == "status":
                print(json.dumps({"status": batch.data["status"], "active": n, "jimeng_reserved_for_submissions": batch.spent(),
                      "pause_reason": batch.data.get("pause_reason"),
                      "cap": batch.data["approval"]["jimeng"], "videos": [{"number": v["number"], "state": v["state"],
                      "review_required": v.get("review_required"), "delivery": v.get("delivery", {}).get("web_url")}
                      for v in batch.data["videos"].values()]}, indent=2))
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
    except (Pause, CanvasError) as error:
        print(json.dumps({"status": "paused", "reason": str(error)}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
