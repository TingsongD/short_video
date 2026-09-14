"""M10 readback: merge window pulls into data/analytics/<video_id>.json,
recompute verdict + promotion signal, emit weekly learning summary lines."""
import json
from pathlib import Path

from modules.common.config import DATA_DIR
from modules.common.schema import validate

from .verdict import format_promotion_signal, verdict

ANALYTICS_DIR = DATA_DIR / "analytics"


def load_or_new(video_id, directory=None):
    p = Path(directory or ANALYTICS_DIR) / f"{video_id}.json"
    if p.exists():
        return json.loads(p.read_text())
    return {"video_id": video_id, "windows": {}, "verdict": "pending",
            "format_promotion": "none", "baseline_median_views": 0}


def record_window(doc, name, window, video_len_s, cfg):
    """Merge one window pull; recompute verdict from the latest window."""
    doc["windows"][name] = window
    latest = doc["windows"].get("28d") or doc["windows"].get("7d") or doc["windows"].get("48h")
    v = verdict(latest, video_len_s, doc.get("baseline_median_views", 0), cfg)
    doc["verdict"] = v
    doc["format_promotion"] = format_promotion_signal(v)
    return validate(doc, "readback.schema.json")


def write_readback(doc, directory=None):
    d = Path(directory or ANALYTICS_DIR)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{doc['video_id']}.json"
    p.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return p


def weekly_summary(readbacks):
    """Markdown block appended to the radar report (M1 learning loop)."""
    lines = ["## Learning summary (M10 readbacks)", ""]
    if not readbacks:
        return "\n".join(lines + ["_no readbacks yet_"])
    for r in readbacks:
        wins = {k: w.get("views", 0) for k, w in r.get("windows", {}).items()}
        lines.append(
            f"- `{r['video_id']}` verdict **{r['verdict']}** "
            f"(promotion: {r['format_promotion']}) views: {wins}"
        )
    return "\n".join(lines)
