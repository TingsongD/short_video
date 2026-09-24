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
from fractions import Fraction
from pathlib import Path

from ..audio import caption_style as style


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _ass_time(frame, fps=30):
    cs = int(frame * 100 // fps)
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
Style: Caption,{font},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,0,0,8,0,0,0,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def captions_ass(captions, fps=30, preset='words.v1', *, font_path=None):
    if preset not in ('words.v1', 'phrases.v1'):
        raise ValueError('unsupported caption preset')
    phrase = preset == 'phrases.v1'
    header = ASS_HEADER.format(font=style.caption_font(font_path).getname()[0] if captions else 'Arial',
                               size=f'{style.FONT_SIZE * 1080 / style.BASE_WIDTH:g}')

    def validate_text(text):
        if not phrase:
            _literal(text)
            return
        lines = text.split('\n')
        from ..audio.phrase_captions import fits_line
        if len(lines) > 2 or any(not line or not fits_line(line, font_path=font_path) for line in lines):
            raise ValueError('phrase caption exceeds readable layout')
        for line in lines:
            _literal(line)

    events = []
    scale = 1080 / style.BASE_WIDTH
    line_height = style.FONT_SIZE * style.LINE_HEIGHT * scale
    for c in sorted(captions, key=lambda c: c['start_frame']):
        validate_text(c['text'])  # Validate before emitting any ASS control data.
        lines = c['text'].split('\n')
        width = (max(style.line_width(line, font_path) for line in lines) + 2 * style.PAD_X) * scale
        height = len(lines) * line_height + 2 * style.PAD_Y * scale
        left, top = (1080 - width) / 2, style.BOTTOM * 1920 - height
        timing = f"{_ass_time(c['start_frame'], fps)},{_ass_time(c['end_frame'], fps)},Caption,,0,0,0,,"
        # One translucent rounded box avoids dark overlaps between line boxes.
        box = _rounded_box(width, height, style.RADIUS * scale)
        events.append('Dialogue: 0,' + timing +
                      f'{{\\an7\\pos({left:g},{top:g})\\1c&H000000&\\1a&H33&\\p1}}{box}{{\\p0}}')
        for index, line in enumerate(lines):
            y = top + style.PAD_Y * scale + index * line_height + (line_height - style.FONT_SIZE * scale) / 2
            events.append('Dialogue: 1,' + timing + f'{{\\pos(540,{y:g})}}' + _literal(line))
    return header + "\n".join(events) + "\n"


def _rounded_box(width, height, radius):
    """ASS vector path, independent of libass's platform-dependent box padding."""
    r = min(radius, width / 2, height / 2)
    k = r * .55228475
    return (f'm {r:g} 0 l {width-r:g} 0 '
            f'b {width-r+k:g} 0 {width:g} {r-k:g} {width:g} {r:g} '
            f'l {width:g} {height-r:g} '
            f'b {width:g} {height-r+k:g} {width-r+k:g} {height:g} {width-r:g} {height:g} '
            f'l {r:g} {height:g} b {r-k:g} {height:g} 0 {height-r+k:g} 0 {height-r:g} '
            f'l 0 {r:g} b 0 {r-k:g} {r-k:g} 0 {r:g} 0')


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

    def normalize_section(self, src, frames, fps, cache_dir, source_in_s=0,
                          width=None, height=None, kind="video", effects=()):
        """Normalize the exact selected interval; cache every rendering decision."""
        if frames <= 0 or fps <= 0 or source_in_s < 0 or set(effects)-{"cut","caption","static_image","text_overlay","audio_bed"}:
            raise RuntimeError("unsupported_or_invalid_section")
        probe = probe_path(self.runner, src)
        info = next(x for x in probe["streams"] if x["codec_type"] == "video")
        width,height = width or info["width"],height or info["height"]
        if kind != "image":
            # Matroska/WebM commonly omits duration on the individual
            # video stream while still reporting it on the container.
            # Use the format duration as the authoritative fallback, then
            # the stream's own frame count over its declared rate. When
            # NO clock evidence exists the source cannot be verified —
            # that is a rejection, never silent padding.
            duration = info.get("duration") or \
                (probe.get("format") or {}).get("duration")
            if duration is None:
                try:
                    nb = int(info.get("nb_frames") or 0)
                    rate = Fraction(str(info.get("avg_frame_rate") or
                                        info.get("r_frame_rate") or "0"))
                    duration = nb / float(rate) if nb and rate else None
                except (ValueError, ZeroDivisionError):
                    duration = None
            if duration is None:
                raise RuntimeError(
                    "short_footage: source has no verifiable duration")
            duration = float(duration)
            # The filter below intentionally pads one frame before the
            # exact trim.  Allow that single-frame tail when the container
            # duration lands just short of the output clock (common when a
            # source reports duration from timestamps); still reject a real
            # shortage of more than one frame.
            required = source_in_s + frames / fps
            if duration + 1e-5 < required - 1 / fps:
                raise RuntimeError("short_footage: source range exceeds duration")
        settings={"source_sha256":_digest(src),"frames":frames,"fps":fps,"source_in_s":source_in_s,
                  "width":width,"height":height,"kind":kind,"effects":list(effects),"renderer":"normalize.v3",
                  "codec":"libx264","crf":18,"pix_fmt":"yuv420p"}
        identity=hashlib.sha256(json.dumps(settings,sort_keys=True).encode()).hexdigest()
        out=Path(cache_dir)/f"{identity}.mp4"; receipt=out.with_suffix(".json")
        if out.exists() and receipt.exists():
            saved=json.loads(receipt.read_text())
            if saved.get("settings")==settings and saved.get("sha256")==_digest(out):
                return out,None
        tmp=out.with_suffix(".pending.mp4")
        args=["-loop","1","-framerate",str(fps)] if kind=="image" else []
        # A container duration can extend a fraction past its final decoded
        # frame (notably WebM).  The coverage check above still rejects real
        # shortages; pad one frame so a sub-frame timestamp discrepancy does
        # not make an otherwise valid tail selection render one frame short.
        vf=(f"trim=start={source_in_s},setpts=PTS-STARTPTS,"
            f"tpad=stop_mode=clone:stop_duration={1/fps},"
            f"fps={fps},trim=end_frame={frames},"
            f"setpts=N/({fps}*TB),scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},setsar=1,"
            "setparams=range=tv:color_primaries=bt709:color_trc=bt709:colorspace=bt709")
        r=self.runner(["ffmpeg","-v","error","-y",*args,"-i",str(src),"-an","-vf",vf,
                       "-frames:v",str(frames),"-c:v","libx264","-preset","veryfast","-crf","18",
                       "-threads","2","-pix_fmt","yuv420p",str(tmp)],timeout=self.timeout)
        if r.returncode:
            raise RuntimeError("section_normalization_failed")
        pic=next(x for x in probe_path(self.runner,tmp)["streams"] if x["codec_type"]=="video")
        if int(pic.get("nb_frames",0))!=frames:
            raise RuntimeError("short_footage: normalized frame count differs")
        tmp.replace(out)
        receipt.write_text(json.dumps({"sha256":_digest(out),"settings":settings}))
        return out,None

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
        cursor=0
        for seg in segments:
            if seg.get("in_frame",cursor)!=cursor or seg.get("out_frame",cursor+seg["frames"])!=cursor+seg["frames"]:
                raise RuntimeError("picture_timeline_gap_or_overlap")
            if seg.get("transition_out", "cut") not in ("cut","none",""):
                raise RuntimeError("transition_requires_hypit")
            cursor+=seg["frames"]
        if not cursor or clock.get("total_frames",cursor)!=cursor:
            raise RuntimeError("picture_coverage_incomplete")
        for c in captions:
            if not 0 <= c["start_frame"] < c["end_frame"] <= cursor:
                raise RuntimeError("caption_interval_invalid")
        for i, seg in enumerate(segments):
            progress["current"] = seg.get("id", f"seg{i}")
            progress["updated_at"] = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            (ws / "progress.json").write_text(json.dumps(progress))
            out, passthrough = self.normalize_section(
                seg["src"], seg["frames"], fps, cache,
                source_in_s=seg.get("source_in_s",0), width=clock["width"],height=clock["height"],
                kind=seg.get("media_kind","video"),effects=seg.get("effects",[]))
            inputs.append((passthrough or out, seg["frames"]))
            sid=seg.get("id",f"seg{i}")
            if sid not in progress["completed_sections"]:
                progress["completed_sections"].append(sid)
            progress["updated_at"] = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            (ws / "progress.json").write_text(json.dumps(progress))
            if on_progress:
                on_progress(dict(progress))
        # concat in exact shot order with per-segment durations
        concat = ws / "concat.txt"
        concat.write_text("".join(
            "file '" + str(Path(p).resolve()).replace("'", "'\\''") + "'\n" +
            f"duration {frames / fps:.12f}\n"
            for p, frames in inputs))
        ass = ws / "captions.ass"
        ass.write_text(captions_ass(captions, fps, clock.get('caption_preset', 'words.v1'), font_path=clock.get('font_path')))
        if captions:
            font_dir = ws / 'caption-fonts'
            font_dir.mkdir(exist_ok=True)
            (font_dir / 'caption.ttf').write_bytes(style.font_path(clock.get('font_path')).read_bytes())
        total = sum(f for _, f in inputs)
        tmp = ws / (final_name + ".pending.mp4")
        audio_args, filter_a = [], ""
        for i,a in enumerate(audio or []):
            off=a.get("offset_s",a.get("in_frame",0)/fps)
            source=a.get("source_in_s",0)
            span=a.get("duration_s",(a["out_frame"]-a["in_frame"])/fps if "out_frame" in a else total/fps-off)
            if off < 0 or source < 0 or span <= 0 or off+span > total/fps+1e-6:
                raise RuntimeError("audio_interval_invalid")
            info=next(x for x in probe_path(self.runner,a["src"])["streams"] if x["codec_type"]=="audio")
            if float(info.get("duration",0))+.02 < source+span:
                raise RuntimeError("insufficient_audio_coverage")
            audio_args += ["-i",str(a["src"])]
            filter_a += (f"[{i+1}:a]atrim=start={source}:duration={span},asetpts=PTS-STARTPTS,aresample=48000,"
                         f"volume={a.get('gain',1)},adelay={round(off*48000)}S:all=1,apad,atrim=end_sample={round(total/fps*48000)}[a{i}];")
        if audio:
            mix_in="".join(f"[a{i}]" for i in range(len(audio)))
            filter_a += (f"{mix_in}amix=inputs={len(audio)}:duration=longest:normalize=0,"
                         "alimiter=limit=0.95:level=false:latency=true[aout]")
        else:
            filter_a += "anullsrc=r=48000:cl=mono[aout]"
        vf = (f"[0:v]setpts=N/({fps}*TB),scale={clock['width']}:"
              f"{clock['height']}:flags=bicubic,setsar=1"
              + (",subtitles=captions.ass:fontsdir=caption-fonts" if captions else "")
              + "[v]")
        boundaries=[sum(n for _,n in inputs[:i])/fps for i in range(len(inputs))]
        argv = (["ffmpeg", "-v", "error", "-y", "-copyts",
                 "-f", "concat", "-safe", "0", "-i", "concat.txt"]
                + audio_args +
                ["-filter_complex_threads", "2", "-filter_complex",
                 vf + ";" + filter_a,
                 "-map", "[v]", "-map", "[aout]",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                 "-threads", "4", "-pix_fmt", "yuv420p",
                 "-r", str(fps), "-fps_mode", "cfr",
                 "-force_key_frames", ",".join(str(t) for t in boundaries), "-forced-idr", "1",
                 "-c:a", "aac", "-b:a", "192k",
                 "-t", f"{total / fps:.6f}",
                 "-movflags", "+faststart", tmp.name])
        try:
            r = self.runner(argv, timeout=self.timeout * 5, cwd=ws)
        except subprocess.TimeoutExpired:
            raise RenderTimeout("observer timeout; build state unknown")
        if r.returncode != 0:
            raise RuntimeError(f"render failed: {r.stderr[-300:]}")
        pic=next(x for x in probe_path(self.runner,tmp)["streams"] if x["codec_type"]=="video")
        if int(pic.get("nb_frames",0))!=total:
            raise RuntimeError("final_frame_count_mismatch")
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
