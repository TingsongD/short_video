"""PL-02 metadata: platform validators, disclosures, selection,
freeze immutability and publication binding (PL-T05/T06)."""
import pytest

from modules.factory.domain.errors import ContractError
from modules.factory.domain.records import VariantPlan
from modules.factory.metadata.service import MetadataService
from modules.factory.store import Database

NOW = "2026-09-18T12:00:00+00:00"
SHA = "ab" * 32
DISC = {"ai_content": True, "branded_content": False,
        "audience": "not_kids"}


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "f.db")


@pytest.fixture
def svc(db):
    return MetadataService(db)


def _pkg(svc, platform="youtube", disclosures=None):
    return svc.create("vp-1", platform, final_sha256=SHA,
                      disclosures=disclosures if disclosures is not None else DISC)


def test_create_generates_platform_candidates(svc):
    pkg = _pkg(svc, "tiktok")
    assert pkg.status == "draft" and len(pkg.candidates) == 3
    assert all("caption" in c["fields"] for c in pkg.candidates)
    assert all("title" not in c["fields"] for c in pkg.candidates)


def test_validation_requires_disclosures(svc):
    pkg = _pkg(svc, disclosures={})
    out = svc.select(pkg.id, candidate_id="c1")
    assert not out["validation"]["ok"]
    fields = {e["field"] for e in out["validation"]["errors"]}
    assert "ai_content" in fields and "audience" in fields


def test_validation_rejects_unsupported_and_long_fields(svc):
    pkg = _pkg(svc, "tiktok")
    out = svc.select(pkg.id, fields={"caption": "x" * 2300,
                                     "bogus_field": "y"})
    errs = {e["field"]: e["error"] for e in out["validation"]["errors"]}
    assert errs["caption"] == "exceeds_2200"
    assert errs["bogus_field"] == "unsupported_field"


def test_freeze_requires_valid_selection(svc):
    pkg = _pkg(svc)
    svc.select(pkg.id, candidate_id="c1")
    frozen = svc.freeze(pkg.id)
    assert frozen["status"] == "frozen" and frozen["content_hash"]
    with pytest.raises(ContractError) as e:
        svc.select(pkg.id, candidate_id="c2")
    assert e.value.code == "package_frozen"


def test_freeze_blocks_invalid_selection(svc):
    pkg = _pkg(svc, disclosures={})
    svc.select(pkg.id, candidate_id="c1")
    with pytest.raises(ContractError) as e:
        svc.freeze(pkg.id)
    assert e.value.code == "validation_failed"


def test_select_stale_revision_rejected(svc):
    pkg = _pkg(svc)
    svc.select(pkg.id, candidate_id="c1")          # revision -> 1
    with pytest.raises(ContractError) as e:
        svc.select(pkg.id, candidate_id="c2", revision=0)
    assert e.value.code == "stale_revision"


def test_platform_field_sets_differ(svc):
    yt = _pkg(svc, "youtube")
    ig = _pkg(svc, "instagram")
    assert "title" in yt.candidates[0]["fields"]
    assert "caption" in ig.candidates[0]["fields"]
