"""M3 matching: every passing idea gets exactly 1 default format
(+ optional alt, explicitly labeled). Retired formats never match.

Ranking: same niche (+4) > proven (+2) > has wins (+1) > candidate (+0).
Deterministic — ties break by format_id sort order."""


def _score(fmt, idea):
    if fmt["status"] == "retired":
        return -1
    s = 0
    if fmt.get("niche") == idea.get("niche"):
        s += 4
    if fmt["status"] == "proven":
        s += 2
    if fmt.get("our_stats", {}).get("wins", 0) > 0:
        s += 1
    return s


def match_ideas(ideas, formats):
    """ideas: scored_ideas ideas[] (pass only are matched).
    Returns {idea_id: {"format_id": str, "alt_format_id": str|None}}.
    Raises ValueError if a passing idea has no eligible format."""
    eligible = sorted(
        (f for f in formats if f["status"] != "retired"),
        key=lambda f: f["format_id"],
    )
    out = {}
    for idea in ideas:
        if idea.get("status") != "pass":
            continue
        ranked = sorted(
            eligible, key=lambda f: (-_score(f, idea), f["format_id"])
        )
        if not ranked or _score(ranked[0], idea) < 0:
            raise ValueError(f"no eligible format for idea {idea['idea_id']}")
        out[idea["idea_id"]] = {
            "format_id": ranked[0]["format_id"],
            "alt_format_id": ranked[1]["format_id"] if len(ranked) > 1 else None,
        }
    return out
