"""Generation adapter contract (F15): the neutral surface every
provider implements. Validation is side-effect-free; `prepare` may
cross the network (and therefore rides F07 recovery); `submit` is the
billable boundary — intent must already be persisted by the caller.
"""
from ..domain.errors import ContractError
from ..testing.fakes import ProviderError


class GenerationAdapter:
    """Interface, not a base for reuse: each adapter owns its payloads."""
    name = ""
    pricing_kind = ""                # native_quote | usage_estimate
    unit = ""                        # money unit this adapter charges in

    def readiness(self):
        """→ {"ready": bool, "reason": str} — auth/quota state only."""
        raise NotImplementedError

    def capabilities(self, model):
        """→ {"durations_s":[...], "aspects":[...], "resolutions":[...],
        "references": {"image": n, "video": n}, "audio": bool} for an
        exact model name. Unknown model → ProviderError."""
        raise NotImplementedError

    def validate(self, request, capabilities):
        """Side-effect-free request/capability check → [problems]."""
        problems = []
        if request.aspect not in (capabilities.get("aspects") or []):
            problems.append("unsupported_aspect")
        if request.resolution not in \
                (capabilities.get("resolutions") or []):
            problems.append("unsupported_resolution")
        refs = capabilities.get("references") or {}
        roles = request.reference_roles or {}
        need = {}
        for r in roles.values():
            need[r] = need.get(r, 0) + 1
        for kind, n in need.items():
            if refs.get(kind, 0) < n:
                problems.append(f"unsupported_reference_{kind}")
        if request.native_audio_policy == "keep" and not \
                capabilities.get("audio"):
            problems.append("audio_not_supported")
        return problems

    def price(self, request, duration_s, model=None):
        """→ Money for one submitted request at the chosen duration."""
        raise NotImplementedError

    # -- remote lifecycle (caller wraps in Executor) ------------------
    def prepare(self, request):
        raise NotImplementedError

    def submit(self, request, price=None):
        raise NotImplementedError

    def observe(self, operation_id):
        raise NotImplementedError

    def poll(self, operation_id):
        """Executor-facing alias for observe — one remote-state read."""
        return self.observe(operation_id)

    def download(self, operation_id, destination=None):
        raise NotImplementedError

    def reconcile(self, operation_id=None, request_hash=None):
        raise NotImplementedError

    def cancel(self, operation_id):
        raise ContractError("cancel_not_supported", "provider",
                            self.name)
