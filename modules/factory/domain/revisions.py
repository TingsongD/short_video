"""Immutable revision lifecycle (handover §3.7, §7.2).

Accepted records are immutable. Any change produces a new revision with
the parent revision/hash and an explicit reason; downstream records that
referenced the old hash are marked superseded.
"""
import copy

from .errors import ContractError
from .records import content_hash


def accept(record):
    """Freeze a draft: compute content hash over all non-hash fields."""
    if getattr(record, "status", "draft") not in ("draft", "candidate"):
        raise ContractError("not_draft", "status", record.status)
    d = record.to_dict()
    d.pop("content_hash", None)
    record.content_hash = content_hash(d)
    record.status = "accepted"
    return record


def revise(record, reason, reason_ref=""):
    """Return a new revision; caller persists and marks the old superseded."""
    if not getattr(record, "content_hash", ""):
        raise ContractError("revise_unaccepted", "content_hash",
                            "only accepted revisions can be revised")
    if not reason:
        raise ContractError("missing_revision_reason", "reason")
    new = copy.deepcopy(record)
    new.revision = record.revision + 1
    new.parent_revision = record.revision
    new.parent_hash = record.content_hash
    new.status = "draft"
    new.content_hash = ""
    new.revision_reason = reason
    new.revision_reason_ref = reason_ref
    record.status = "superseded"
    return new


def check_revision_chain(revisions):
    """Revisions of one record: contiguous seq, parent hashes match."""
    errs = []
    ordered = sorted(revisions, key=lambda r: r.revision)
    for i, (prev, cur) in enumerate(zip(ordered, ordered[1:])):
        if cur.revision != prev.revision + 1:
            errs.append(ContractError("revision_gap", f"revisions[{i}]"))
        if cur.parent_hash != prev.content_hash:
            errs.append(ContractError("parent_hash_mismatch",
                                      f"revision[{cur.revision}]"))
    return errs
