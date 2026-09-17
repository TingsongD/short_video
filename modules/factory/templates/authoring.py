"""Blueprint → FormatTemplate authoring (F13 checklist 1–3).

Structure is reused; source-specific content is not. The template keeps
the blueprint hash for provenance, but slots carry roles/timing/
constraints — never transcript text, product names or presenter
identity from the seed.
"""
import copy

from ..domain.errors import ContractError
from ..domain.records import FormatTemplate, Slot
from ..store.uow import utcnow

ROLE_KIND = {"hook": "hook", "product_reveal": "product",
             "proof": "proof", "payoff": "proof", "cta": "cta",
             "transition": "transition", "body": "product"}
REFERENCE_FOR = {"product": "image", "proof": "image"}

MIN_RATIO, MAX_RATIO = 0.5, 1.5

DEFAULT_CONSTRAINTS = {
    "caption": {"region": "lower_third", "safe_zone": "center_80",
                "font": None, "max_chars_per_line": 42},
    "music": {"role": "bed", "duck_under_speech": True},
    "transitions": {"default": "cut", "handle_frames": 0},
}


def author_from_blueprint(bp, template_id, created_at=None):
    """Accepted blueprint → candidate template draft (not persisted —
    TemplateService owns storage)."""
    if bp.status != "accepted":
        raise ContractError("blueprint_not_accepted", "status",
                            bp.status)
    slots = []
    for b in bp.beats:
        kind = ROLE_KIND.get(b.role, "product")
        frames = b.target.length if b.target else 0
        slots.append(Slot(
            id=f"s-{b.id}", kind=kind, frames=frames,
            min_frames=max(1, int(frames * MIN_RATIO)),
            max_frames=int(frames * MAX_RATIO + 0.5),
            required_reference=REFERENCE_FOR.get(kind, "none"),
            effects=["static_image"] if kind in ("product", "proof")
            else [],
            transition_out="cut",
            content={"beat_role": b.role}))
    return FormatTemplate(
        schema_version="format_template.v1", id=template_id,
        created_at=created_at or utcnow(), revision=1,
        status="candidate", slots=slots,
        constraints=copy.deepcopy(DEFAULT_CONSTRAINTS), renderer="hypit",
        derived_from_blueprint=bp.content_hash)
