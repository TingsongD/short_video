"""Decision-layer gap fixes: non-midnight YouTube windows, eligible
snapshot selection, account-aware publication keys."""
import json

import pytest

from test_factory_learning import (_experiment, _policy, _publish,
                                   _rich)
from test_factory_seed_selection import _snap
from modules.factory.domain.records import Publication
from modules.factory.learning.service import LearningService
from modules.factory.store import Database


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "f.db")


def _set_snap(db, snap_id, **patch):
    row = db.uow().records.get("metricsnapshot", snap_id)
    body = json.loads(row["body"])
    body.update(patch)
    body.get("requested_period", {}).update(
        patch.get("requested_period", {}))
    with db.uow() as u:
        u.conn.execute(
            "UPDATE records SET body=? WHERE kind=? AND id=? "
            "AND revision=?",
            (json.dumps(body), "metricsnapshot", snap_id,
             row["revision"]))


def test_youtube_source_calendar_window_is_decidable(db):
    """A midday (non-LA-midnight) post snapshots as source_calendar —
    usable evidence, not a permanent wait (was incompatible_window)."""
    _experiment(db)
    svc = LearningService(db)
    _policy(svc)
    _publish(db, "exp-1", {"a": _rich(1000), "b": _rich(1400),
                           "c": _rich(900), "d": _rich(800)})
    # Flip each snapshot's window to the kind collect() emits for
    # non-midnight-aligned publish times.
    for vk in "abcd":
        _set_snap(db, f"snap-pub-exp-1-{vk}-48h",
                  requested_period={"horizon_hours": 48,
                                    "window_kind": "source_calendar"})
    dec = svc.decide("exp-1", 1, platform="youtube")
    assert dec["conclusion"] == "provisional_winner", dec["conclusion"]
    assert dec["winner"] == "B"
    assert any("source_calendar" in lim for lim in dec["limitations"])


def test_later_partial_retry_does_not_mask_complete_snapshot(db):
    """An eligible earlier sample wins over a later pending retry."""
    _experiment(db)
    svc = LearningService(db)
    _policy(svc)
    _publish(db, "exp-1", {"a": _rich(1000), "b": _rich(1400),
                           "c": _rich(900), "d": _rich(800)})
    # Plant a LATER pending retry on B — latest-by-time would hide the
    # complete sample; the eligible pick must not.
    _snap(db, "pub-exp-1-b", "48h", {}, platform="youtube", rev=1)
    _set_snap(db, "snap-pub-exp-1-b-48h",
              completeness="pending", metrics={}, availability={},
              observed_at="2027-01-01T00:00:00+00:00")
    dec = svc.decide("exp-1", 1, platform="youtube")
    assert dec["conclusion"] == "provisional_winner", (
        dec["conclusion"], dec.get("per_variant", {}))
    assert dec["winner"] == "B"


def test_two_accounts_same_platform_resolve_by_account(db):
    """(variant, platform, account) — a second account only resolves
    when the caller names it; unscoped stays honestly ambiguous."""
    _experiment(db)
    svc = LearningService(db)
    _policy(svc)
    _publish(db, "exp-1", {"a": _rich(1000), "b": _rich(1400),
                           "c": _rich(900), "d": _rich(800)})
    rows = db.conn.execute(
        "SELECT body FROM records WHERE kind='publication'").fetchall()
    with db.uow() as u:
        for r in rows:
            p = json.loads(r["body"])
            p["id"] = p["id"] + "-acct2"
            p["account_id"] = "acct-2"
            u.records.put(Publication(**{
                k: v for k, v in p.items()
                if k in Publication.__dataclass_fields__}))
    # Unscoped: two public posts per (variant, youtube) → missing.
    dec = svc.decide("exp-1", 1, platform="youtube")
    assert dec["conclusion"] == "waiting_for_data"
    # Scoped: the original account resolves deterministically.
    dec2 = svc.decide("exp-1", 1, platform="youtube",
                      account="acct-main")
    assert dec2["conclusion"] == "provisional_winner", dec2
    assert dec2["winner"] == "B"
    assert dec2["id"].endswith("-acct-main")
