"""Named fault registry (runbook §3).

Faults are finite, named and data-driven. They are injected at the fake
provider/service boundary — never as arbitrary shell/SQL/Python from a
caller. Unknown fault names are rejected before any effect.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Fault:
    name: str
    boundary: str          # which fake surface implements it
    description: str


FAULTS = {f.name: f for f in [
    Fault("reject-before-accept", "provider.submit",
          "submission refused before acceptance; no charge, no operation"),
    Fault("accept-then-timeout", "provider.submit",
          "remote accepted and possibly charged; ack never reached caller"),
    Fault("malformed-ack", "provider.submit",
          "acknowledgement body is unparseable"),
    Fault("accepted-then-failed", "provider.poll",
          "accepted operation resolves to a terminal failure"),
    Fault("stalled-operation", "provider.poll",
          "operation never leaves accepted state"),
    Fault("auth-expiry", "provider.*",
          "calls fail auth_required until reconnect()"),
    Fault("quota-rejection", "provider.submit",
          "HTTP-429-style capacity rejection"),
    Fault("download-failure", "provider.download",
          "completed output exists but transfer fails transiently"),
    Fault("corrupt-bytes", "provider.download",
          "transfer returns bytes that fail media validation"),
    Fault("insufficient-duration", "artifact.intake",
          "returned media cannot cover its assigned interval"),
    Fault("storage-full", "artifact.intake",
          "atomic promotion fails on out-of-space"),
    Fault("event-disconnect", "events.stream",
          "SSE/cursor stream drops mid-history"),
    Fault("stale-lease", "scheduler.claim",
          "old worker's fencing token is rejected"),
    Fault("stale-review-hash", "reviews.record",
          "review targets a superseded artifact hash"),
    Fault("duplicate-upload", "provider.upload",
          "upload ack lost; remote file exists on reconcile"),
    Fault("ambiguous-publish", "provider.publish",
          "publish ack lost after possible remote acceptance"),
    Fault("http200-then-errors", "provider.poll",
          "HTTP 200 poll response carrying terminal error payload"),
    Fault("lost-upload-ack", "provider.upload",
          "same as duplicate-upload, Drive wording"),
    Fault("draft-only", "provider.publish",
          "async publish accepted into draft/inbox, never public"),
]}


def validate(names):
    unknown = [n for n in names if n not in FAULTS]
    if unknown:
        raise KeyError(f"unknown fault(s): {', '.join(unknown)}; "
                       f"registry is finite ({len(FAULTS)} entries)")
    return [FAULTS[n] for n in names]
