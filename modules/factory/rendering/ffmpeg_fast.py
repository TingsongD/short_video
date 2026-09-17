"""FFmpeg fast-path renderer (F23): static compositions render
locally, section by section, with verified cached intermediates.

Reuses the proven fast_render recipes: fps+trim normalization with
post-verification, concat with exact durations, libass captions,
amix+alimiter audio, atomic finalize. Every section output is keyed by
its complete input/settings hash — an interrupted render resumes from
cached sections, never re-encodes them.
"""
import hashlib
import json
import shlex
import subprocess
import time
from pathlib import Path


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _ass_time(frame, fps=30):
    cs = frame * 100 // fps
    seconds, fraction = divmod(cs, 100)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02}:{seconds:02}.{fraction:02}"


def _literal(text):
    if any(c in text for c in ("\\", "{", "}", "\n", "\r")):
        raise ValueError("caption has unsupported ASS control chars")
    return text


ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,Times New Roman,54,&H00FFFFFF,&H00FFFFFF,&H20000000,0,0,0,0,100,100,0,0,1,0.6,2,8,86,86,0,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def captions_ass(captions, fps=30):
    events = [f"Dialogue: 0,{_ass_time(c['start_frame'], fps)},"
              f"{_ass_time(c['end_frame'], fps)},Caption,,0,0,0,,"
              + "{\\pos(540,1306)}" + _literal(c["text"])
              for c in sorted(captions, key=lambda c: c["start_frame"])]
    return ASS_HEADER + "\n".join(events) + "\n"


class RenderTimeout(Exception):
    """Observer-side timeout: the remote/local work state is UNKNOWN,
    not failed — the build may still be running."""


