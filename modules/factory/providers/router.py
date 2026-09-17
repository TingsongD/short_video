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
    def __init__(self, db, adapters, catalog=None, executor=None, live=False):
        self.db = db
        self.live = live
        self.adapters = adapters
        self.catalog = catalog or CapabilityCatalog(db)
        self.executor = executor

    def preflight(self, provider, model, request, duration, experiment_id='', authorization=None):
        """Production boundary: validate the pinned route without quoting or effects."""
        from .base import GenerationAdapter
        adapter = self.adapters.get(provider)
        if adapter is None: raise ContractError('generation_route_unavailable','provider',provider)
        if request.get('model',model) != model or request.get('provider',provider) != provider:
            raise ContractError('pinned_route_mismatch','provider/model')
        settings=request.get('settings') or {}
        roles=request.get('reference_roles') or {}
        for i,ref in enumerate(request.get('refs') or []):
            if not isinstance(ref,dict) or ref.get('kind') not in ('image','video','audio'):
                raise ContractError('invalid_reference','refs')
            roles={**roles,str(i):ref['kind']}
        neutral=GenerationRequest(schema_version='generation_request.v1',id='preflight',created_at='',
            provider=provider,model=model,requested_duration_s=duration,reference_roles=roles,
            region=request.get('region',getattr(adapter,'location','')),
            aspect=settings.get('aspect',request.get('aspect','9:16')),
            resolution=settings.get('resolution',request.get('resolution','720p')),
            native_audio_policy=request.get('native_audio_policy','strip'))
        entry=self.catalog.latest(provider,model,neutral.region,self._input_mode(neutral),utcnow())
        if not entry or entry['stale'] or not entry['snapshot'].valid_until:
            raise ContractError('capability_evidence_required','provider/model/input_mode')
        if entry['snapshot'].support not in (('qualified',) if self.live else ('observed','qualified')):
            raise ContractError('route_not_qualified','provider/model/input_mode')
        caps=entry['snapshot'].capabilities
        problems=GenerationAdapter.validate(adapter,neutral,caps)
        if duration not in (caps.get('durations_s') or []):problems.append('unsupported_duration')
        if problems:raise ContractError('unsupported_generation_settings','request',','.join(problems))
        if experiment_id:
            rows=self.db.conn.execute("SELECT a.id FROM attempts a JOIN intents i ON json_extract(i.body,'$.attempt_id')=a.id JOIN jobs j ON j.id=a.job_id WHERE j.experiment_id=? AND json_extract(i.body,'$.provider')<>? AND i.kind='generation'",(experiment_id,provider)).fetchall()
            for row in rows:
                if self.fallback_blocked_reason(row['id']):raise ContractError('original_unresolved','attempt_id',row['id'])
        if authorization and (provider not in authorization.allowed_providers or model not in authorization.allowed_models.get(provider,[])):
            raise ContractError('route_outside_authority','provider/model')
        return {'provider':provider,'model':model,'input_mode':self._input_mode(neutral),'capability_revision':entry['revision']}

    # --------------------------------------------------------- route

    def route(self, request, policy, authorization=None, now=None, original_attempt_id=None):
        """→ {"provider", "model", "duration_s", "price", "reason",
        "rejected": {provider: [why_not...]}} or raise no_route."""
        now = now or utcnow()
        if original_attempt_id and self.fallback_blocked_reason(original_attempt_id):
            raise ContractError("original_unresolved", "attempt_id", original_attempt_id)
        if self.live and authorization is None:
            raise ContractError("authority_required", "routing")
        if authorization and (authorization.status != "authorized" or not authorization.valid_until or authorization.valid_until <= now):
            raise ContractError("authorization_expired_or_inactive", "routing")
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
        if request.model:
            if request.model not in models:
                return {"eligible": False, "why_not": [f"model_locked_to:{request.model}"]}
            models = [request.model]
        if authorization:
            models = [m for m in models if m in (authorization.allowed_models or {}).get(provider, [])]
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
        if snap.support not in (("qualified",) if self.live else ("observed", "qualified")):
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
                if cap is None:
                    why.append(f"model:{model}:no_authorized_cap:{price.unit}")
                elif price.amount > cap:
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
