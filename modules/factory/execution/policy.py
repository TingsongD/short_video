"""Explicit process policy. Offline is the default, including on restart.

This switch permits construction of live transports; it never grants budget
or publication authority. Dispatch still requires a scoped authorization.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..domain.errors import ContractError


@dataclass(frozen=True)
class ExecutionPolicy:
    mode: str = "offline"
    enabled: frozenset = frozenset()
    qualified_until: dict = field(default_factory=dict)
    clock: object = field(default=lambda: datetime.now(timezone.utc), repr=False, compare=False)

    def require_live(self, capability):
        if self.mode != "live" or capability not in self.enabled:
            raise ContractError("live_disabled", "capability", capability)
        if capability in self.qualified_until:
            try:
                expiry = datetime.fromisoformat(self.qualified_until[capability].replace('Z', '+00:00'))
                current = expiry > self.clock()
            except (ValueError, TypeError, AttributeError):
                current = False
            if not current:
                raise ContractError('qualification_expired', 'capability', capability)


def live_transport(transport, capability, policy=None):
    """Wrap real I/O; injected boundary fakes need no network privileges."""
    policy = policy or ExecutionPolicy()
    policy.require_live(capability)

    def invoke(*args, **kwargs):
        policy.require_live(capability)
        return transport(*args, **kwargs)
    return invoke
