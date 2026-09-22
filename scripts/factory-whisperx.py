"""Repository-owned entrypoint for the pinned WhisperX serviceCommand.

Run with the existing managed WhisperX environment, preserving its installation.
Only startup/logging is wrapped; the provider protocol and engine are unchanged.
"""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    p = argparse.ArgumentParser()
    for name in ('port', 'model', 'device', 'compute', 'batch-size', 'nltk-data'):
        p.add_argument('--' + name, required=True)
    args = p.parse_args()
    os.umask(0o077)
    for key, value in vars(args).items():
        os.environ['HYPIT_WHISPERX_' + key.upper()] = value
    from modules.factory.diagnostics import console_logging
    folder = ROOT / '.run'; folder.mkdir(exist_ok=True)
    with console_logging(folder, 'whisperx'):
        from hypit_whisperx_service.__main__ import main as serve
        serve()


if __name__ == '__main__':
    try:
        main()
    except Exception:
        # The configured handler already recorded a sanitized traceback; do
        # not let Python print its raw exception into the runtime launcher log.
        sys.exit(1)
