"""M3: library CRUD + stable IDs (test_crud)."""
import pytest

from modules.formats import library


def _entry(name="Dark-facts 3-item listicle", niche="psychology_facts"):
    return {
        "name": name, "hook_type": "onscreen",
        "beats": ["Stakes: x", "Mechanism: y", "Payoff: z"],
        "visual_payoff": "bold text reveal", "cta_pattern": "follow",
        "watch_reference": "https://www.youtube.com/watch?v=abc123",
        "status": "candidate",
        "our_stats": {"videos": 0, "wins": 0, "avg_multiplier": 0},
        "niche": niche,
    }


def test_add_assigns_stable_slug_id(tmp_path):
    lib = {"version": 1, "formats": []}
    fid = library.add(lib, _entry())
    assert fid == "fmt-dark-facts-3-item-listicle"
    library.save(lib, tmp_path / "library.json")
    lib2 = library.load(tmp_path / "library.json")
    assert library.get(lib2, fid)["name"] == "Dark-facts 3-item listicle"


def test_id_collision_gets_suffix():
    lib = {"version": 1, "formats": []}
    a = library.add(lib, _entry())
    b = library.add(lib, _entry())
    assert a != b and b.endswith("-2")


def test_update_and_retire(tmp_path):
    lib = {"version": 1, "formats": []}
    fid = library.add(lib, _entry())
    library.update(lib, fid, notes="watch me")
    library.set_status(lib, fid, "retired")
    assert library.get(lib, fid)["status"] == "retired"
    assert [f["format_id"] for f in library.active(lib)] == []


def test_bad_status_rejected():
    lib = {"version": 1, "formats": []}
    with pytest.raises(ValueError):
        library.add(lib, _entry() | {"status": "weird"})
    fid = library.add(lib, _entry())
    with pytest.raises(ValueError):
        library.set_status(lib, fid, "weird")


def test_saved_file_is_schema_valid(tmp_path):
    lib = {"version": 1, "formats": []}
    library.add(lib, _entry())
    library.save(lib, tmp_path / "library.json")  # raises if invalid
