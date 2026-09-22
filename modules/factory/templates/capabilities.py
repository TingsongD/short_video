"""Renderer capability manifest (F13 checklist 4).

Effects are declarative names; the report routes each slot to the
cheapest renderer that supports its whole effect set. Unsupported
effects are named, never silently dropped.
"""

from ..composition.compiler import RENDERER_EFFECTS
RENDERERS = {name: {"effects":effects,"animated_overlay":False} for name,effects in RENDERER_EFFECTS.items()}



def renderer_order(policy=None):
    if policy is None:
        return ('ffmpeg_fast', 'hypit')
    if policy == 'hypit_primary.v1':
        return ('hypit',)
    from ..domain.errors import ContractError
    raise ContractError('unsupported_renderer_policy', 'renderer', str(policy))


def capability_report(slots, renderer_policy=None):
    """→ {routes: {slot_id: renderer}, preferred, unsupported: [...]}.
    preferred is the cheapest renderer covering EVERY slot."""
    order = renderer_order(renderer_policy)
    routes, unsupported = {}, []
    for s in slots:
        want = set(s.effects or []) | (
            {s.transition_out} if s.transition_out != "none" else set())
        chosen = None
        for rname in order:
            if want <= RENDERERS[rname]["effects"]:
                chosen = rname
                break
        if chosen is None:
            unsupported.append({"slot": s.id,
                                "effects": sorted(want - set().union(
                                    *[r["effects"]
                                      for r in RENDERERS.values()]))})
            routes[s.id] = "unsupported"
        else:
            routes[s.id] = chosen
    used = set(routes.values()) - {"unsupported"}
    preferred = ("unsupported" if unsupported else
                 "ffmpeg_fast" if used == {"ffmpeg_fast"} else "hypit")
    return {"routes": routes, "preferred": preferred,
            "unsupported": unsupported}
