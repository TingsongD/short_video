"""Repository-owned entrypoint for the pinned WhisperX serviceCommand.

Run with the existing managed WhisperX environment, preserving its installation.
The installed engine supplies STT/alignment; our extension adds pyannote turns.
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
        from hypit_whisperx_service.config import ServiceConfig
        from hypit_whisperx_service.engine import WhisperXEngine
        from hypit_whisperx_service.application import WhisperXApplication
        from hypit_whisperx_service.server import serve
        from modules.factory.analysis.whisperx_speakers import SpeakerEngine
        config = ServiceConfig.from_environment()
        serve(WhisperXApplication(config, SpeakerEngine(WhisperXEngine(config), ROOT)))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        # The configured handler already recorded a sanitized traceback; do
        # not let Python print its raw exception into the runtime launcher log.
        sys.exit(1)
