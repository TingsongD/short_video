"""Reference-vs-source validation (F18 checklist 4): compare declared
garment attributes against product snapshot facts. Missing views stay
uncertainty — never silently inferred.
"""
from ..domain.errors import ContractError

CHECKED_ATTRS = ("color", "pattern", "silhouette", "construction")


def validate_reference(ref, snapshot_facts):
    """ref: VisualReference dict. snapshot_facts: {color, pattern,
    silhouette, construction, claims[], overlays: bool}.
    → {"verdicts": {attr: match|mismatch|unknown_view}, "flags": [...]}"""
    verdicts, flags = {}, []
    attrs = ref.get("attributes") or {}
    for attr in CHECKED_ATTRS:
        declared = attrs.get(attr, {})
        value, state = declared.get("value"), declared.get("state")
        fact = (snapshot_facts or {}).get(attr)
        if state == "unknown" or value in (None, ""):
            verdicts[attr] = "unknown_view"
            flags.append({"flag": "missing_view", "detail":
                          f"{attr} not evidenced in the reference"})
            continue
        if fact in (None, ""):
            # no source fact to compare — the claim is invented
            verdicts[attr] = "mismatch"
            flags.append({"flag": "invented_detail", "detail":
                          f"{attr}={value!r} has no source evidence"})
            continue
        if state == "inferred":
            verdicts[attr] = "unknown_view"
            flags.append({"flag": "inferred_attribute", "detail":
                          f"{attr} marked inferred — needs a real view"})
            continue
        if str(value).casefold() == str(fact).casefold():
            verdicts[attr] = "match"
        else:
            verdicts[attr] = "mismatch"
            flags.append({"flag": "attribute_mismatch", "detail":
                          f"{attr}: ref {value!r} vs source {fact!r}"})
    claims = set(snapshot_facts.get("claims") or [])
    extra = attrs.get("extra_details") or []
    for d in extra:
        if d not in claims:
            flags.append({"flag": "invented_detail", "detail":
                          f"detail {d!r} absent from source claims"})
    if attrs.get("copied_overlay"):
        flags.append({"flag": "copied_source_overlay", "detail":
                      "source overlay/text embedded in the reference"})
    if ref.get("role", "").startswith("presenter") and \
            ref.get("origin") == "seed_frame":
        flags.append({"flag": "seed_presenter_copied", "detail":
                      "presenter reference derives from the seed"})
    return {"verdicts": verdicts, "flags": flags}
