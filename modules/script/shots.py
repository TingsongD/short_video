"""M5 shot splitting + visual direction.

Deterministic: sentences -> 4-7 contiguous shots; duration ~ words/2.75s;
shot idx 0 is always the hook and always asset_type=video. With an LLM
attached, per-shot Jimeng prompts/Pexels terms come from the model;
without one, template defaults keep the pipeline runnable offline.
"""
import re

from modules.common.llm import parse_json

from .prompts import VISUAL_SYSTEM
from .write import sentences

WORDS_PER_SEC = 2.75
MIN_SHOTS, MAX_SHOTS = 4, 7
_STOP = {"the", "a", "an", "of", "to", "in", "is", "are", "you", "your",
         "that", "this", "it", "for", "on", "and", "or", "with", "be"}


def _duration(text):
    words = len(re.findall(r"[a-zA-Z0-9']+", text))
    return max(2.0, round(words / WORDS_PER_SEC, 1))


def _split_clauses(sent):
    parts = re.split(r"\s*(?:;|—|,)\s*", sent)
    return [p for p in parts if p.strip()]


def _chunks(items, k):
    """Split `items` into k contiguous groups, sizes differ by <= 1."""
    n = len(items)
    base, extra = divmod(n, k)
    out, i = [], 0
    for g in range(k):
        take = base + (1 if g < extra else 0)
        out.append(items[i:i + take])
        i += take
    return out


def split_shots(script, hook_line):
    """Script -> [{idx, text, duration_s}], 4-7 shots, hook = shot 0."""
    sents = sentences(script)
    if not sents or re.sub(r"\s+", " ", sents[0].strip()) != re.sub(r"\s+", " ", hook_line.strip()):
        raise ValueError("hook must be the first sentence")
    rest = sents[1:]
    while len(sents) < MIN_SHOTS:
        # rare edge: split the longest remaining sentence into clauses
        longest = max(range(1, len(sents)), key=lambda i: len(sents[i]), default=None)
        if longest is None:
            break
        clauses = _split_clauses(sents[longest])
        if len(clauses) < 2:
            break
        sents[longest:longest + 1] = clauses
    k = max(MIN_SHOTS, min(MAX_SHOTS, len(sents)))
    groups = [[sents[0]]] + _chunks(sents[1:], k - 1) if len(sents) > 1 else [sents]
    groups = [g for g in groups if g]
    return [
        {"idx": i, "text": " ".join(g), "duration_s": _duration(" ".join(g))}
        for i, g in enumerate(groups)
    ]


def _fallback_term(text):
    toks = [w for w in re.findall(r"[a-z]+", text.lower())
            if w not in _STOP and len(w) > 2]
    return " ".join(toks[:3]) or "abstract background"


def _template_prompt(text):
    short = " ".join(text.split()[:14])
    return (f"Cinematic vertical 9:16 shot illustrating: {short}. "
            "Dramatic lighting, shallow depth of field, no text overlay.")


def assign_visuals(shots, llm=None):
    """Fill prompt_jimeng / asset_type / pexels_fallback_term on each shot.
    LLM output is validated per-shot; bad entries fall back to templates.
    Hook shot is forced to video regardless of what the model says."""
    visual_list = []
    if llm is not None:
        user = "\n".join(f"shot {s['idx']}: {s['text']}" for s in shots)
        try:
            visual_list = parse_json(llm.complete(VISUAL_SYSTEM, user, temperature=0.0))
        except Exception:
            visual_list = []
    for s in shots:
        v = visual_list[s["idx"]] if s["idx"] < len(visual_list) else {}
        s["prompt_jimeng"] = (v.get("prompt_jimeng") or "").strip() or _template_prompt(s["text"])
        s["asset_type"] = v.get("asset_type") if v.get("asset_type") in ("video", "image") else "video"
        s["pexels_fallback_term"] = (v.get("pexels_fallback_term") or "").strip() or _fallback_term(s["text"])
    shots[0]["asset_type"] = "video"
    return shots
