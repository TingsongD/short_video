"""Prepare cached, zero-fee review evidence; never approve an artifact automatically.

Run with vendor/speech-qc/.venv/bin/python. One cached local Whisper model serves
the entire ready batch. No model downloads, paid APIs, or generation requests.
"""
import argparse
import difflib
import json
import math
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.batch.picture import timing_points
from modules.batch.state import digest, now, read, write


def tokens(words):
    return [re.sub(r"[^a-z0-9]", "", w["text"].lower()) for w in words]


def comparison(reference, generated, target, native):
    a, b = tokens(reference), tokens(generated)
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    pairs, differences = [], []
    for kind, i, j, k, l in matcher.get_opcodes():
        if kind == "equal":
            pairs.extend({"word": x["text"], "generated_word": y["text"], "reference_start": x["start"],
                          "reference_end": x["end"], "generated_start": y["start"], "generated_end": y["end"]}
                         for x, y in zip(reference[i:j], generated[k:l], strict=True))
        else:
            differences.append({"reference": reference[i:j], "generated": generated[k:l]})
    result = {"same_transcript": False, "asr_normalized_equal": a == b and bool(a), "pairs": pairs,
              "differences": differences, "similarity": matcher.ratio(),
              "limits": "ASR evidence only. Inspect actual picture and speech before setting same_transcript or accepting a timing edit."}
    if result["asr_normalized_equal"]:
        try:
            result["candidate_timing_points"] = timing_points(pairs, target, native)
        except Exception as error:
            result["timing_attention"] = str(error)
    return result


def run(argv):
    subprocess.run(list(map(str, argv)), check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=180)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    parser.add_argument("keys", nargs="+")
    args = parser.parse_args()
    folder = args.folder.resolve()
    state = read(folder.parent.parent / "batch-plan/run-state.json")
    number = str(int(folder.name.split("-")[-1]))
    v, brief = state["videos"][number], read(folder / "brief.json")
    output = folder / "review/pack"
    output.mkdir(parents=True, exist_ok=True)
    model = None
    def transcribe(source, receipt):
        nonlocal model
        sha = digest(source)
        if receipt.exists():
            cached = read(receipt)
            if cached.get("sha256") == sha and cached.get("model") == "small.en":
                return cached["words"]
        if model is None:
            from faster_whisper import WhisperModel
            model = WhisperModel("small.en", device="cpu", compute_type="int8", cpu_threads=4, local_files_only=True)
        segments, _ = model.transcribe(str(source), language="en", beam_size=5, word_timestamps=True,
                                       condition_on_previous_text=False)
        words = [{"text": w.word.strip(), "start": w.start, "end": w.end} for s in segments for w in (s.words or [])]
        write(receipt, {"sha256": sha, "model": "small.en", "words": words})
        return words
    for key in args.keys:
        job = v["jobs"][key]
        if job["stage"] != "downloaded":
            raise RuntimeError("Review evidence needs a downloaded artifact")
        source = folder / job["file"]
        if digest(source) != job["sha256"]:
            raise RuntimeError("Native artifact hash changed")
        inputs = {"source": job["sha256"], "brief": digest(folder / "brief.json"), "tool": digest(Path(__file__))}
        receipt = output / (key + ".json")
        if job["kind"] == "video":
            take = next(t for t in brief["takes"] if t["id"] == job.get("replacement_for", key))
            speech = folder / "audio" / (take["id"] + ".wav")
            inputs["speech"] = digest(speech)
        else:
            slot = int(job.get("replacement_for", key).split("-")[1])
            product = next(p for p in brief["products"] if p["slot"] == slot)
            reference = Path(product["reference_path"])
            inputs["reference"] = digest(reference)
        cached = read(receipt) if receipt.exists() else {}
        if (cached.get("inputs") == inputs and cached.get("grid")
                and Path(cached["grid"]).is_file()
                and (job["kind"] != "video" or (output / (key + "-timing-candidate.json")).is_file())):
            print(json.dumps({"key": key, "cached": True, "report": str(receipt)}), flush=True)
            continue
        started = now()
        report = {"key": key, "inputs": inputs, "started_at": started, "verdict": "requires_agent_review", "paid_requests": 0}
        grid = output / (key + "-native.jpg")
        if job["kind"] == "video":
            duration = float(job["probe"]["format"]["duration"])
            rows = max(1, math.ceil(duration * 2 / 6))
            run(["ffmpeg", "-v", "error", "-y", "-i", source, "-vf", f"fps=2,scale=240:426,tile=6x{rows}", "-frames:v", "1", grid])
            ref_words = transcribe(speech, output / (key + "-reference-asr.json"))
            gen_words = transcribe(source, output / (key + "-native-asr.json"))
            report["speech"] = comparison(ref_words, gen_words, (take["end_frame"]-take["start_frame"])/30, duration)
            report["approved_copy"] = take["text"]
            report["reference_asr"] = " ".join(w["text"] for w in ref_words)
            report["generated_asr"] = " ".join(w["text"] for w in gen_words)
            write(output / (key + "-timing-candidate.json"), report["speech"])
        else:
            run(["ffmpeg", "-v", "error", "-y", "-i", reference, "-i", source,
                 "-filter_complex", "[0:v]scale=-1:900[a];[1:v]scale=-1:900[b];[a][b]hstack[out]",
                 "-map", "[out]", "-frames:v", "1", grid])
            report.update(product=product["label"], reference_sha256=digest(reference))
        report.update(grid=str(grid), completed_at=now())
        write(receipt, report)
        print(json.dumps({"key": key, "report": str(receipt), "grid": str(grid),
                          "speech_equal": report.get("speech", {}).get("asr_normalized_equal"),
                          "differences": len(report.get("speech", {}).get("differences", []))}), flush=True)


if __name__ == "__main__":
    main()
