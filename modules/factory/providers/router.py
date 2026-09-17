"""Provider router (F15 checklist 4–6): deterministic route decisions
from plan policy + capability evidence + authorization.

- Every candidate gets an explicit verdict; the report says *why* a
  cheaper or faster route was not eligible — the dashboard never has
  to guess.
- Duration rounds UP only to a supported catalog choice; if no native
  duration covers the request, the verdict names `duration_uncovered`
  (split/replan) rather than silently shortening.
- Fallback requires the policy AND a terminal original — the router
  asks the Executor whether the original attempt is still unresolved
  and suppresses paid replacement while it is.
- Independent money: a credits provider can never cover a USD request
  and vice versa; no implicit upgrade.
"""
import json

from ..domain.errors import ContractError
from ..domain.money import Money
from ..domain.records import GenerationRequest
from ..store.uow import utcnow
from .catalog import CapabilityCatalog

CHOICE_PROVIDERS = {"jimeng": "jimeng_canvas", "vertex": "google_vertex"}
MIN_SUPPORT = "observed"


class ProviderRouter:
    def __init__(self, db, adapters, catalog=None, executor=None):
        self.db = db
        self.adapters = adapters
        self.catalog = catalog or CapabilityCatalog(db)
        self.executor = executor

    # --------------------------------------------------------- route

    def route(self, request, policy, authorization=None, now=None):
        """→ {"provider", "model", "duration_s", "price", "reason",
        "rejected": {provider: [why_not...]}} or raise no_route."""
        now = now or utcnow()
        candidates = self._candidates(policy)
        rejected = {}
        for provider in candidates:
            verdict = self._evaluate(provider, request, policy,
                                     authorization, now)
            if verdict["eligible"]:
                return {"provider": provider,
                        "model": verdict["model"],
                        "duration_s": verdict["duration_s"],
                        "price": verdict["price"],
                        "input_mode": verdict["input_mode"],
                        "reason": verdict["reason"],
                        "rejected": rejected}
            rejected[provider] = verdict["why_not"]
        raise ContractError("no_eligible_route", "provider_policy",
                            json.dumps(rejected))

    def _candidates(self, policy):
        choice = getattr(policy, "choice", "jimeng")
        if choice == "jimeng_with_vertex_fallback":
            return ["jimeng_canvas", "google_vertex"]
        return [CHOICE_PROVIDERS[choice]]

    def _evaluate(self, provider, request, policy, authorization, now):
        why = []
        adapter = self.adapters.get(provider)
        if adapter is None:
            return {"eligible": False, "why_not": ["adapter_missing"]}
        # plan lock: a frozen plan pins provider/model — confound guard
        if request.provider and request.provider != provider:
            return {"eligible": False,
                    "why_not": [f"plan_locked_to:{request.provider}"]}
        allowed = (policy.allowed_models or {}).get(provider)
        if allowed:
            models = list(allowed)
        elif request.model:
            models = [request.model]
        else:
            models = list(getattr(adapter, "models", []) or [])
        if request.model and request.model not in models:
            return {"eligible": False,
                    "why_not": [f"model_locked_to:{request.model}"]}
        if authorization and authorization.allowed_providers and \
                provider not in authorization.allowed_providers:
            return {"eligible": False,
                    "why_not": ["not_in_scope"]}
        ready = adapter.readiness()
        if not ready.get("ready"):
            # a provider that can't authenticate/quote is ineligible —
            # not merely a model-level problem
            return {"eligible": False,
                    "why_not": [f"not_ready:{ready.get('reason', '')}"]}
        best = None
        for model in models:
            v = self._model_verdict(adapter, provider, model, request,
                                    policy, authorization, now)
            if v["eligible"]:
                best = v
                break
            why.extend(v["why_not"])
        if best is None:
            return {"eligible": False, "why_not": why or ["no_model"]}
        best["reason"] = f"policy:{getattr(policy, 'choice', '')}"
        return best

    def _model_verdict(self, adapter, provider, model, request, policy,
                       authorization, now):
        why = []
        input_mode = self._input_mode(request)
        entry = self.catalog.latest(provider, model,
                                    request.region, input_mode, now)
        if entry is None:
            why.append(f"no_capability_snapshot:{model}:{input_mode}")
            return {"eligible": False, "why_not": why}
        if entry["stale"]:
            why.append("stale_capability_snapshot")
            return {"eligible": False, "why_not": why}
        snap = entry["snapshot"]
        if snap.support not in ("observed", "qualified"):
            why.append(f"unqualified_support:{snap.support}")
            return {"eligible": False, "why_not": why}
        caps = snap.capabilities or adapter.capabilities(model)
        problems = adapter.validate(request, caps)
        why.extend(f"model:{model}:{p}" for p in problems)
        duration = self._pick_duration(request, caps)
        if duration is None:
            why.append(f"model:{model}:duration_uncovered")
        price = None
        if duration is not None and not problems:
            price = adapter.price(request, duration, model=model)
            if authorization:
                cap = (authorization.caps or {}).get(price.unit)
                if cap is not None and price.amount > cap:
                    why.append(f"model:{model}:exceeds_cap:{price.unit}")
        if why:
            return {"eligible": False, "why_not": why}
        return {"eligible": True, "model": model,
                "duration_s": duration, "price": price,
                "input_mode": input_mode, "why_not": []}

    @staticmethod
    def _input_mode(request):
        roles = set((request.reference_roles or {}).values())
        if "video" in roles:
            return "video_ref"
        if "image" in roles:
            return "image_ref"
        return "text"

    @staticmethod
    def _pick_duration(request, caps):
        for d in sorted(caps.get("durations_s") or []):
            if d >= request.requested_duration_s:
                return d
        return None

    # -------------------------------------------------- eligibility

    def fallback_blocked_reason(self, attempt_id):
        """Why a fallback is suppressed: the original attempt isn't
        terminal. None when fallback is allowed."""
        if self.executor is None:
            return "no_executor"
        if not self.executor.fallback_allowed(attempt_id):
            return "original_unresolved"
        return None
