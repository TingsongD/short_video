"""M2 generation: expand a radar cluster into candidate ideas via LLM.
Batch mode — the niche_report replaces the vendored grill's human interview."""
import json

from modules.common.llm import parse_json

from .prompts import GENERATE_SYSTEM


def expand_cluster(cluster_entry, llm, n_ideas):
    """cluster_entry: one niche_report.niches[] item with breakout_videos.
    Returns list of raw candidate dicts (idea_id assigned by gate.run)."""
    evidence = [
        {
            "title": v["title"],
            "multiplier_vs_median": v["multiplier"] if v.get("baseline_available", True) else None,
            "views_to_followers": v.get("subs_ratio"),
            "platform": v.get("platform", "youtube"),
            "source_url": v.get("source_url"),
            "views": v["views"],
            "format_guess": v.get("format_guess", ""),
        }
        for v in cluster_entry.get("breakout_videos", [])
    ]
    user = (
        f"Niche: {cluster_entry['niche']}\n"
        f"Confirmed cluster: {cluster_entry.get('confirmed', False)}\n"
        f"Breakout evidence: {json.dumps(evidence)}\n"
        f"Generate {n_ideas} candidate ideas as a JSON array."
    )
    raw = llm.complete(GENERATE_SYSTEM, user, temperature=0.0)
    ideas = parse_json(raw)
    out = []
    for i in ideas[:n_ideas]:
        out.append(
            {
                "niche": cluster_entry["niche"],
                "topic": i["topic"],
                "hook_overlay": i["hook_overlay"],
                "target_viewer": i.get("target_viewer", ""),
                "payoff": i["payoff"],
                "three_bullets": i.get("three_bullets", []),
                "cta": i.get("cta", ""),
                "filmable": True,
                "number_claims": i.get("number_claims", []),
                "source_video_ids": [v["video_id"] for v in cluster_entry.get("breakout_videos", [])],
            }
        )
    return out
