"""M8 batch runner: invoke vendored MoneyPrinterTurbo CLI on a batch manifest.
The command runs inside vendor/MoneyPrinterTurbo via uv; logs go to logs/.
`runner` is injectable so tests never execute the CLI."""
import subprocess
import sys
from pathlib import Path

from modules.common.config import ROOT

MPT_DIR = ROOT / "vendor" / "MoneyPrinterTurbo"
LOGS = ROOT / "logs"


def build_command(batch_path):
    return [
        "uv", "run", "python", "cli.py",
        "--batch-file", str(Path(batch_path).resolve()),
    ]


def run_batch(batch_path, log_name="assemble", runner=subprocess.run):
    cmd = build_command(batch_path)
    LOGS.mkdir(exist_ok=True)
    log_path = LOGS / f"{log_name}-{Path(batch_path).stem}.log"
    with open(log_path, "w", encoding="utf-8") as lf:
        result = runner(
            cmd, cwd=MPT_DIR, stdout=lf, stderr=subprocess.STDOUT,
            text=True, timeout=3600,
        )
    return {"returncode": result.returncode, "log": str(log_path), "cmd": cmd}
