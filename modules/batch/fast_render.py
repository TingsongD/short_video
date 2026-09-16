"""Native caption rendering for the haul's static typography; Hypit stays editable."""
import hashlib
import shutil
import time
from pathlib import Path

from .local import probe, verify_media
from .picture import selected_picture
from .state import Pause, digest, now, read, write


def ass_time(frame):
    # Floor centiseconds so the first sampled 30-fps frame is exactly `frame`.
    cs = frame * 100 // 30
    seconds, fraction = divmod(cs, 100)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02}:{seconds:02}.{fraction:02}"


def literal(text):
    # No HTML entities, ASS override injection, or unintended hard line breaks.
    if any(c in text for c in ("\\", "{", "}", "\n", "\r")):
        raise Pause("Caption contains unsupported ASS control characters")
    return text


def render_input(local, source, frames, cache):
    """Trim unused native tails and normalize frame rate before concatenating.

    Speech-fitted pictures already contain exactly their allocated 30-fps frames.
    Native Jimeng results can be 24 fps and rounded up to whole seconds; a concat
    duration alone does not discard those extra frames.
    """
    info = next(s for s in probe(local, source)["streams"] if s["codec_type"] == "video")
    if info["avg_frame_rate"] == "30/1" and int(info.get("nb_frames", 0)) == frames:
        return source
    cache.mkdir(exist_ok=True)
    identity = f"{digest(source)}-{frames}"
    output, receipt = cache / (identity + ".mp4"), cache / (identity + ".json")
    if output.exists() and receipt.exists() and digest(output) == read(receipt).get("sha256"):
        return output
    temp = output.with_suffix(".pending.mp4")
    local.run(["ffmpeg", "-v", "error", "-y", "-i", source, "-an", "-vf",
        f"fps=30,trim=end_frame={frames},setpts=N/(30*TB),setsar=1", "-c:v", "libx264",
        "-preset", "veryfast", "-crf", "18", "-threads", "2", "-pix_fmt", "yuv420p", temp], timeout=120)
    picture = next(s for s in probe(local, temp)["streams"] if s["codec_type"] == "video")
    if picture["avg_frame_rate"] != "30/1" or int(picture.get("nb_frames", 0)) != frames:
        raise Pause("Native picture cannot cover its allocated frame count")
    temp.replace(output)
    write(receipt, {"sha256": digest(output), "source_sha256": digest(source), "frames": frames})
    return output


def subtitles(brief, words):
    from .render import cues
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,Times New Roman,54,&H00FFFFFF,&H00FFFFFF,&H40000000,&H20000000,0,0,0,0,100,100,0,0,1,0.6,2,8,86,86,0,1
Style: Label,Times New Roman,54,&H00FFFFFF,&H00FFFFFF,&H40000000,&H20000000,0,-1,0,0,100,100,0,0,1,0.6,2,8,86,86,0,1
Style: Brand,Impact,200,&H00FFFFFF,&H00FFFFFF,&H40000000,&H20000000,0,0,0,0,100,100,0,0,1,0.6,2,7,97,43,0,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    def add(start, end, style, x, y, text):
        events.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},{style},,0,0,0,,"
                      + "{\\pos(" + f"{x},{y}" + ")}" + literal(text))
    for cue in cues(words):
        add(cue["start"], cue["end"], "Caption", 540, 1306, cue["text"])
    for product in brief["products"]:
        start = next(t["start_frame"] for t in brief["takes"] if t["slot"] == product["slot"]) + 14
        add(start, start + 70, "Label", 540, 1459, product["label"])
    for a, b, text in [(0, 3, "|"), (3, 6, "MS|"), (6, 9, "MSDR|"), (9, 12, "MSDRESS|"),
                       (12, 16, "MSDRESSLY|"), (16, 43, "MSDRESSLY")]:
        add(a, b, "Brand", 97, 925, text)
    return header + "\n".join(events) + "\n"


