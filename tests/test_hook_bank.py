"""M4: bank schema + selector + attribution (test_bank_schema, test_select,
test_attribution)."""
import json
from pathlib import Path

import pytest

from modules.common.config import DATA_DIR
from modules.common.schema import validate
from modules.hooks.select import attribution, load_bank, select

BANK = DATA_DIR / "hooks" / "bank.json"


def test_bank_file_validates_against_schema():
    bank = json.loads(BANK.read_text())
    validate(bank, "hooks_bank.schema.json")


def test_every_entry_has_required_fields():
    for h in load_bank(BANK):
        for field in ("id", "text", "niche", "hook_type", "source_url", "added_at"):
            assert h[field], f"{h.get('id')} missing {field}"


def test_select_matches_niche_and_type():
    hooks = load_bank(BANK)
    h = select(hooks, "psychology_facts", "onscreen")
    assert h["niche"] == "psychology_facts"
    assert h["hook_type"] == "onscreen"


def test_select_falls_back_to_niche_when_type_missing():
    hooks = load_bank(BANK)
    h = select(hooks, "money_tips", "onscreen")
    assert h["niche"] == "money_tips"


def test_select_raises_on_empty_niche():
    with pytest.raises(LookupError):
        select(load_bank(BANK), "nonexistent_niche")


def test_selected_hook_carries_attribution():
    h = select(load_bank(BANK), "ai_tools")
    a = attribution(h)
    assert a["source_url"].startswith("https://")
    assert a["hook_id"] == h["id"]
