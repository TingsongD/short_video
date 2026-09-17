"""Fixture materialization (F01).

Tracked data fixtures live under tests/factory_fixtures/<name>/. Larger
media is generated into the QA workspace from deterministic ffmpeg recipes —
bytes vary by build, so expectations are probe facts; generated hashes are
recorded in the workspace fixture-lock.json at init.
"""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "tests" / "factory_fixtures"


def manifest():
    return json.loads((FIXTURE_ROOT / "manifest.json").read_text())


def _ffmpeg(args, timeout=120):
    return subprocess.run(["ffmpeg", "-v", "error", "-y", *args],
                          check=True, capture_output=True, timeout=timeout)


def _color_mp4(path, duration, size="360x640", rate=24, color="0x3366cc",
               audio=True):
    src = f"color=c={color}:s={size}:r={rate}:d={duration}"
    args = ["-f", "lavfi", "-i", src]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}"]
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if audio:
        args += ["-c:a", "aac", "-shortest"]
    args += [str(path)]
    _ffmpeg(args)


def _moving_mp4(path, duration, size="360x640", rate=30, color="0x3366cc", audio=True):
    """Moving bar over color makes freezes distinguishable from intentional stills."""
    src=f"color=c={color}:s={size}:r={rate}:d={duration},drawgrid=w=40:h=40:t=2:c=white,scroll=horizontal=0.02"
    args=["-f","lavfi","-i",src]
    if audio:
        args += ["-f","lavfi","-i",f"sine=frequency=440:duration={duration}"]
    args += ["-c:v","libx264","-pix_fmt","yuv420p"]
    if audio:
        args += ["-c:a","aac","-shortest"]
    _ffmpeg(args+[str(path)])


def _png(path, size="360x640", color="0xcc3366"):
    # Force the PNG encoder+image2 muxer even when `path` ends in .mp4 —
    # reference-defects relies on PNG bytes under a video name.
    _ffmpeg(["-f", "lavfi", "-i", f"color=c={color}:s={size}:d=0.1",
             "-frames:v", "1", "-c:v", "png", "-f", "image2", str(path)])


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def materialize(fixture, workspace):
    """Materialize one fixture into <workspace>/fixtures/<fixture>/.

    Returns the recorded file list with sha256 + probe facts."""
    root = Path(workspace) / "fixtures" / fixture
    root.mkdir(parents=True, exist_ok=True)
    locked = {"fixture": fixture, "files": []}

    def record(path):
        p = Path(path)
        locked["files"].append({"path": str(p.relative_to(workspace)),
                                "sha256": _sha256(p), "bytes": p.stat().st_size})

    src_dir = FIXTURE_ROOT / fixture
    if src_dir.is_dir():
        for f in sorted(src_dir.iterdir()):
            dest = root / f.name
            shutil.copy2(f, dest)
            record(dest)

    gen = _GENERATORS.get(fixture)
    if gen:
        for path in gen(root):
            record(path)
    return locked


def _gen_core_30s(root):
    out = []
    src = root / "source.mp4"
    _color_mp4(src, 30.0)
    out.append(src)
    for i, color in enumerate(("0xaa3344", "0x33aa66", "0x3344aa"), 1):
        p = root / f"product-{i}.png"
        _png(p, color=color)
        out.append(p)
    bed = root / "music-bed.wav"
    _ffmpeg(["-f", "lavfi", "-i", "sine=frequency=220:duration=30",
             "-c:a", "pcm_s16le", str(bed)])
    out.append(bed)
    beats = {"beats_s": [[0, 4], [4, 8], [8, 12], [12, 17], [17, 26], [26, 30]],
             "transcript": [
                 {"id": "hook", "text": "Three outfits that fix Monday.",
                  "start_s": 0.0, "end_s": 4.0},
                 {"id": "p1", "text": "First, the denim that does everything.",
                  "start_s": 4.0, "end_s": 8.0},
                 {"id": "p2", "text": "This knit goes desk to dinner.",
                  "start_s": 8.0, "end_s": 12.0},
                 {"id": "p3", "text": "And the dress people ask about.",
                  "start_s": 12.0, "end_s": 17.0},
                 {"id": "proof", "text": "Every piece under sixty dollars.",
                  "start_s": 17.0, "end_s": 26.0},
                 {"id": "cta", "text": "Links are below — sizes go fast.",
                  "start_s": 26.0, "end_s": 30.0}]}
    p = root / "transcript.json"
    p.write_text(json.dumps(beats, indent=1))
    out.append(p)
    return out


def _gen_long_haul(root):
    src = root / "source.mp4"
    _color_mp4(src, 169.7, color="0x445566")
    return [src]


def _gen_reference_defects(root):
    out = []
    thumb = root / "thumbnail_as_video.mp4"
    _png(thumb)                      # PNG bytes with .mp4 name
    out.append(thumb)
    zero = root / "zero_byte.mp4"
    zero.write_bytes(b"")
    out.append(zero)
    corrupt = root / "corrupt.mp4"
    corrupt.write_bytes(b"\x00\x01\x02\x03 not a media file \x04\x05")
    out.append(corrupt)
    short = root / "short_clip.mp4"
    _color_mp4(short, 1.0)           # shorter than any 4s allocation
    out.append(short)
    vfr = root / "vfr_clip.mp4"
    _ffmpeg(["-f", "lavfi", "-i", "testsrc=s=360x640:d=5:r=24",
             "-vf", "setpts=N/(30)/TB", "-vsync", "vfr",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", str(vfr)])
    out.append(vfr)
    noaudio = root / "missing_audio.mp4"
    _color_mp4(noaudio, 5.0, audio=False)
    out.append(noaudio)
    return out


def _gen_composition_effects(root):
    out = []
    for i in range(1, 3):
        p = root / f"seg-{i}.mp4"
        _color_mp4(p, 5.0, color=f"0x{20+i*30:02x}{40+i*20:02x}aa")
        out.append(p)
    spec = root / "composition.json"
    spec.write_text(json.dumps({
        "static": {"segments": ["seg-1.mp4", "seg-2.mp4"], "overlays": []},
        "animated": {"segments": ["seg-1.mp4"],
                     "overlays": [{"type": "animated_overlay",
                                   "unsupported_by": "ffmpeg_fast_path"}]}
    }, indent=1))
    out.append(spec)
    return out


_GENERATORS = {
    "core-30s": _gen_core_30s,
    "long-haul-1697": _gen_long_haul,
    "reference-defects": _gen_reference_defects,
    "composition-effects": _gen_composition_effects,
}
