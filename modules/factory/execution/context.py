"""Ephemeral transport permission, available only inside a fenced submission."""
from contextlib import contextmanager
from contextvars import ContextVar

current_effect = ContextVar("factory_effect", default=None)


@contextmanager
def dispatch_context(binding):
    token = current_effect.set(binding)
    try:
        yield
    finally:
        current_effect.reset(token)
