"""Deterministic script adaptation for the automatic pipeline.

A stays verbatim to the observed narration — honest close adaptation;
only the qualified LLM route may paraphrase. B/C/D each edit ONE beat
using only words present in the source transcript: tighten, clarify or
call back. No template here invents a fact, a number or a promise.
"""
import math
import re

from ...script.voicetext import clean as _normalize
from ..analysis.analyzer import assign_passages
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
# Pre-spend filter for GENERATED copy only. A conservative narration pace;
# the real gate stays the measured waveform fit (audio/fit.py). A false
# reject only falls back to source-derived copy; a false accept is still
# caught by the measured fit, so uncertainty never becomes approval.
WPS_ESTIMATE = 2.5


def word_budget(beat, source_copy):
    """Most words a beat can carry: whichever is larger of what the source
    speaker actually said in it or the beat's target seconds at a
    conservative pace, stretched by the documented max rate."""
    from ..audio.fit import RATE_MAX
    target_s = float(beat.get("target_s") or
                     (beat["end_s"] - beat["start_s"]))
    source_words = len(str(source_copy or "").split())
    return int(math.ceil(max(source_words, target_s * WPS_ESTIMATE)
                         * RATE_MAX))


def _passage_intervals(transcript):
    """Passages with usable timing → [{start_s,end_s,text}]."""
    out = []
    for t in transcript:
        text = str(t.get("text") or "").strip()
        if not text:
            continue
        start = t.get("start_s")
        end = t.get("end_s")
        if start is None:
            start = t.get("start", 0)
        if end is None:
            end = t.get("end", start)
        try:
            start, end = float(start), float(end)
        except (TypeError, ValueError):
            continue
        out.append({"start_s": start, "end_s": end, "text": text,
                    "words": t.get("words") or []})
    return out


def _assign_script_passages(beats, transcript):
    """Keep each sentence intact, using complete timed-word evidence when
    available. Equal word votes avoid treating a long silence-alignment word
    as many seconds of spoken evidence. Ties keep legacy start ownership.
    This chooses a script scene; it does not certify or rewrite word timing.
    """
    passages = _passage_intervals(transcript)
    result = {"by_beat": {b['id']: [] for b in beats}, "unplaced": [],
              "timing_warnings": []}
    for passage in passages:
        fallback = assign_passages(beats, [passage])
        owner = next((bid for bid, entries in fallback['by_beat'].items() if entries), None)
        words = passage['words']
        complete = (isinstance(words, list) and words and
            all(isinstance(w, dict) for w in words) and
            _norm_words(' '.join(str(w.get('text', w.get('word', ''))) for w in words)) ==
            _norm_words(passage['text']))
        votes = {}
        last_start = -1
        for word in words if complete else []:
            start = word.get('start_s', word.get('start_seconds', word.get('start')))
            end = word.get('end_s', word.get('end_seconds', word.get('end')))
            if not (type(start) in (int, float) and type(end) in (int, float)
                    and math.isfinite(start) and math.isfinite(end)
                    and passage['start_s'] <= start < end <= passage['end_s']
                    and start >= last_start):
                votes = {}
                break
            last_start = start
            if end - start > 2:
                result['timing_warnings'].append(
                    f"Passage at {passage['start_s']:.3f}s has a word interval "
                    "longer than two seconds; original timing retained, not certified as repaired.")
            midpoint = (start + end) / 2
            beat = next((b for b in beats if b['start_s'] <= midpoint < b['end_s']), None)
            if beat is None:
                votes = {}
                break
            votes[beat['id']] = votes.get(beat['id'], 0) + 1
        if votes:
            winners = [bid for bid, count in votes.items() if count == max(votes.values())]
            if len(winners) == 1:
                owner = winners[0]
        if owner is None:
            result['unplaced'].append(passage)
        else:
            result['by_beat'][owner].append(passage)
    result['timing_warnings'] = list(dict.fromkeys(result['timing_warnings']))
    return result


def beat_copy(beat, transcript, _assigned=None):
    """Assign each transcript passage to exactly one beat — verbatim.

    A passage can be longer than a very short visual beat.  Using any
    overlap (``end > start`` and ``start < end``) would copy that passage
    into every adjacent beat, duplicating narration across the draft.
    Ownership is single. Complete timed-word evidence can select the scene
    containing most words; otherwise passage start, midpoint and end remain
    the fallback. Unplaced passages are reported, never silently dropped.
    """
    if _assigned is None:
        _assigned = _assign_script_passages([beat], transcript)
    return " ".join(p["text"] for p in
                    _assigned["by_beat"].get(beat.get("id")) or [])


def _norm_words(text):
    """Case/punctuation-insensitive word list for the variation
    equivalence check — 'Watch this dog!' and 'watch this dog' are the
    same spoken line, not a variation."""
    return re.sub(r"[^\w\s]", "",
                  _normalize(str(text))).lower().split()


