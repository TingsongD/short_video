"""ElevenLabs v3 segments; alignment follows the exact local time transform."""
import base64
import hashlib
import json
import re
import urllib.request
from pathlib import Path

from modules.common.config import secrets
from .local import probe
from .state import Pause, digest, read, write

VOICE = "cgSgspJ2msm6clMCkdW9"


def compact_intervals(duration, silence):
    """Retain short natural pauses and speech; return source-time intervals to keep."""
    removed = []
    for start, end in silence:
        if end - start <= .20:
            continue
        a = 0. if start < .05 else start + .055
        b = duration if end >= duration - .02 else end - .055
        if b > a:
            removed.append((a, b))
    cursor, kept = 0., []
    for a, b in sorted(removed):
        if a > cursor:
            kept.append((cursor, a))
        cursor = max(cursor, b)
    if cursor < duration:
        kept.append((cursor, duration))
    return kept


def compact_time(t, intervals):
    return sum(max(0., min(t, end) - start) for start, end in intervals if t > start)


def word_times(alignment, trim_start, tempo, offset, limit, intervals=None):
    chars = alignment["characters"]
    starts, ends = alignment["character_start_times_seconds"], alignment["character_end_times_seconds"]
    if not (len(chars) == len(starts) == len(ends)):
        raise Pause("Malformed narration alignment")
    text = "".join(chars)
    result = []
    for m in re.finditer(r"\S+", text):
        a, b = starts[m.start()], ends[m.end() - 1]
        start = max(0., (compact_time(a, intervals) if intervals is not None else a - trim_start) / tempo)
        end = (compact_time(b, intervals) if intervals is not None else b - trim_start) / tempo
        if end <= 0:
            continue
        if end > limit + .07:
            raise Pause("Spoken words exceed their assigned timeline")
        result.append({"text": m.group(), "start": offset + start,
                       "end": offset + min(end, limit), "type": "word"})
    return result


