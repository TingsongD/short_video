"""ffprobe → typed Probe. Bounded timeouts; extension/MIME are hints —
the probed stream facts are the truth (F04 checklist 1–2)."""
import json
import subprocess
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

from ..domain.errors import ContractError

PROBE_TIMEOUT = 30


@dataclass
class StreamInfo:
    codec_type: str = ""              # video | audio | subtitle | ...
    codec_name: str = ""
    width: int = 0
    height: int = 0
    r_frame_rate: object = None       # Fraction — container-claimed rate
    avg_frame_rate: object = None     # Fraction — measured rate
    nb_frames: object = None          # int | None
    duration_s: object = None         # float | None
    sample_rate: int = 0
    channels: int = 0

    @property
    def vfr(self):
        return (self.r_frame_rate is not None
                and self.avg_frame_rate is not None
                and self.r_frame_rate != self.avg_frame_rate)

    def to_dict(self):
        d = {"codec_type": self.codec_type, "codec_name": self.codec_name}
        if self.codec_type == "video":
            d.update(width=self.width, height=self.height,
                     r_frame_rate=str(self.r_frame_rate or ""),
                     avg_frame_rate=str(self.avg_frame_rate or ""),
                     nb_frames=self.nb_frames,
                     vfr=self.vfr)
        if self.codec_type == "audio":
            d.update(sample_rate=self.sample_rate,
                     channels=self.channels)
        if self.duration_s is not None:
            d["duration_s"] = self.duration_s
        return d


@dataclass
class Probe:
    format_name: str = ""
    duration_s: float = 0.0
    byte_count: int = 0
    streams: list = field(default_factory=list)

    @property
    def video(self):
        return next((s for s in self.streams if s.codec_type == "video"),
                    None)

    @property
    def audio(self):
        return next((s for s in self.streams if s.codec_type == "audio"),
                    None)

    def kind(self):
        """Classify by stream facts, never by filename."""
        v = self.video
        if v is not None:
            image_codecs = {"png", "mjpeg", "bmp", "webp", "tiff", "gif"}
            single = (v.nb_frames in (None, 1)
                      and v.codec_name in image_codecs)
            return "image" if single else "video"
        if self.audio is not None:
            return "audio"
        return "unknown"

    def to_dict(self):
        return {"format_name": self.format_name,
                "duration_s": self.duration_s,
                "byte_count": self.byte_count,
                "streams": [s.to_dict() for s in self.streams]}


def _rate(value):
    if not value or value == "0/0":
        return None
    try:
        f = Fraction(value)
        return f if f > 0 else None
    except (ValueError, ZeroDivisionError):
        return None


def probe(path):
    p = Path(path)
    if not p.is_file():
        raise ContractError("missing_file", "path", str(path))
    size = p.stat().st_size
    if size == 0:
        raise ContractError("zero_bytes", "path", str(path))
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format",
             "-of", "json", str(p)],
            capture_output=True, text=True, timeout=PROBE_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ContractError("probe_failed", "path", str(e))
    if out.returncode != 0:
        raise ContractError("unprobeable", "path",
                            out.stderr.strip()[:200] or "ffprobe failed")
    try:
        data = json.loads(out.stdout)
    except json.JSONDecodeError as e:
        raise ContractError("unprobeable", "path", f"bad ffprobe json: {e}")
    streams = []
    for s in data.get("streams") or []:
        streams.append(StreamInfo(
            codec_type=s.get("codec_type", ""),
            codec_name=s.get("codec_name", ""),
            width=int(s.get("width") or 0),
            height=int(s.get("height") or 0),
            r_frame_rate=_rate(s.get("r_frame_rate")),
            avg_frame_rate=_rate(s.get("avg_frame_rate")),
            nb_frames=(int(s["nb_frames"]) if str(
                s.get("nb_frames", "")).isdigit() else None),
            duration_s=(float(s["duration"]) if s.get("duration")
                        else None),
            sample_rate=int(s.get("sample_rate") or 0),
            channels=int(s.get("channels") or 0)))
    fmt = data.get("format") or {}
    return Probe(
        format_name=fmt.get("format_name", ""),
        duration_s=float(fmt.get("duration") or 0),
        byte_count=int(fmt.get("size") or size),
        streams=streams)
