"""M3 extraction: draft a format_entry from breakout evidence via LLM.
Structure only — the no-copy guard rejects entries that reuse the reference
title's wording (token overlap > 0.6)."""
import re

from modules.common.llm import parse_json

MAX_TOKEN_OVERLAP = 0.6

EXTRACT_SYSTEM = """You extract reusable short-form STRUCTURES from breakout videos.
Describe the skeleton, never the wording: hook_type (spoken|caption|onscreen),
exactly 3 beats as abstract stages (e.g. "Stakes: name the viewer's vulnerable
moment", NOT the video's actual phrasing), visual_payoff, cta_pattern.
Return ONLY JSON:
{"name": str (original structural name, no copied phrases),
 "hook_type": "spoken|caption|onscreen",
 "beats": [str, str, str], "visual_payoff": str, "cta_pattern": str}"""

STOP = {"the", "a", "an", "of", "to", "in", "is", "are", "you", "your",
        "that", "this", "it", "for", "on", "and", "or", "how", "with"}


def _tokens(text):
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP}


def token_overlap(a, b):
    """Jaccard similarity of content tokens. 1.0 = identical wording."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def watch_url(video_id):
    return f"https://www.youtube.com/watch?v={video_id}"


def draft_format(video, niche, llm, idea=None):
    """video: breakout_videos[] entry. Returns a full format_entry dict.
    Raises ValueError on no-copy violation or bad LLM output."""
    user = (
        f"Niche: {niche}\nReference title: {video['title']}\n"
        f"Observed format guess: {video.get('format_guess', '')}\n"
        f"Multiplier: {video.get('multiplier')}x vs channel median\n"
        + (f"Related approved idea payoff: {idea['payoff']}\n" if idea else "")
        + "Draft the reusable format structure."
    )
    raw = llm.complete(EXTRACT_SYSTEM, user, temperature=0.0)
    d = parse_json(raw)
    beats = [b for b in d.get("beats", []) if isinstance(b, str) and b.strip()][:3]
    entry = {
        "format_id": "",  # assigned by library.add
        "name": str(d["name"]).strip(),
        "hook_type": d["hook_type"],
        "beats": beats,
        "visual_payoff": str(d["visual_payoff"]).strip(),
        "cta_pattern": str(d.get("cta_pattern", "")).strip(),
        "watch_reference": watch_url(video["video_id"]),
        "status": "candidate",
        "our_stats": {"videos": 0, "wins": 0, "avg_multiplier": 0},
        "niche": niche,
        "notes": f"Extracted from {video['video_id']} ({video.get('multiplier')}x outlier)",
    }
    if len(beats) != 3 or entry["hook_type"] not in ("spoken", "caption", "onscreen"):
        raise ValueError("extracted format fails structural requirements")
    overlap = token_overlap(entry["name"] + " " + " ".join(beats), video["title"])
    if overlap > MAX_TOKEN_OVERLAP:
        raise ValueError(f"extracted format copies reference wording ({overlap:.2f})")
    return entry
