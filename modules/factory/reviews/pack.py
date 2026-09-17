"""Review pack (F24): required evidence for every section — product
reveals, detail shots, motion extremes, transitions, first/last frame,
caption joins — extracted to a durable pack a reviewer can judge.
"""
import json
import subprocess
from pathlib import Path


def required_evidence(segments, captions, fps):
    """Every required check-point with its frame location."""
    out = []
    for s in segments:
        sid = s["id"]
        out.append({"kind": "first_frame", "segment": sid,
                    "frame": s["in_frame"]})
        out.append({"kind": "last_frame", "segment": sid,
                    "frame": s["out_frame"] - 1})
        if s.get("role") in ("product", "reveal", "detail"):
            mid = (s["in_frame"] + s["out_frame"]) // 2
            out.append({"kind": f"{s['role']}_check", "segment": sid,
                        "frame": mid})
        if s.get("transition_out") not in (None, "cut", "none"):
            out.append({"kind": "transition", "segment": sid,
                        "frame": s["out_frame"] - 1})
    for c in captions:
        out.append({"kind": "caption_join", "caption": c["id"],
                    "frame": c["start_frame"]})
        out.append({"kind": "caption_text", "caption": c["id"],
                    "frame": (c["start_frame"] + c["end_frame"]) // 2,
                    "text": c["text"]})
    return sorted(out, key=lambda e: e["frame"])


class ReviewPack:
    def __init__(self, root, runner=None):
        self.root = Path(root)
        self.runner = runner or (
            lambda argv, timeout=60: subprocess.run(
                argv, capture_output=True, text=True, timeout=timeout))

    def build(self, pack_id, final_path, segments, captions, fps):
        """Extract every required frame to pack dir; write index."""
        pack = self.root / pack_id
        pack.mkdir(parents=True, exist_ok=True)
        reqs = required_evidence(segments, captions, fps)
        files = []
        for i, e in enumerate(reqs):
            name = f"{i:03d}-{e['kind']}-f{e['frame']}.jpg"
            out = pack / name
            r = self.runner(
                ["ffmpeg", "-y", "-v", "error", "-i", str(final_path),
                 "-vf", f"select='eq(n,{e['frame']})'", "-vsync", "0",
                 "-frames:v", "1", str(out)], timeout=60)
            ok = r.returncode == 0 and out.exists()
            files.append({**e, "file": name, "extracted": ok})
        index = {"pack_id": pack_id, "final": str(final_path),
                 "fps": fps, "evidence": files}
        (pack / "index.json").write_text(json.dumps(index, indent=1))
        return index
