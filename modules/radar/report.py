"""Emit the niche_report contract (JSON) + a human-readable Markdown summary.
One schema `niches[]` entry per topic cluster (see cluster.py)."""
import json
from pathlib import Path

from . import __version__

OUTLIER_CHECKLIST = """## Reference review

- [ ] Open candidate references and verify the hook and payoff
- [ ] Confirm the post is still available and relevant to the selected niche
- [ ] Treat views/followers as an eligibility signal, not proof of repeatable success
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
    meta = report["scan_meta"]
    usage = (f"Viral Outliers: {meta.get('credits_reserved', 0)} credits reserved; "
             "provider charges are recorded in the JSON receipt"
             if meta.get("provider") == "viral-outliers"
             else f"YouTube quota used: {meta['quota_used']} units")
    lines = [
        f"# Niche Radar — {report['scan_meta']['scanned_at'][:10]}",
        "",
        usage
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
                    f"- {_video_summary(v)}"
                )
            lines.append("")
    unconfirmed = [n for n in report["niches"] if not n["confirmed"] and n["cluster_size"]]
    if unconfirmed:
        lines.append("## Unconfirmed spikes (single channel)")
        for n in unconfirmed:
            for v in n["breakout_videos"]:
                lines.append(
                    f"- {n['niche']}: {_video_summary(v)}"
                )
        lines.append("")
    quiet = [n["niche"] for n in report["niches"] if n["cluster_size"] == 0]
    if quiet:
        lines.append(f"Quiet niches (no breakouts): {', '.join(quiet)}")
        lines.append("")
    lines.append(OUTLIER_CHECKLIST)
    return "\n".join(lines)


def _video_summary(video):
    from modules.common.video_reference import video_reference
    baseline = (f"{video['multiplier']}x channel median" if video.get("baseline_available", True)
                else "channel median unavailable")
    title = video['title'].replace("[", "(").replace("]", ")").replace("\n", " ")
    return (f"**{video['subs_ratio']}x views/followers** ({video['views']:,} views; {baseline}) "
            f"[{title}]({video_reference(video)}) — {video['published_at'][:10]}")


def write_report(report, out_dir, date_str):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / f"{date_str}.json"
    md_path = out / f"{date_str}.md"
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(to_markdown(report), encoding="utf-8")
    return json_path, md_path
