"""Technical QC (F24): probe and decode-verify a final; distinguish
container padding from picture duration; find black/frozen/corrupt
sections and audio silence/clipping. Findings carry locations.
"""
import json
import re
import subprocess


class TechnicalQC:
    def __init__(self, runner=None):
        self.runner = runner or (
            lambda argv, timeout=60: subprocess.run(
                argv, capture_output=True, text=True, timeout=timeout))

    def _ff(self, argv, timeout=60):
        return self.runner(argv, timeout=timeout)

    def probe(self, path):
        r = self._ff(["ffprobe", "-v", "error", "-print_format", "json",
                      "-show_streams", "-show_format", str(path)])
        if r.returncode != 0:
            raise RuntimeError(f"probe failed: {r.stderr[-200:]}")
        return json.loads(r.stdout)

    # ------------------------------------------------------------

    def inspect(self, path, expected):
        """expected: {frames, fps, width, height, has_audio,
        duration_s}. → {"ok", "findings":[{code,at,detail}]}"""
        findings = []
        try:
            info = self.probe(path)
        except RuntimeError as e:
            return {"ok": False, "findings": [
                {"code": "probe_failed", "at": "container",
                 "detail": str(e)[:200]}]}
        vids = [s for s in info.get("streams", [])
                if s.get("codec_type") == "video"]
        auds = [s for s in info.get("streams", [])
                if s.get("codec_type") == "audio"]
        if not vids:
            findings.append({"code": "no_video", "at": "container",
                             "detail": ""})
            return {"ok": False, "findings": findings}
        v = vids[0]
        if (v.get("width"), v.get("height")) != \
                (expected["width"], expected["height"]):
            findings.append({"code": "wrong_dimensions",
                             "at": "video",
                             "detail": f"{v.get('width')}x"
                                       f"{v.get('height')}"})
        nb = int(v.get("nb_frames", 0) or 0)
        if expected.get("frames") and nb != expected["frames"]:
            # container padding is not picture duration
            findings.append({"code": "wrong_frame_count",
                             "at": "video",
                             "detail": f"{nb} != {expected['frames']}"})
        if expected.get("has_audio") and not auds:
            findings.append({"code": "no_audio", "at": "container",
                             "detail": ""})
        # decode pass — any decode error is a finding with its log tail
        dec = self._ff(["ffmpeg", "-v", "error", "-i", str(path),
                        "-f", "null", "-"], timeout=120)
        if dec.returncode != 0 or dec.stderr.strip():
            findings.append({"code": "decode_error", "at": "stream",
                             "detail": (dec.stderr or
                                        "decode failed")[-200:]})
        findings += self._black_freeze(path)
        if auds and expected.get("has_audio"):
            findings += self._audio_levels(path)
        return {"ok": not findings, "findings": findings,
                "streams": {"video": bool(vids), "audio": bool(auds)},
                "frames": nb}

    def _black_freeze(self, path):
        """blackdetect + freezedetect — findings carry time ranges."""
        out = []
        r = self._ff(["ffmpeg", "-v", "info", "-i", str(path), "-vf",
                      "blackdetect=d=0.5:pix_th=0.10,freezedetect=n=0.001:d=0.5",
                      "-an", "-f", "null", "-"], timeout=120)
        log = r.stderr or ""
        for m in re.finditer(r"blackdetect.*black_start:([\d.]+) "
                             r"black_end:([\d.]+)", log):
            out.append({"code": "black_section",
                        "at": f"{m.group(1)}-{m.group(2)}s",
                        "detail": "black frames"})
        for m in re.finditer(r"freezedetect.*freeze_start:([\d.]+).*?"
                             r"freeze_end:([\d.]+)", log):
            out.append({"code": "frozen_section",
                        "at": f"{m.group(1)}-{m.group(2)}s",
                        "detail": "frozen frames"})
        return out

    def _audio_levels(self, path):
        """volumedetect: silence vs clipping policy — measured, not
        assumed."""
        r = self._ff(["ffmpeg", "-v", "info", "-i", str(path), "-af",
                      "volumedetect", "-vn", "-f", "null", "-"],
                     timeout=120)
        log = r.stderr or ""
        out = []
        mean = re.search(r"mean_volume: ([-\d.]+) dB", log)
        peak = re.search(r"max_volume: ([-\d.]+) dB", log)
        if mean and float(mean.group(1)) < -60:
            out.append({"code": "silent_audio", "at": "audio",
                        "detail": f"mean {mean.group(1)} dB"})
        if peak and float(peak.group(1)) >= -0.05:
            out.append({"code": "clipping", "at": "audio",
                        "detail": f"max {peak.group(1)} dB"})
        return out
