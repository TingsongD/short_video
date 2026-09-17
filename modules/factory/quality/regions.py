"""Changed-region gate (F24): A vs each variant outside declared
changed intervals. Deterministic intermediates compare by hash;
separately encoded finals compare by calibrated SSIM. Any difference
outside the declared regions is an undeclared_change with a location.
"""
import json
import re
import subprocess
import hashlib


class RegionGate:
    def __init__(self, runner=None, ssim_threshold=0.98):
        self.runner = runner or (
            lambda argv, timeout=60: subprocess.run(
                argv, capture_output=True, text=True, timeout=timeout))
        self.threshold = ssim_threshold

    # ------------------------------------------- deterministic mode --

    def compare_intermediates(self, a_hashes, b_hashes,
                              unchanged_regions):
        """a_hashes/b_hashes: {region_key: sha256} of normalized
        intermediate sections. Identical inputs must hash identically
        — a difference is proof of an undeclared change."""
        diffs = []
        for r in unchanged_regions:
            key = f"{r['start_frame']}-{r['end_frame']}"
            if a_hashes.get(key) != b_hashes.get(key):
                diffs.append({"region": key, "mode": "hash",
                              "a": (a_hashes.get(key) or "")[:12],
                              "b": (b_hashes.get(key) or "")[:12],
                              "code": "undeclared_change"})
        return {"ok": not diffs, "diffs": diffs}

    # --------------------------------------------------- final mode --

    def compare_finals(self, a_path, b_path, unchanged_regions, fps,
                       samples_per_region=1):
        """Sample-frame SSIM per unchanged region. Encoded pixels carry
        codec noise — calibrated threshold separates noise from real
        change. Returns per-region scores for evidence."""
        regions = []
        diffs = []
        for r in unchanged_regions:
            mid = (r["start_frame"] + r["end_frame"]) // 2
            t = mid / fps
            score = self._ssim_at(a_path, b_path, t)
            regions.append({"region":
                            f"{r['start_frame']}-{r['end_frame']}",
                            "sample_frame": mid, "ssim": score})
            if score is None or score < self.threshold:
                diffs.append({"region":
                              f"{r['start_frame']}-{r['end_frame']}",
                              "sample_frame": mid, "ssim": score,
                              "code": "undeclared_change"})
        return {"ok": not diffs, "regions": regions, "diffs": diffs}

    def _ssim_at(self, a, b, t):
        r = self.runner(
            ["ffmpeg", "-v", "info",
             "-ss", f"{t:.4f}", "-i", str(a),
             "-ss", f"{t:.4f}", "-i", str(b),
             "-filter_complex",
             "[0:v]select='eq(n,0)'[x];[1:v]select='eq(n,0)'[y];"
             "[x][y]ssim", "-f", "null", "-"], timeout=120)
        log = r.stderr or ""
        m = re.search(r"All:([\d.]+)", log)
        return float(m.group(1)) if m else None

    # --------------------------------------------------- audio side --

    def compare_audio_region(self, a_mix, b_mix, region, rate=22050):
        """Unchanged audio regions must be sample-identical — a music
        gain or normalization difference outside declared scope is a
        leak. a_mix/b_mix: sample lists (pcm module)."""
        s, e = int(region["start_s"] * rate), int(region["end_s"] * rate)
        aa, bb = a_mix[s:e], b_mix[s:e]
        if len(aa) != len(bb):
            return {"ok": False, "code": "length_differs",
                    "region": region}
        if aa != bb:
            first = next(i for i, (x, y) in enumerate(zip(aa, bb))
                         if x != y)
            return {"ok": False, "code": "undeclared_change",
                    "region": region,
                    "first_diff_sample": s + first,
                    "at_s": round((s + first) / rate, 4)}
        return {"ok": True, "region": region}
