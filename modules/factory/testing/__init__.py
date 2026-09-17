"""Deterministic test doubles shared by QA cases and pytest.

Every external effect goes through a fake whose state persists under the QA
workspace separately from the application database, so crash/restart drills
are honest.
"""
from .clock import FakeClock
from .ids import IdFactory
from .netguard import NetworkGuard, BlockedNetworkCall
from .fakes import FakeProvider, FakeProviderState, ProviderError

__all__ = [
    "FakeClock", "IdFactory", "NetworkGuard", "BlockedNetworkCall",
    "FakeProvider", "FakeProviderState", "ProviderError",
]
