"""Dated capability snapshots (F15 checklist 2).

Support levels are ordered: advertised (docs say so) < observed (seen
working once) < qualified (evidence-backed for production). Routing
requires at least `observed`; a stale snapshot is reported, not trusted.
"""
import json

from ..domain.errors import ContractError
from ..domain.records import Record
from ..store.uow import utcnow
from dataclasses import dataclass, field

SUPPORT = ("advertised", "observed", "qualified")


@dataclass
class CapabilitySnapshot(Record):
    provider: str = ""
    model: str = ""
    location: str = ""
    input_mode: str = ""             # text | image_ref | video_ref | ...
    support: str = "advertised"      # advertised | observed | qualified
    capabilities: dict = field(default_factory=dict)
    observed_at: str = ""
    valid_until: str = ""
    revision: int = 0

    def validate(self):
        e = super().validate()
        if self.support not in SUPPORT:
            e.append(ContractError("bad_support", "support",
                                   self.support))
        return e


def snapshot_id(provider, model, location, input_mode):
    return f"cap-{provider}-{model}-{location or 'any'}-{input_mode}"


class CapabilityCatalog:
    def __init__(self, db):
        self.db = db

    def put(self, snap):
        prior = self.db.uow().records.get(
            "capabilitysnapshot",
            snapshot_id(snap.provider, snap.model, snap.location,
                        snap.input_mode))
        snap.revision = (prior["revision"] + 1) if prior else 0
        snap.validate_or_raise()
        with self.db.uow() as u:
            u.records.put(snap)
        return snap

    def latest(self, provider, model, location="", input_mode="",
               now=None):
        rid = snapshot_id(provider, model, location, input_mode)
        row = self.db.uow().records.get("capabilitysnapshot", rid)
        if row is None:
            return None
        snap = CapabilitySnapshot(**json.loads(row["body"]))
        from datetime import datetime
        try:
            stale = bool(snap.valid_until and now and datetime.fromisoformat(snap.valid_until.replace('Z','+00:00')) <= datetime.fromisoformat(now.replace('Z','+00:00')))
        except (ValueError,TypeError):
            stale = True
        return {"snapshot": snap, "stale": stale,
                "revision": row["revision"]}
