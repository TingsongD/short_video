"""Production asset gate: Canvas first, explicit manual/stock substitution."""
from modules.assets.__main__ import collect, service
from modules.assets.canvas_cli import CanvasError
from modules.assets.canvas_state import atomic_json
from modules.assets.queue import render_cards
from .pipeline import ReviewRequired


def production_assets(shot_list, ctx, base):
    video_id = shot_list["video_id"]
    folder = render_cards(shot_list, base=base)
    doc = collect(video_id, base=base)
    if doc["complete"]:
        return doc
    cfg = ctx["config"]
    provider = ctx.get("asset_provider", cfg.get("assets", {}).get("provider", "jimeng-canvas"))
    fallback = ctx.get("asset_fallback", "none")
    report = None
    if provider == "jimeng-canvas":
        canvas = ctx.get("canvas_assets") or service(cfg, base)
        try:
            # Existing operations are only inspected/waited/downloaded on resume.
            if canvas.path(video_id).exists():
                report = canvas.resume(video_id, wait_seconds=ctx.get("canvas_wait_seconds", 45))
            report = canvas.prepare(shot_list)
            ceiling = ctx.get("jimeng_credit_ceiling")
            if ceiling is not None and not report["complete"]:
                report = canvas.generate(video_id, ceiling,
                                         wait_seconds=ctx.get("canvas_wait_seconds", 45))
        except CanvasError as error:
            report = {"video_id": video_id, "complete": False, "error": str(error),
                      "action": "resolve Canvas status or import the missing shots manually"}
        atomic_json(folder.parent / "asset_status.json", report)
        doc = collect(video_id, base=base)
    elif provider != "manual":
        raise ValueError(f"unsupported asset provider: {provider}")
    if not doc["complete"] and fallback == "stock":
        doc = collect(video_id, base=base, fallback="stock", pexels=ctx.get("pexels"))
    if doc["complete"]:
        return doc
    message = (f"assets incomplete: shots {doc['missing_shots']}; import into {folder}, "
               f"then resume production. Stock substitution requires --asset-fallback stock.")
    if report is not None:
        message += (" Review asset_status.json and all quotes. To approve unsubmitted shots, "
                    "use assets generate with --credit-ceiling, or resume production with "
                    "--jimeng-credit-ceiling. Unknown/failed shots require review.")
        raise ReviewRequired(message, report)
    raise RuntimeError(message)