class FastRender:
    def __init__(self, batch, number, local, previous):
        self.batch, self.number, self.local, self.previous = batch, number, local, Path(previous)
        self.v, self.folder = batch.video(number), batch.directory(number)

    def finish(self, brief):
        from .render import author
        folder = self.folder
        for font in ("caption", "label", "headline"):
            shutil.copy2(self.previous / "assets" / (font + ".ttf"), folder / "assets" / (font + ".ttf"))
        (folder / "style.svs").write_text((self.previous / "style.svs").read_text().replace("text.label { size: 63;", "text.label { size: 48;"))
        write(folder / "package.json", {"name": f"msdressly-batch-haul-{self.number:02}", "private": True, "type": "module"})
        author(folder, brief, self.v)  # Preserve the editable Hypit project; paid requests are never needed here.
        content = subtitles(brief, read(folder / "audio/words.json"))
        (folder / "captions.ass").write_text(content)
        paths = [selected_picture(self.v, folder, self.v.get("selected_jobs", {}).get(t["id"], t["id"])) for t in brief["takes"]]
        inputs = {"version": 1, "implementation": digest(Path(__file__)), "captions": hashlib.sha256(content.encode()).hexdigest(),
                  "pictures": [digest(path) for path in paths], "voice": digest(folder / "audio/narration.wav"),
                  "music": digest(folder / "audio/music-bed.wav"),
                  "fonts": [digest(folder / "assets" / (f + ".ttf")) for f in ("caption", "label", "headline")]}
        receipt = folder / "fast-render.json"
        prior = read(receipt) if receipt.exists() else {}
        final = folder / brief["delivery_name"]
        if prior and prior.get("inputs") != inputs:
            raise Pause("Fast render inputs changed; preserve the existing render before an intentional revision")
        if prior.get("state") == "verified" and final.exists() and digest(final) == prior["sha256"]:
            self.v.update(state="rendered", final_path=str(final), technical_qc=read(folder / "technical-qc.json"))
            self.batch.save()
            return final
        def quote_path(path):
            return str(path.resolve()).replace("'", "'\\''")
        doc = {"state": "rendering", "started_at": now(), "inputs": inputs, "backend": "ffmpeg-libass"}
        write(receipt, doc)
        started = time.monotonic()
        paths = [render_input(self.local, path, take["end_frame"]-take["start_frame"], folder / "render-inputs")
                 for path, take in zip(paths, brief["takes"], strict=True)]
        (folder / "picture-concat.txt").write_text("".join(
            f"file '{quote_path(path)}'\nduration {(take['end_frame']-take['start_frame'])/30:.12f}\n"
            for path, take in zip(paths, brief["takes"], strict=True)))
        temp = folder / "final.pending.mp4"
        self.local.run(["ffmpeg", "-v", "error", "-y", "-copyts", "-f", "concat", "-safe", "0",
            "-i", "picture-concat.txt", "-i", "audio/narration.wav", "-i", "audio/music-bed.wav",
            "-filter_complex_threads", "2", "-filter_complex",
            "[0:v]setpts=N/(30*TB),scale=1080:1920:flags=bicubic,setsar=1,subtitles=captions.ass:fontsdir=assets[v];"
            "[1:a]volume=1.25[voice];[voice][2:a]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95:level=false[a]",
            "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-threads", "4", "-pix_fmt", "yuv420p", "-r", "30", "-fps_mode", "cfr", "-c:a", "aac", "-b:a", "192k",
            "-t", "169.7", "-movflags", "+faststart", temp], timeout=600)
        doc["encode_seconds"] = time.monotonic() - started
        report = verify_media(self.local, temp, "video", 169.7, final=True)
        temp.replace(final)
        report["probe"]["format"]["filename"] = str(final)
        doc.update(state="verified", completed_at=now(), sha256=digest(final), total_seconds=time.monotonic()-started)
        write(receipt, doc)
        write(folder / "technical-qc.json", report)
        self.v.update(state="rendered", final_path=str(final), technical_qc=report)
        self.batch.save()
        return final
