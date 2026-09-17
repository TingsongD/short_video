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
        diffs = [] if unchanged_regions else [{"code":"missing_region_coverage"}]
        for r in unchanged_regions:
            key = f"{r['start_frame']}-{r['end_frame']}"
            if not re.fullmatch(r"[0-9a-f]{64}",a_hashes.get(key, "")) or not re.fullmatch(r"[0-9a-f]{64}",b_hashes.get(key, "")) or a_hashes[key] != b_hashes[key]:
                diffs.append({"region": key, "mode": "hash",
                              "a": (a_hashes.get(key) or "")[:12],
                              "b": (b_hashes.get(key) or "")[:12],
                              "code": "undeclared_change"})
        return {"ok": not diffs, "diffs": diffs}

    # --------------------------------------------------- final mode --

    def compare_finals(self, a_path, b_path, unchanged_regions, fps,
                       samples_per_region=1):
        """Compare every frame in each complete unchanged interval.
        samples_per_region is retained for callers; coverage is always full.
        Codec noise uses the configured minimum per-frame SSIM threshold."""
        import tempfile
        from pathlib import Path
        regions, diffs = [], []
        if not unchanged_regions:
            return {"ok":False,"regions":[],"diffs":[{"code":"missing_region_coverage","ssim":None,"region":"all"}]}
        for interval in unchanged_regions:
            start,end = interval["start_frame"],interval["end_frame"]
            key = f"{start}-{end}"
            scores=[]
            if start >= 0 and end > start:
                with tempfile.TemporaryDirectory(prefix="factory-ssim-") as td:
                    stats = Path(td)/"scores.txt"
                    filt = (f"[0:v]trim=start_frame={start}:end_frame={end},setpts=PTS-STARTPTS[x];"
                            f"[1:v]trim=start_frame={start}:end_frame={end},setpts=PTS-STARTPTS[y];"
                            f"[x][y]ssim=stats_file={stats}:shortest=1:repeatlast=0")
                    try:
                        r=self.runner(["ffmpeg","-v","error","-i",str(a_path),"-i",str(b_path),
                                       "-filter_complex",filt,"-an","-f","null","-"],timeout=120)
                        if r.returncode == 0 and stats.exists():
                            scores=[float(x) for x in re.findall(r"All:([\d.]+)",stats.read_text())]
                    except (OSError,subprocess.SubprocessError):
                        scores=[]
            score=min(scores) if scores else None
            evidence={"region":key,"ssim":score,"compared_frames":len(scores),"expected_frames":end-start}
            regions.append(evidence)
            if len(scores)!=end-start or score is None or score < self.threshold:
                diffs.append({**evidence,"code":"undeclared_change" if scores else "missing_evidence"})
        return {"ok":not diffs,"regions":regions,"diffs":diffs}

    # --------------------------------------------------- audio side --

    def compare_audio_region(self, a_mix, b_mix, region, rate=22050):
        """Unchanged audio regions must be sample-identical — a music
        gain or normalization difference outside declared scope is a
        leak. a_mix/b_mix: sample lists (pcm module)."""
        s, e = int(region["start_s"] * rate), int(region["end_s"] * rate)
        if s < 0 or e <= s or len(a_mix) < e or len(b_mix) < e:
            return {"ok":False,"code":"missing_audio_coverage","region":region}
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
