"""PL-01 contracts: additive publishing/learning records and backward
compatibility for extended factory records."""
import pytest

from modules.factory.domain.records import (CheckpointSchedule, Decision,
                                            DecisionPolicy, LoopPolicy,
                                            MetadataPackage, Publication,
                                            RoundLineage, Seed,
                                            SeedSelection)
from modules.factory.store import Database

NOW = "2026-09-18T12:00:00+00:00"


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "f.db")


def _seed_record(**kw):
    body = dict(schema_version="seed.v1", id="seed-1", created_at=NOW,
                platform="local", title="t")
    body.update(kw)
    return Seed(**{k: v for k, v in body.items() if k in Seed.__dataclass_fields__})


def test_seed_lineage_fields_default_empty():
    s = _seed_record()
    assert s.parent_seed_id == "" and s.lineage_root_id == ""
    assert s.round == 0 and s.independence_group == ""


def test_publication_new_fields_default():
    p = Publication(schema_version="publication.v1", id="pub-1",
                    created_at=NOW, platform="youtube",
                    account_id="acct", status="requested")
    assert p.provider == "upload_post" and p.connection_id == ""
    assert p.metadata_package_id == "" and p.remote_schedule_id == ""


def test_decision_platform_field_and_new_conclusions():
    d = Decision(schema_version="decision.v1", id="d1", created_at=NOW,
                 conclusion="retain_control")
    assert d.platform == ""
    assert not d.validate()
    for c in ("invalid_comparison", "confirmed_winner"):
        d.conclusion = c
        assert not d.validate()


def test_decision_policy_seed_policy_optional():
    p = DecisionPolicy(schema_version="decision_policy.v1", id="p1",
                       created_at=NOW, status="draft")
    assert p.seed_policy == {}


def test_metadata_package_validation():
    m = MetadataPackage(schema_version="metadatapackage.v1", id="mp-1",
                        created_at=NOW, platform="youtube", status="draft")
    assert not m.validate()
    m.platform = "myspace"
    assert m.validate()
    m.platform = "tiktok"
    m.status = "frozen"
    assert m.validate()                      # frozen needs selected
    m.selected = {"caption": "x"}
    assert not m.validate()


def test_seed_selection_validation():
    s = SeedSelection(schema_version="seedselection.v1", id="sel-1",
                      created_at=NOW, horizon="24h", status="waiting")
    assert not s.validate()
    s.winner_variant = "Z"
    assert s.validate()
    s.winner_variant = "A"
    assert not s.validate()


def test_checkpoint_schedule_validation():
    c = CheckpointSchedule(schema_version="checkpointschedule.v1",
                           id="cp-1", created_at=NOW,
                           publication_id="pub-1", horizon="24h",
                           status="pending")
    assert not c.validate()
    c.status = "due"
    assert c.validate()                      # due needs due_at
    c.due_at = NOW
    assert not c.validate()


def test_round_lineage_and_loop_policy():
    r = RoundLineage(schema_version="roundlineage.v1", id="rl-1",
                     created_at=NOW, series_id="ser-1", round=1,
                     independence_group="grp-1")
    assert not r.validate()
    lp = LoopPolicy(schema_version="looppolicy.v1", id="lp-1",
                    created_at=NOW, series_id="ser-1",
                    mode="execute_within_authorization")
    assert lp.validate()                     # execution needs auth
    lp.authorization_id = "auth-1"
    assert not lp.validate()
    lp.mode = "bogus"
    assert lp.validate()


def test_new_kinds_persist_and_read_back(db):
    with db.uow() as u:
        u.records.put(MetadataPackage(
            schema_version="metadatapackage.v1", id="mp-1",
            created_at=NOW, platform="youtube", status="frozen",
            selected={"title": "t"}, content_hash="h"))
        u.records.put(SeedSelection(
            schema_version="seedselection.v1", id="sel-1",
            created_at=NOW, horizon="24h", status="provisional",
            winner_variant="B", artifact_id="art:1"))
    row = db.uow().records.get("metadatapackage", "mp-1")
    import json
    assert json.loads(row["body"])["selected"]["title"] == "t"
    row = db.uow().records.get("seedselection", "sel-1")
    assert json.loads(row["body"])["winner_variant"] == "B"
