"""PL-06/PL-35: bounded Round-2 loop — derived seed, one active child,
loop-policy limits, pause vs series-cancel semantics, and mature
basis supersession without auto-replacement."""
import json

import pytest

from modules.factory.domain.errors import ContractError
from modules.factory.domain.records import Publication, Seed
from modules.factory.services.rounds import RoundService
from modules.factory.store import Database
from test_factory_seed_selection import (
    _experiment, _lanes, _policy, W2)

NOW = "2026-09-17T12:00:00+00:00"
SHA = "ab" * 32


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "f.db")


class _Svc:
    def __init__(self, db):
        from modules.factory.seeds.registry import SeedRegistry
        self.db = db
        self.publishing = None
        self.seeds = SeedRegistry(db)


def _rounds(db):
    return RoundService(_Svc(db))


def _selection(db, winner="B", sel_id="sel-exp-1-r1-48h"):
    from modules.factory.domain.records import SeedSelection
    with db.uow() as u:
        u.records.put(SeedSelection(
            schema_version="seed_selection.v1", id=sel_id,
            created_at=NOW, experiment_id="exp-1",
            experiment_revision=1, horizon="48h",
            status="provisional", winner_variant=winner,
            inputs_hash="h1"))
    return sel_id


def _setup(db):
    _experiment(db)
    with db.uow() as u:
        u.records.put(Seed(schema_version="seed.v1", id="seed-1",
                           created_at=NOW, original_url="u1",
                           independence_group="root-1"))


def _freeze(rounds, series="series:root-1", **kw):
    args = dict(mode="propose_only", max_rounds=2)
    args.update(kw)
    return rounds.freeze_loop(series, **args)


# --------------------------------------------------- proposal -----

def test_propose_creates_derived_seed_and_lineage(db):
    _setup(db)
    rounds = _rounds(db)
    _freeze(rounds)
    sel = _selection(db, winner="B")
    out = rounds.propose_next("exp-1", 1, sel)
    child = out["seed"]
    assert child["parent_seed_id"] == "seed-1"
    assert child["lineage_root_id"] == "root-1"
    assert child["independence_group"] == "root-1"
    assert child["round"] == 1
    lin = out["lineage"]
    assert lin["status"] == "proposed"
    assert lin["parent_selection_id"] == sel
    assert lin["round"] == 1
    # The selection records its child once — evaluation was separate.
    sel_row = db.uow().records.get("seedselection", sel)
    assert json.loads(sel_row["body"])["seed_id"] == child["id"]
    assert out["requires_review"] is True   # winner != A → new analysis


def test_propose_is_idempotent_and_single_child(db):
    _setup(db)
    rounds = _rounds(db)
    _freeze(rounds)
    sel = _selection(db)
    first = rounds.propose_next("exp-1", 1, sel)
    again = rounds.propose_next("exp-1", 1, sel)
    assert again["idempotent"] is True
    assert again["lineage"]["id"] == first["lineage"]["id"]
    # A DIFFERENT selection for the same parent is a second active
    # child — refused.
    _selection(db, winner="C", sel_id="sel-exp-1-r1-7d")
    with pytest.raises(ContractError) as e:
        rounds.propose_next("exp-1", 1, "sel-exp-1-r1-7d")
    assert e.value.code == "active_child_exists"


def test_propose_requires_winner_and_policy(db):
    _setup(db)
    rounds = _rounds(db)
    sel = _selection(db, winner="")
    _freeze(rounds)
    with pytest.raises(ContractError) as e:
        rounds.propose_next("exp-1", 1, sel)
    assert e.value.code == "no_winner"


def test_propose_requires_loop_policy(db):
    _setup(db)
    rounds = _rounds(db)
    sel = _selection(db)
    with pytest.raises(ContractError) as e:
        rounds.propose_next("exp-1", 1, sel)
    assert e.value.code == "loop_policy_required"


def test_loop_expiry_and_round_limit(db):
    _setup(db)
    rounds = _rounds(db)
    _freeze(rounds, valid_until="2026-01-01T00:00:00+00:00")
    sel = _selection(db)
    with pytest.raises(ContractError) as e:
        rounds.propose_next("exp-1", 1, sel,
                            now="2026-09-17T12:00:00+00:00")
    assert e.value.code == "loop_expired"
    assert rounds._loop_policy("series:root-1")["status"] == "expired"

    rounds2 = _rounds(db)
    rounds2._set_policy("series:root-1", status="active",
                        valid_until="", max_rounds=1)
    rounds2.propose_next("exp-1", 1, sel)
    _selection(db, winner="C", sel_id="sel-exp-1-r1-7d")
    # Round limit reached AND an active child exists — child wins.
    with pytest.raises(ContractError) as e2:
        rounds2.propose_next("exp-1", 1, "sel-exp-1-r1-7d")
    assert e2.value.code in ("round_limit", "active_child_exists")


# -------------------------------------------------- supersession ---

def test_mature_revision_marks_basis_superseded(db):
    """A mature reevaluation that changes the winner marks the
    child's basis superseded — history kept, no auto-replacement."""
    _setup(db)
    rounds = _rounds(db)
    _freeze(rounds)
    sel = _selection(db)
    out = rounds.propose_next("exp-1", 1, sel)
    lid = out["lineage"]["id"]
    marked = rounds.mark_basis_superseded(sel)
    assert marked == [lid]
    lin = db.uow().records.get("roundlineage", lid)
    assert json.loads(lin["body"])["status"] == "superseded"


# ------------------------------------------------------ control ----

def _scheduled_pub(db, pid, exp="exp-1"):
    with db.uow() as u:
        u.records.put(Publication(
            schema_version="publication.v1", id=pid, created_at=NOW,
            variant_plan_id="vp-exp-1-b", final_sha256=SHA,
            platform="tiktok", account_id="tt-1", job_id="job-1",
            status="scheduled", experiment_id=exp,
            experiment_revision=1))


def test_pause_lists_remote_schedules_without_cancelling(db):
    _setup(db)
    rounds = _rounds(db)
    _freeze(rounds)
    _scheduled_pub(db, "pub-1")
    out = rounds.pause_series("series:root-1")
    assert out["status"] == "paused"
    assert out["outstanding_remote"][0]["state"].startswith(
        "scheduled_remote")
    # Local policy paused; the remote job was NOT cancelled.
    assert rounds._loop_policy("series:root-1")["status"] == "paused"


def test_cancel_series_cancels_remote_and_revokes(db):
    _setup(db)
    rounds = _rounds(db)
    _freeze(rounds)
    _scheduled_pub(db, "pub-1")

    class _Pub:
        def cancel_remote(self, pid, now=""):
            return {"outcome": "cancelled", "publication_id": pid}
    rounds.s.publishing = _Pub()
    out = rounds.cancel_series("series:root-1")
    assert out["policy"] == "revoked"
    assert out["remote"][0]["outcome"] == "cancelled"
    assert out["remote"][0]["platform"] == "tiktok"
