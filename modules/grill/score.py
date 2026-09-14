"""M2 scoring: deterministic hard-reject rules + LLM-as-judge (temp 0).

Hard-reject order is deliberate — each fixture candidate must die by its own
rule: viewer -> payoff -> hook -> numbers -> structure. Every candidate is
still judged (killed ones too) so the audit log has real scores for G2's
human review. three_bullets comes from the candidate when present; the judge
supplies them otherwise; killed ideas are padded so output is always
schema-valid.
"""
import re

from modules.common.llm import parse_json

from .prompts import JUDGE_SYSTEM

HYPE_PATTERNS = [
    r"change your life",
    r"won'?t believe",
    r"!{2,}",
    r"\binsane\b",
    r"\bcrazy\b",
    r"\bshocking\b",
    r"mind.?blow",
    r"they don'?t want you to know",
]

KILL_NO_VIEWER = "no specific viewer"
KILL_NO_PAYOFF = "no filmable payoff"
KILL_NO_HOOK = "no repayable hook"
KILL_BAD_NUMBER = "unsupported numeric claim"
KILL_STRUCTURE = "incomplete idea structure (three_bullets)"


def hard_reject(candidate):
    """Return kill_reason str or None. Deterministic, no LLM."""
    if not (candidate.get("target_viewer") or "").strip():
        return KILL_NO_VIEWER
    if not candidate.get("filmable", True) or not (candidate.get("payoff") or "").strip():
        return KILL_NO_PAYOFF
    hook = (candidate.get("hook_overlay") or "").lower()
    words = re.findall(r"[a-z']+", hook)
    if len(words) < 3 or any(re.search(p, hook) for p in HYPE_PATTERNS):
        return KILL_NO_HOOK
    if candidate.get("number_claims"):
        return KILL_BAD_NUMBER
    return None


def _clamp(x):
    return round(max(1.0, min(10.0, float(x))), 1)


def _clean_bullets(items):
    return [b.strip() for b in items if isinstance(b, str) and b.strip()]


def judge(candidate, llm):
    """LLM-as-judge at temperature 0. Returns scores + bullets + raw output."""
    user = (
        "Score this short-form idea.\n"
        f"niche: {candidate.get('niche')}\n"
        f"topic: {candidate.get('topic')}\n"
        f"hook_overlay: {candidate.get('hook_overlay')}\n"
        f"target_viewer: {candidate.get('target_viewer')}\n"
        f"payoff: {candidate.get('payoff')}\n"
        f"three_bullets: {candidate.get('three_bullets', [])}\n"
        f"cta: {candidate.get('cta')}"
    )
    raw = llm.complete(JUDGE_SYSTEM, user, temperature=0.0)
    s = parse_json(raw)
    return {
        "virality_score": _clamp(s["virality_score"]),
        "hook_score": _clamp(s["hook_score"]),
        "payoff_confidence": _clamp(s.get("payoff_confidence", 5)),
        "three_bullets": _clean_bullets(s.get("three_bullets", [])),
        "judge_notes": s.get("judge_notes", ""),
        "raw_judge_output": raw,
    }


def score_candidate(candidate, llm):
    """Full scoring: hard reject (still judged for audit) + judge scores."""
    kill = hard_reject(candidate)
    scores = judge(candidate, llm)
    bullets = _clean_bullets(candidate.get("three_bullets", []))
    structure_ok = len(bullets) == 3
    if not structure_ok:
        bullets = scores["three_bullets"]
        structure_ok = len(bullets) == 3
    if not kill and not structure_ok:
        kill = KILL_STRUCTURE
    return {
        "idea_id": candidate["idea_id"],
        "niche": candidate["niche"],
        "topic": candidate["topic"],
        "hook_overlay": candidate["hook_overlay"],
        "virality_score": scores["virality_score"],
        "hook_score": scores["hook_score"],
        "payoff": candidate["payoff"],
        "three_bullets": (bullets + [""] * 3)[:3],
        "cta": candidate.get("cta", ""),
        "status": "kill" if kill else "pending",
        "kill_reason": kill,
        "source_video_ids": list(candidate.get("source_video_ids", [])),
        "_audit": {
            "payoff_confidence": scores["payoff_confidence"],
            "judge_notes": scores["judge_notes"],
            "raw_judge_output": scores["raw_judge_output"],
        },
    }
