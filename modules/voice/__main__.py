"""CLI: python -m modules.voice <shot_list.json>
Synthesizes voice.mp3 next to the shot list. Needs ELEVENLABS_API_KEY and a
pinned voice_id in config/system.toml (Wave 3 spend)."""
import argparse
import json
import sys
from pathlib import Path

from modules.common.config import secrets, system

from .tts import ElevenLabsTTS, duration_ok


def main(argv=None):
    p = argparse.ArgumentParser(description="M7 Voice — ElevenLabs TTS")
    p.add_argument("shot_list")
    p.add_argument("--out", help="output mp3 path (default: <dir>/voice.mp3)")
    args = p.parse_args(argv)

    sl_path = Path(args.shot_list)
    doc = json.loads(sl_path.read_text())
    cfg = system()["voice"]
    sec = secrets()

    tts = ElevenLabsTTS(
        api_key=sec.get("ELEVENLABS_API_KEY", ""),
        voice_id=cfg.get("voice_id", ""),
        model=cfg.get("model", "eleven_v3"),
    )
    out = Path(args.out) if args.out else sl_path.parent / "voice.mp3"
    tts.synthesize(doc["voice_text"], out)
    ok = duration_ok(out, cfg["min_duration_s"], cfg["max_duration_s"])
    print(f"voice: {out} duration_ok={ok}")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
