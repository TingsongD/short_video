"""Deterministic script adaptation for the automatic pipeline.

A stays verbatim to the observed narration — honest close adaptation;
only the qualified LLM route may paraphrase. B/C/D each edit ONE beat
using only words present in the source transcript: tighten, clarify or
call back. No template here invents a fact, a number or a promise.
"""
from ..domain.errors import ContractError

STYLE = ("Vertical 9:16 social footage, original or authorized fictional "
         "characters, one consistent presenter across scenes, natural "
         "lighting, no on-screen text, logos or watermarks.")
DIRECTIONS = {
    "control": "",
    "hook": ("Tighter opening composition, an immediate expressive "
             "reaction, energetic camera blocking."),
    "body": ("Alternate demonstration angle with clearer action, prop "
             "interaction and visual contrast."),
    "ending": ("Alternate payoff composition, a stronger final reaction, "
               "a clear open-loop ending image."),
}
FILLERS = ("so ", "and ", "but ", "actually ", "basically ", "really ",
           "just ", "well ", "now ", "okay ", "ok ", "like, ")
FACTORS = {"B": "hook", "C": "body", "D": "ending"}
METRICS = {"B": "retention", "C": "retention", "D": "completion"}


def beat_copy(beat, transcript):
    """Words spoken inside the beat's source window — verbatim."""
    s, e = beat["start_s"], beat["end_s"]
    parts = [t["text"].strip() for t in transcript
             if t.get("end_s", 0) > s and t.get("start_s", 0) < e
             and str(t.get("text") or "").strip()]
    return " ".join(parts)


def _clauses(text):
    out, cur = [], ""
    for ch in text:
        cur += ch
        if ch in ".!?;":
            out.append(cur.strip())
            cur = ""
    if cur.strip():
        out.append(cur.strip())
    return [c for c in out if c]


def tighten_hook(text):
    """Reach the point sooner: keep the first clause(s), drop the wind-up."""
    clauses = _clauses(text)
    if not clauses:
        return text
    keep = clauses[0]
    i = 1
    while len(keep) < 40 and i < len(clauses):
        keep += " " + clauses[i]
        i += 1
    return keep


def tighten_body(text):
    """Clearer explanation: strip discourse fillers, keep every fact."""
    words = text.split()
    cleaned = " ".join(words)
    low = cleaned.lower()
    for f in FILLERS:
        if low.startswith(f):
            cleaned = cleaned[len(f):]
            low = cleaned.lower()
            break
    for marker in (" so ", " and then ", " basically ", " actually ",
                   " really ", " just "):
        cleaned = cleaned.replace(marker, " ")
    return " ".join(cleaned.split())


def payoff_callback(text, hook_text):
    """Natural loop: end by calling back the actual opening words."""
    clauses = _clauses(text)
    hook = _clauses(hook_text)
    if not clauses or not hook:
        return text
    body = " ".join(clauses)
    if hook[0].lower() in body.lower():
        return body
    return f"{body} {hook[0]}"


def changed_index(key, n):
    return {"B": 0, "C": n // 2, "D": n - 1}[key]


def adapt(beats, transcript):
    """beats: [{id,role,start_s,end_s,visual_event}] in order.
    transcript: [{start_s,end_s,text}].
    → {A:{seg:copy}, B:{seg:copy}, C:{...}, D:{...}, hypotheses:{...}}
    B/C/D dicts contain ONLY their changed beat's copy."""
    if not beats:
        raise ContractError("script_no_beats", "beats")
    a = {b["id"]: beat_copy(b, transcript) for b in beats}
    n = len(beats)
    out = {"A": a, "B": {}, "C": {}, "D": {}, "hypotheses": {},
           "factors": {}, "metrics": {}, "changed": {}}
    for key in ("B", "C", "D"):
        idx = changed_index(key, n)
        beat = beats[idx]
        original = a[beat["id"]]
        if key == "B":
            new = tighten_hook(original)
        elif key == "C":
            new = tighten_body(original)
        else:
            new = payoff_callback(original, a[beats[0]["id"]])
        out[key][beat["id"]] = new
        out["changed"][key] = beat["id"]
        out["factors"][key] = FACTORS[key]
        out["metrics"][key] = METRICS[key]
    out["hypotheses"] = {
        "B": ("A tighter opening line with alternate opening footage "
              "reaches the point sooner and improves first-seconds "
              "retention versus the control."),
        "C": ("A clearer, tighter delivery of the body beat with "
              "alternate demonstration footage improves mid-video "
              "retention versus the control."),
        "D": ("An ending that calls back to the opening with alternate "
              "payoff footage improves completion and replay versus "
              "the control."),
    }
    return out


def picture_request(beat, factor="control", settings=None):
    event = beat.get("visual_event") or f"{beat.get('role', 'scene')} moment"
    prompt = f"{STYLE} Depict: {event}."
    direction = DIRECTIONS.get(factor, "")
    if direction:
        prompt += " " + direction
    return {"kind": "video", "mode": "t2v", "prompt": prompt,
            "settings": dict(settings or {"aspect": "9:16"})}


def llm_request(model, beats, transcript, a_copy, changed):
    """Script-adaptation request for the qualified analysis route —
    text-only generateContent on the same provider/model."""
    return {"task": "adapt_script", "model": model,
            "script_input": {
                "beats": [{"id": b["id"], "role": b["role"],
                           "start_s": b["start_s"], "end_s": b["end_s"],
                           "visual_event": b.get("visual_event", "")}
                          for b in beats],
                "transcript": transcript,
                "control_copy": a_copy,
                "treatments": {"B": {"beat": changed["B"], "goal": "stronger curiosity hook"},
                               "C": {"beat": changed["C"], "goal": "clearer body explanation"},
                               "D": {"beat": changed["D"], "goal": "stronger payoff and loop"}}}}
