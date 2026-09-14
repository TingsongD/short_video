"""Emit the niche_report contract (JSON) + a human-readable Markdown summary.
One schema `niches[]` entry per topic cluster (see cluster.py)."""
import json
from pathlib import Path

from . import __version__

OUTLIER_CHECKLIST = """## Outlier.so cross-check (manual, ~10 min)

- [ ] Open outlier.so free tier; search each confirmed topic key above
- [ ] Note any breakout format the API scan missed (thumbnail/title pattern)
- [ ] Add missed candidates to the grill slate manually if they pass smell test
"""


def build_report(clusters, scanned_at, niches_scanned, quota_used, degraded=False):
    return {
        "scan_meta": {
            "scanned_at": scanned_at.isoformat().replace("+00:00", "Z"),
            "niches_scanned": list(niches_scanned),
            "quota_used": quota_used,
            "scanner_version": __version__,
            "degraded": degraded,
        },
        "niches": [
            {
                "niche": c["niche"],
                "cluster_size": len(c["videos"]),
                "confirmed": c["confirmed"],
                "breakout_videos": c["videos"],
            }
            for c in clusters
        ],
    }


def to_markdown(report, topics=None):
    lines = [
        f"# Niche Radar — {report['scan_meta']['scanned_at'][:10]}",
        "",
        f"Quota used: {report['scan_meta']['quota_used']} units"
        + ("  ⚠️ DEGRADED (channel-only, quota exhausted)" if report["scan_meta"].get("degraded") else ""),
        "",
    ]
    topics = topics or {}
    confirmed = [n for n in report["niches"] if n["confirmed"]]
    if confirmed:
        lines.append("## Confirmed clusters (>=2 distinct channels)")
        for n in confirmed:
            key = f"{n['niche']}|{id(n)}"
            lines.append(f"### {n['niche']} — {n['cluster_size']} breakout(s)")
            for v in n["breakout_videos"]:
                lines.append(
                    f"- **{v['multiplier']}x** ({v['views']:,} views, "
                    f"{v['subs_ratio']}x subs) [{v.get('channel_title') or v['channel_id']}] "
                    f"{v['title']} — {v['published_at'][:10]}"
                )
            lines.append("")
    unconfirmed = [n for n in report["niches"] if not n["confirmed"] and n["cluster_size"]]
    if unconfirmed:
        lines.append("## Unconfirmed spikes (single channel)")
        for n in unconfirmed:
            for v in n["breakout_videos"]:
                lines.append(
                    f"- {n['niche']}: {v['multiplier']}x [{v.get('channel_title') or v['channel_id']}] {v['title']}"
                )
        lines.append("")
    quiet = [n["niche"] for n in report["niches"] if n["cluster_size"] == 0]
    if quiet:
        lines.append(f"Quiet niches (no breakouts): {', '.join(quiet)}")
        lines.append("")
    lines.append(OUTLIER_CHECKLIST)
    return "\n".join(lines)


def write_report(report, out_dir, date_str):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / f"{date_str}.json"
    md_path = out / f"{date_str}.md"
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(to_markdown(report), encoding="utf-8")
    return json_path, md_path
