"""M5 script writing: LLM writes a 60-110 word script — hook verbatim first,
3 format beats, loop/CTA ending. Output is validated; failures raise."""
import json
import re

from .prompts import WRITE_SYSTEM

MIN_WORDS, MAX_WORDS = 60, 110


def word_count(text):
    return len(re.findall(r"[a-zA-Z0-9']+", text))


def sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]


def _norm(s):
    return re.sub(r"\s+", " ", s.strip())


def validate_script(script, hook_line):
    wc = word_count(script)
    if not (MIN_WORDS <= wc <= MAX_WORDS):
        raise ValueError(f"script {wc} words outside {MIN_WORDS}-{MAX_WORDS}")
    sents = sentences(script)
    if not sents or _norm(sents[0]) != _norm(hook_line):
        raise ValueError("hook is not the first sentence of the script")
    return script


def write_script(idea, format_entry, hook_line, llm):
    user = (
        f"Hook line (verbatim first sentence): {hook_line}\n"
        f"Format '{format_entry['name']}' beats: {json.dumps(format_entry['beats'])}\n"
        f"Format CTA pattern: {format_entry.get('cta_pattern', '')}\n"
        f"Idea topic: {idea['topic']}\nPayoff to deliver: {idea['payoff']}\n"
        f"Beats material: {json.dumps(idea.get('three_bullets', []))}\n"
        f"CTA: {idea.get('cta', '')}"
    )
    script = llm.complete(WRITE_SYSTEM, user, temperature=0.0).strip()
    return validate_script(script, hook_line)