class Audio:
    def __init__(self, batch, number, local):
        self.batch, self.number, self.local = batch, number, local
        self.v = batch.video(number)
        self.folder = batch.directory(number) / "audio"
        self.folder.mkdir(exist_ok=True)

    def generate(self, take, defer_fit=False):
        key, text = take["id"], take["text"]
        raw, alignment_file = self.folder / (key + ".mp3"), self.folder / (key + "-alignment.json")
        fitted = self.folder / (key + ".wav")
        receipt = self.v["tts_jobs"].get(key)
        if receipt:
            if receipt["text_sha256"] != hashlib.sha256(text.encode()).hexdigest():
                raise Pause("Narration copy changed after spending; keep accepted audio or explicitly revise")
            if not defer_fit and receipt.get("state") == "fitted" and fitted.exists() and digest(fitted) == receipt["sha256"]:
                return fitted, read(self.folder / (key + "-words.json"))
            response_file = self.folder / (key + "-response.json")
            if response_file.exists() and (not raw.exists() or not alignment_file.exists()):
                response = read(response_file)
                raw.write_bytes(base64.b64decode(response.pop("audio_base64"), validate=True))
                write(alignment_file, response)
            if not raw.exists() or not alignment_file.exists():
                raise Pause("TTS response is incomplete/ambiguous; inspect the saved request, never repeat it automatically")
        else:
            cfg = secrets()
            key_value = cfg.get("ELEVENLABS_API_KEY")
            if not key_value:
                raise Pause("ElevenLabs credential is unavailable")
            # Included allowance only; do not silently enter overage billing.
            request = urllib.request.Request("https://api.elevenlabs.io/v1/user/subscription", headers={"xi-api-key": key_value})
            with urllib.request.urlopen(request, timeout=40) as response:
                subscription = json.load(response)
            remaining = subscription["character_limit"] - subscription["character_count"]
            if remaining < len(text):
                raise Pause("ElevenLabs included credit balance is insufficient")
            self.batch.claim_tts(self.number, key, text)
            payload = {"text": text, "model_id": "eleven_v3", "language_code": "en",
                       "voice_settings": {"stability": .5, "similarity_boost": .75, "speed": 1.2}, "seed": 260915 + self.number}
            request = urllib.request.Request(f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE}/with-timestamps?output_format=mp3_44100_128",
                    data=json.dumps(payload).encode(), headers={"xi-api-key": key_value, "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(request, timeout=180) as response:
                    doc = json.load(response)
                    actual = response.headers.get("x-character-count")
                    request_id = response.headers.get("request-id")
                audio = base64.b64decode(doc.pop("audio_base64"), validate=True)
                if len(audio) < 1000 or not doc.get("alignment"):
                    raise ValueError()
                # Atomic response receipt first, so a crash can recover the audio without another POST.
                write(self.folder / (key + "-response.json"), {"audio_base64": base64.b64encode(audio).decode(), **doc})
                raw.write_bytes(audio)
                write(alignment_file, doc)
                receipt = self.v["tts_jobs"][key]
                receipt.update(state="received", request_id=request_id, actual_credits=actual)
                if actual and int(actual) > receipt["reserved_credits"]:
                    raise Pause("Provider billed more narration credits than reserved; reconcile before continuing")
                self.batch.save()
            except Pause:
                raise
            except Exception:
                raise Pause("TTS request failed or its response is ambiguous; no automatic repeat") from None
        alignment = read(alignment_file)["alignment"]
        text_actual = "".join(alignment["characters"])
        if re.sub(r"\W", "", text_actual).lower() != re.sub(r"\W", "", text).lower():
            raise Pause("TTS alignment text differs from approved copy; review before fitting")
        raw_duration = float(probe(self.local, raw)["format"]["duration"])
        detection = self.local.run(["ffmpeg", "-hide_banner", "-i", raw, "-af", "silencedetect=noise=-40dB:d=0.18", "-f", "null", "-"], stderr_output=True)
        silence, silence_start = [], None
        for match in re.finditer(r"silence_(start|end):\s*([\d.]+)", detection):
            if match.group(1) == "start":
                silence_start = float(match.group(2))
            elif silence_start is not None:
                silence.append((silence_start, float(match.group(2))))
                silence_start = None
        intervals = compact_intervals(raw_duration, silence)
        if not intervals:
            raise Pause("Narration contains no usable speech")
        compact_duration = sum(b-a for a,b in intervals)
        receipt = self.v["tts_jobs"][key]
        receipt["compact_seconds"] = compact_duration
        self.batch.save()
        if defer_fit:
            return raw, []
        target = (take["end_frame"] - take["start_frame"]) / 30
        tempo = max(.9, compact_duration / (target - .08))
        if tempo > 1.18:
            raise Pause(f"{key} speech is too long; review an intentional copy/audio correction")
        pieces = [f"[0:a]atrim=start={a}:end={b},asetpts=PTS-STARTPTS[s{i}]" for i,(a,b) in enumerate(intervals)]
        pieces.append("".join(f"[s{i}]" for i in range(len(intervals))) +
                      f"concat=n={len(intervals)}:v=0:a=1,atempo={tempo},apad,atrim=duration={target}[voice]")
        self.local.run(["ffmpeg", "-v", "error", "-y", "-i", raw, "-filter_complex", ";".join(pieces),
                        "-map", "[voice]", "-ar", "44100", "-ac", "1", "-c:a", "pcm_s16le", fitted])
        words = word_times(alignment, 0., tempo, take["start_frame"] / 30, target, intervals)
        write(self.folder / (key + "-words.json"), words)
        receipt = self.v["tts_jobs"][key]
        receipt.update(state="fitted", sha256=digest(fitted), kept_intervals=intervals, tempo=tempo, duration=target)
        self.batch.save()
        return fitted, words

    def finish(self, brief, music):
        # Measure all accepted performances before assigning their final shot lengths.
        # This avoids forcing a long sentence into half of an arbitrary equal split.
        for take in brief["takes"]:
            self.generate(take, defer_fit=True)
        weights = [self.v["tts_jobs"][t["id"]]["compact_seconds"] for t in brief["takes"]]
        total = sum(weights)
        if total / (169.7 - .08 * len(weights)) > 1.18:
            raise Pause("Whole narration is too long even after pause removal; review an intentional copy correction")
        cursor, cumulative = 0, 0.
        old_times = [{"id": t["id"], "start_frame": t["start_frame"], "end_frame": t["end_frame"]} for t in brief["takes"]]
        for take, weight in zip(brief["takes"], weights):
            cumulative += weight
            end = round(5091 * cumulative / total)
            if not 120 <= end - cursor <= 450:
                raise Pause("Measured performance needs a different shot split before generation")
            take.update(start_frame=cursor, end_frame=end)
            cursor = end
            self.v["tts_jobs"][take["id"]]["state"] = "received"  # re-fit locally; never synthesize again
        brief_path = self.folder.parent / "brief.json"
        write(brief_path, brief)
        self.v["brief_sha256"] = digest(brief_path)
        self.v.setdefault("timing_revisions", []).append({"basis": "Measured accepted speech after pause removal",
                          "before": old_times, "compact_seconds": total, "frames": 5091})
        self.batch.save()
        all_words, paths = [], []
        for take in brief["takes"]:
            path, words = self.generate(take)
            paths.append(path)
            all_words.extend(words)
        playlist = self.folder / "concat.txt"
        playlist.write_text("".join("file '" + p.name + "'\n" for p in paths))
        self.local.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", playlist,
                        "-c:a", "pcm_s16le", self.folder / "narration.wav"])
        duration = float(probe(self.local, self.folder / "narration.wav")["format"]["duration"])
        if abs(duration - 169.7) > .005:
            raise Pause("Measured narration does not match the complete timeline")
        import shutil
        shutil.copy2(music, self.folder / "music-bed.wav")
        write(self.folder / "words.json", all_words)
        write(self.folder / "audio-verification.json", {"duration": duration, "words": len(all_words),
              "sha256": digest(self.folder / "narration.wav"), "music_sha256": digest(music),
              "alignment_basis": "ElevenLabs character alignment transformed through exact trim and tempo"})
        self.v["state"] = "narration_ready"
        self.batch.save()
