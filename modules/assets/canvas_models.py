"""Resolve generation choices exclusively against the current Canvas catalog."""
import math

from .canvas_cli import CanvasError


def _same(a, b):
    return str(a).casefold() == str(b).casefold()


def choose_model(catalog, kind, requested=None):
    mode = "t2v" if kind == "video" else "t2i"
    candidates = []
    for item in catalog:
        names = [item["model"], *item.get("aliases", [])]
        matches = (any(_same(requested, n) for n in names) if requested else
                   any("seedance" in n.lower() and "fast" in n.lower() for n in names)
                   if kind == "video" else len(catalog) == 1)
        if not matches:
            continue
        for spec in item.get("modes", []):
            if spec["name"] == mode:
                candidates.append((item["model"], spec))
    if len(candidates) != 1:
        raise CanvasError("model_selection_required",
                          f"set an explicit {kind}_model from the live catalog")
    return candidates[0]


def generation_parameters(shot, selected, resolution="720P", ratio="9:16"):
    model, mode = selected
    specs = {f["flag"].lstrip("-"): f for f in mode.get("flags", [])}
    params = {"model": model, "mode": mode["name"], "prompt": shot["prompt_jimeng"],
              "ratio": ratio, "resolution": resolution, "count": 1}
    refs = mode.get("references", {})
    if refs.get("min", 0) or refs.get("requireAnyOfTypes"):
        raise CanvasError("model_requires_references")
    if shot["asset_type"] == "video":
        spec = specs.get("duration", {})
        target = max(3.0, float(shot["duration_s"]))
        if not math.isfinite(target):
            raise CanvasError("invalid_duration")
        if spec.get("values"):
            durations = sorted(float(v) for v in spec["values"])
            values = [v for v in durations if v >= target]
            if not values:
                raise CanvasError("duration_above_model_limit")
            duration = values[0]
        elif all(k in spec for k in ("min", "max", "step")) and spec["step"] > 0:
            low, high, step = spec["min"], spec["max"], spec["step"]
            duration = low + max(0, math.ceil((target - low) / step)) * step
            if duration > high:
                raise CanvasError("duration_above_model_limit")
        else:
            raise CanvasError("duration_constraints_missing")
        params["duration"] = duration
    for key, value in list(params.items()):
        if key in {"model", "mode"}:
            continue
        if key not in specs:
            raise CanvasError(f"unsupported_model_parameter_{key}")
        spec = specs[key]
        if spec.get("values"):
            matches = [v for v in spec["values"] if _same(value, v)]
            if not matches:
                raise CanvasError(f"unsupported_{key}")
            params[key] = matches[0]
        if key in {"duration", "count"}:
            number = float(value)
            if number < spec.get("min", number) or number > spec.get("max", number):
                raise CanvasError(f"unsupported_{key}")
        if key == "prompt":
            size = len(value.encode("utf-16-le")) // 2
            if size < spec.get("minLength", 0) or size > spec.get("maxLength", size):
                raise CanvasError("prompt_length_out_of_range")
    for key, spec in specs.items():
        if spec.get("required") and key not in params:
            raise CanvasError(f"missing_model_parameter_{key}")
    return params
