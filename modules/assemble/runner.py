"""Run MPT and retrieve only finals explicitly returned by its JSON result."""
import json
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

from modules.common.config import ROOT
from .qc import probe_full

MPT_DIR = ROOT / "vendor" / "MoneyPrinterTurbo"
LOGS = ROOT / "logs"


def build_command(batch_path):
    return ["uv", "run", "--frozen", "--no-sync", "python",
            str(Path(__file__).with_name("mpt_local.py").resolve()),
            "--batch-file", str(Path(batch_path).resolve())]


def parse_result(raw, expected_tasks):
    try:
        data = json.loads(raw)
        tasks = data["tasks"]
        if (data["total"] != expected_tasks or data["succeeded"] != expected_tasks
                or data["failed"] != 0 or len(tasks) != expected_tasks
                or {t["index"] for t in tasks} != set(range(1, expected_tasks + 1))):
            raise ValueError()
        finals = []
        for task in sorted(tasks, key=lambda t: t["index"]):
            if task["status"] != "succeeded" or task.get("error") or task.get("failed_stage"):
                raise ValueError()
            videos = task["result"]["videos"]
            if not isinstance(videos, list) or len(videos) != 1:
                raise ValueError()
            path = Path(videos[0])
            if not path.is_absolute() or path.suffix.lower() != ".mp4":
                raise ValueError()
            finals.append(path)
        if len(set(finals)) != len(finals):
            raise ValueError()
        return finals
    except (ValueError, TypeError, KeyError, IndexError):
        raise RuntimeError("MPT returned failed or malformed results; no final accepted") from None


def run_batch(batch_path, log_name="assemble", runner=None, output_dir=None):
    runner = runner or subprocess.run
    batch_path = Path(batch_path).resolve()
    batch = json.loads(batch_path.read_text())
    if not isinstance(batch, list) or not batch:
        raise ValueError("MPT batch must contain tasks")
    if output_dir is not None and len(batch) != 1:
        raise ValueError("a production output folder requires exactly one task")
    cmd = build_command(batch_path)
    LOGS.mkdir(exist_ok=True)
    log_path = LOGS / f"{log_name}-{uuid4().hex}.log"
    with log_path.open("w", encoding="utf-8") as log:
        result = runner(cmd, cwd=MPT_DIR, stdout=subprocess.PIPE, stderr=log,
                        text=True, timeout=3600)
    if result.returncode:
        raise RuntimeError(f"MPT failed (exit {result.returncode}); see {log_path}")
    sources = parse_result(getattr(result, "stdout", ""), len(batch))
    for path in sources:
        info = probe_full(path)
        kinds = {s.get("codec_type") for s in info.get("streams", [])}
        if not {"audio", "video"} <= kinds:
            raise RuntimeError("MPT final is missing video or audio")
    finals = sources
    if output_dir is not None:
        directory = Path(output_dir).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        finals = []
        for idx, src in enumerate(sources, 1):
            dest = directory / f"final-{idx}.mp4"
            if src.resolve() != dest.resolve():
                temp = dest.with_suffix(".part.mp4")
                shutil.copyfile(src, temp)
                temp.replace(dest)
            finals.append(dest)
    return {"returncode": 0, "log": str(log_path), "cmd": cmd,
            "finals": [str(p) for p in finals], "source_finals": [str(p) for p in sources]}
