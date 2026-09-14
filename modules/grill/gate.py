"""M2 gate: apply pass thresholds, emit the scored_ideas contract.
pass = hook_score >= pass_hook_score AND virality_score >= pass_virality_score.
"""
from datetime import datetime, timezone

from .generate import expand_cluster
from .score import score_candidate


def apply_gate(idea, cfg):
    """idea from score_candidate (status 'pending' or 'kill'). Mutates+returns."""
    if idea["status"] == "kill":
        return idea
    if idea["hook_score"] < cfg["pass_hook_score"]:
        idea["status"] = "kill"
        idea["kill_reason"] = (
            f"hook_score {idea['hook_score']} < {cfg['pass_hook_score']}"
        )
    elif idea["virality_score"] < cfg["pass_virality_score"]:
        idea["status"] = "kill"
        idea["kill_reason"] = (
            f"virality_score {idea['virality_score']} < {cfg['pass_virality_score']}"
        )
    else:
        idea["status"] = "pass"
        idea["kill_reason"] = None
    return idea


def score_candidates(candidates, llm, cfg):
    """Score + gate a list of raw candidates. Returns (ideas, audit_log)."""
    ideas, audit = [], []
    for c in candidates:
        scored = apply_gate(score_candidate(c, llm), cfg)
        audit.append(scored.pop("_audit") | {"idea_id": scored["idea_id"]})
        ideas.append(scored)
    return ideas, audit


def run(niche_report, llm, cfg, source_report="", generated_at=None):
    """Full grill pass over a niche_report dict. LLM expands every cluster
    that has breakout evidence, then scores and gates."""
    candidates = []
    for entry in niche_report.get("niches", []):
        if entry.get("breakout_videos"):
            candidates.extend(expand_cluster(entry, llm, cfg["ideas_per_cluster"]))
    return build_output(candidates, llm, cfg, source_report, generated_at)


def build_output(candidates, llm, cfg, source_report="", generated_at=None):
    """Score/gate raw candidates -> scored_ideas document + audit log."""
    generated_at = generated_at or datetime.now(timezone.utc)
    for i, c in enumerate(candidates):
        c.setdefault("idea_id", f"idea-{generated_at:%Y%m%d}-{i + 1:03d}")
    ideas, audit = score_candidates(candidates, llm, cfg)
    doc = {
        "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
        "source_report": source_report,
        "ideas": ideas,
    }
    return doc, audit
