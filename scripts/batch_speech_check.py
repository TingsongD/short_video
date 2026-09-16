"""Optional zero-fee local speech evidence; run with vendor/speech-qc/.venv/bin/python.

Install faster-whisper==1.2.1 in that isolated Python 3.12 environment. Downloads
the public base.en model once; subsequent checks are local. Never auto-approves
visual mouth synchronization or the finished film.
"""
import argparse
import difflib
import json
import re
from pathlib import Path


def tokens(text):
    text = re.sub(r"(?i)miss\s*dress(?:ly|y)|mistressly|msdressly", "msdressly", text)
    return re.findall(r"[a-z0-9]+", text.lower().replace("'", ""))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("audio")
    p.add_argument("--expected-text-file", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--model", choices=("base.en", "small.en"), default="base.en")
    args = p.parse_args()
    from faster_whisper import WhisperModel
    model = WhisperModel(args.model, device="cpu", compute_type="int8", cpu_threads=4)
    parts, info = model.transcribe(args.audio, language="en", beam_size=5, word_timestamps=True,
                                   condition_on_previous_text=False)
    parts = list(parts)
    actual = " ".join(s.text.strip() for s in parts)
    expected = Path(args.expected_text_file).read_text()
    matcher = difflib.SequenceMatcher(None, tokens(expected), tokens(actual), autojunk=False)
    doc = {"model": "faster-whisper/" + args.model, "provider_spend": 0, "duration": info.duration,
           "transcript": actual, "text_similarity": matcher.ratio(),
           "words": [{"text": w.word.strip(), "start": w.start, "end": w.end} for s in parts for w in (s.words or [])],
           "limits": "Local ASR evidence only; visually inspect mouth timing and all final captions."}
    Path(args.output).write_text(json.dumps(doc, indent=2) + "\n")
    print(json.dumps({"duration": doc["duration"], "text_similarity": doc["text_similarity"], "transcript": actual}))


if __name__ == "__main__":
    main()