class FastPathRenderer:
    """Renders a compiled composition to a verified local final."""

    def __init__(self, runner=None, timeout=120):
        self.runner = runner or self._run
        self.timeout = timeout

    @staticmethod
    def _run(argv, timeout=120, cwd=None):
        return subprocess.run(argv, capture_output=True, text=True,
                              timeout=timeout, cwd=cwd)

    # ----------------------------------------------------- sections --

    def normalize_section(self, src, frames, fps, cache_dir):
        """Normalize one picture input to the target clock and EXACT
        frame count, keyed by (source sha, frames, fps). Post-verified:
        a source that cannot cover its allocation refuses, never pads."""
        info = next(s for s in probe_path(self.runner, src)["streams"]
                    if s["codec_type"] == "video")
        exact = (info.get("avg_frame_rate") == f"{fps}/1"
                 and int(info.get("nb_frames", 0)) == frames)
        identity = f"{_digest(src)[:16]}-{frames}@{fps}"
        out = cache_dir / f"{identity}.mp4"
        receipt = cache_dir / f"{identity}.json"
        if exact:
            return out, src
        if out.exists() and receipt.exists() and \
                json.loads(receipt.read_text()).get("sha256") == \
                _digest(out):
            return out, None          # cached verified intermediate
        tmp = out.with_suffix(".pending.mp4")
        r = self.runner(
            ["ffmpeg", "-v", "error", "-y", "-i", str(src), "-an",
             "-vf", f"fps={fps},trim=end_frame={frames},"
                    "setpts=N/(30*TB),setsar=1",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
             "-threads", "2", "-pix_fmt", "yuv420p", str(tmp)],
            timeout=self.timeout)
        if r.returncode != 0:
            raise RuntimeError(f"normalize failed: {r.stderr[-200:]}")
        pic = next(s for s in probe_path(self.runner, tmp)["streams"]
                   if s["codec_type"] == "video")
        if int(pic.get("nb_frames", 0)) < frames:
            raise RuntimeError(
                f"short_footage: source cannot cover {frames} frames")
        tmp.replace(out)
        receipt.write_text(json.dumps(
            {"sha256": _digest(out), "source_sha256": _digest(src),
             "frames": frames, "fps": fps}))
        return out, None

    # -------------------------------------------------------- render --

    def render(self, workspace, segments, captions, audio, clock,
               final_name="final.mp4", progress=None, on_progress=None):
        """segments: picture bindings in shot order
        [{src,frames}], audio: [{src,gain}], captions: ASS items.
        Returns the finalized path. Interrupted runs resume from
        verified cached sections; the concat encode reruns (it is the
        cheap deterministic tail)."""
        fps = clock["fps"]
        ws = Path(workspace)
        cache = ws / "render-inputs"
        cache.mkdir(parents=True, exist_ok=True)
        progress = progress if progress is not None else \
            {"completed_sections": [], "current": None}
        inputs = []
        for i, seg in enumerate(segments):
            progress["current"] = seg.get("id", f"seg{i}")
            progress["updated_at"] = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            (ws / "progress.json").write_text(json.dumps(progress))
            out, passthrough = self.normalize_section(
                seg["src"], seg["frames"], fps, cache)
            inputs.append((passthrough or out, seg["frames"]))
            progress["completed_sections"].append(seg.get("id", f"seg{i}"))
            progress["updated_at"] = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            (ws / "progress.json").write_text(json.dumps(progress))
            if on_progress:
                on_progress(dict(progress))
        # concat in exact shot order with per-segment durations
        concat = ws / "concat.txt"
        concat.write_text("".join(
            f"file '{Path(p).resolve()}'\n"
            f"duration {frames / fps:.12f}\n"
            for p, frames in inputs))
        ass = ws / "captions.ass"
        ass.write_text(captions_ass(captions, fps))
        total = sum(f for _, f in inputs)
        tmp = ws / (final_name + ".pending.mp4")
        audio_args, filter_a = [], ""
        for i, a in enumerate(audio or []):
            audio_args += ["-i", str(a["src"])]
            filter_a += (f"[{i+1}:a]volume={a.get('gain', 1.0)}[a{i}];")
        if audio:
            mix_in = "".join(f"[a{i}]" for i in range(len(audio)))
            filter_a += (f"{mix_in}amix=inputs={len(audio)}"
                         ":duration=first:normalize=0,"
                         "alimiter=limit=0.95:level=false[aout]")
        else:
            filter_a += "anullsrc=r=48000:cl=mono[aout]"
        vf = (f"[0:v]setpts=N/({fps}*TB),scale={clock['width']}:"
              f"{clock['height']}:flags=bicubic,setsar=1"
              + (",subtitles=captions.ass" if captions else "")
              + "[v]")
        argv = (["ffmpeg", "-v", "error", "-y", "-copyts",
                 "-f", "concat", "-safe", "0", "-i", "concat.txt"]
                + audio_args +
                ["-filter_complex_threads", "2", "-filter_complex",
                 vf + ";" + filter_a,
                 "-map", "[v]", "-map", "[aout]",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                 "-threads", "4", "-pix_fmt", "yuv420p",
                 "-r", str(fps), "-fps_mode", "cfr",
                 "-c:a", "aac", "-b:a", "192k",
                 "-t", f"{total / fps:.6f}",
                 "-movflags", "+faststart", tmp.name])
        try:
            r = self.runner(argv, timeout=self.timeout * 5, cwd=ws)
        except subprocess.TimeoutExpired:
            raise RenderTimeout("observer timeout; build state unknown")
        if r.returncode != 0:
            raise RuntimeError(f"render failed: {r.stderr[-300:]}")
        final = ws / final_name
        tmp.replace(final)
        progress["current"] = "finalized"
        progress["updated_at"] = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        (ws / "progress.json").write_text(json.dumps(progress))
        return final


def probe_path(runner, path):
    """ffprobe through the injectable runner so tests can fake it."""
    r = runner(["ffprobe", "-v", "error", "-print_format", "json",
                "-show_streams", "-show_format", str(path)],
               timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"probe failed: {r.stderr[-200:]}")
    return json.loads(r.stdout)