def validate_variations(sc, beats):
    """The experiment contract: B/C/D must each carry one *meaningful*
    declared change — copy that still differs after text normalization
    (case/punctuation/filler-insensitive) and a non-empty alternate
    footage direction. Normalization-equivalent wording is not a
    variation. → [problems]; empty means the quartet is valid."""
    problems = []
    changed = sc.get("changed") or {}
    factors = sc.get("factors") or {}
    for key in ("B", "C", "D"):
        beat_id = changed.get(key)
        if not beat_id:
            problems.append(f"{key}: no changed beat declared")
            continue
        new_copy = str((sc.get(key) or {}).get(beat_id) or "").strip()
        control = str((sc.get("A") or {}).get(beat_id) or "")
        if not new_copy:
            problems.append(f"{key}:{beat_id}: changed beat has no copy")
        elif _norm_words(new_copy) == _norm_words(control):
            problems.append(
                f"{key}:{beat_id}: changed copy is normalization-"
                "equivalent to the control — not a real variation")
        if not DIRECTIONS.get(factors.get(key) or ""):
            problems.append(f"{key}: no alternate footage direction")
    return problems


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
    assigned = _assign_script_passages(beats, transcript)
    a = {b["id"]: " ".join(
        p["text"] for p in assigned["by_beat"].get(b["id"]) or [])
        for b in beats}
    n = len(beats)
    out = {"A": a, "B": {}, "C": {}, "D": {}, "hypotheses": {},
           "factors": {}, "metrics": {}, "changed": {},
           "unplaced": [p["text"] for p in assigned["unplaced"]],
           "timing_warnings": assigned["timing_warnings"]}
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


def variant_picture_request(beat, key, settings=None):
    """Variant identity lives in the actual creative request, not only labels."""
    looks = {
        'B': 'Close immersive handheld camera, warm daylight, expressive reactions.',
        'C': 'Steady medium-wide camera, cool daylight, clear step-by-step action.',
        'D': 'Low-angle cinematic tracking, golden-hour light, playful anticipation.',
    }
    request = picture_request(beat, FACTORS[key], settings)
    request['prompt'] += (' Variant ' + key + ' continuous visual treatment: ' + looks[key]
        + ' Keep character species, wardrobe, markings and setting consistent across this variant.'
        + ' No subtitles, captions, title cards, decorative lettering, logos or watermarks.'
        + ' Convey the story through action only; text will be added separately.')
    return request


def llm_request(model, beats, transcript, a_copy, changed):
    """Script-adaptation request for the qualified analysis route —
    text-only generateContent on the same provider/model."""
    return {"task": "adapt_script", "model": model,
            "script_input": {
                "beats": [{"id": b["id"], "role": b["role"],
                           "start_s": b["start_s"], "end_s": b["end_s"],
                           "max_words": word_budget(b, a_copy.get(b["id"], "")),
                           "visual_event": b.get("visual_event", "")}
                          for b in beats],
                "transcript": transcript,
                "control_copy": a_copy,
                "treatments": {"B": {"beat": changed["B"], "goal": "stronger curiosity hook"},
                               "C": {"beat": changed["C"], "goal": "clearer body explanation"},
                               "D": {"beat": changed["D"], "goal": "stronger payoff and loop"}}}}


# Delivery resolutions the generation routes declare, mapped to the
# pixel height of the *long* side's portrait complement: "720p" means a
# 720-wide portrait (720×1280), matching provider conventions. Unknown
# labels are refused — output dimensions are never guessed.
_RESOLUTION_PX = {"360p": 360, "480p": 480, "540p": 540, "720p": 720,
                  "1080p": 1080, "1440p": 1440, "2160p": 2160,
                  "4k": 2160, "2k": 1440}


def output_dims(aspect, resolution):
    """Frozen output profile dimensions for a declared aspect+resolution.
    → (width, height), both even. A resolution may name a standard label
    ("720p") or declare exact pixels ("180x320") — both are honored
    verbatim. ContractError when neither parses — the profile is a
    declaration, not a probe of whichever input happened to render
    first."""
    res_label = str(resolution).strip().lower()
    explicit = re.fullmatch(r"(\d+)x(\d+)", res_label)
    if explicit:
        w, h = int(explicit[1]), int(explicit[2])
        if w > 0 and h > 0:
            return w - w % 2, h - h % 2
        raise ContractError("unknown_resolution", "resolution",
                            str(resolution))
    try:
        aw, ah = (int(x) for x in str(aspect).split(":"))
        assert aw > 0 and ah > 0
    except (ValueError, AssertionError):
        raise ContractError("unknown_aspect", "aspect", str(aspect))
    res = _RESOLUTION_PX.get(res_label)
    if res is None:
        raise ContractError("unknown_resolution", "resolution",
                            str(resolution))
    if aw >= ah:                        # landscape or square
        height = res
        width = int(round(res * aw / ah / 2) * 2)
    else:                               # portrait
        width = res
        height = int(round(res * ah / aw / 2) * 2)
    return width, height
