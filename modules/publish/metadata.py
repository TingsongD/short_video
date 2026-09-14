"""M9 metadata: title/caption/hashtags from idea + format CTA (LLM, temp 0).

Enforced: title <=100 chars, <=15 hashtags (normalized, deduped),
a CTA keyword must appear in the caption (else the format's CTA pattern
is appended).
"""
import json
import re

from modules.common.llm import parse_json

MAX_TITLE = 100
MAX_HASHTAGS = 15
CTA_WORDS = ("follow", "subscribe", "watch", "comment", "share", "save")

META_SYSTEM = """You write YouTube Shorts metadata for a faceless channel.
Return ONLY JSON:
{"title": str (<=100 chars, specific, no clickbait lies),
 "caption": str (1-2 lines + a CTA),
 "hashtags": [str] (3-8, topical, no # prefix)}"""


def _norm_tags(tags):
    out, seen = [], set()
    for t in tags:
        tag = re.sub(r"[^a-z0-9_]", "", str(t).lower().lstrip("#"))
        if tag and tag not in seen:
            seen.add(tag)
            out.append(tag)
    return out[:MAX_HASHTAGS]


def _has_cta(caption):
    return any(w in caption.lower() for w in CTA_WORDS)


def build_metadata(idea, format_entry, llm):
    user = (
        f"Niche: {idea['niche']}\nTopic: {idea['topic']}\n"
        f"Hook: {idea['hook_overlay']}\nPayoff: {idea['payoff']}\n"
        f"CTA pattern: {format_entry.get('cta_pattern', '')}\n"
        f"Suggested CTA: {idea.get('cta', '')}"
    )
    raw = llm.complete(META_SYSTEM, user, temperature=0.0)
    d = parse_json(raw)
    title = str(d["title"]).strip()
    if not title or len(title) > MAX_TITLE:
        raise ValueError(f"title empty or > {MAX_TITLE} chars")
    caption = str(d.get("caption", "")).strip()
    if not _has_cta(caption):
        cta = format_entry.get("cta_pattern") or idea.get("cta") or "Follow for more"
        caption = f"{caption} {cta}".strip()
    return {
        "title": title,
        "caption": caption,
        "hashtags": _norm_tags(d.get("hashtags", [])),
    }
