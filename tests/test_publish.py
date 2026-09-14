"""M9: metadata rules, record schema+dupes, cadence cap (test_metadata,
test_record, test_cadence)."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from modules.common.llm import FakeLLM
from modules.common.schema import validate
from modules.publish.metadata import build_metadata
from modules.publish.record import (
    CadenceBlock, check_cadence, posts_on, write_record,
)

IDEA = {
    "idea_id": "idea-20260914-001", "niche": "psychology_facts",
    "topic": "3 phrases manipulators use",
    "hook_overlay": "If someone says these 3 phrases, walk away.",
    "payoff": "the phrases + counters", "cta": "Follow for part 2",
    "status": "pass",
}
FMT = {"format_id": "fmt-dark-list-3", "cta_pattern": "Follow for part 2"}


def _llm(title="3 Phrases Manipulators Use (Walk Away)",
         caption="Spot them early.", hashtags=None):
    return FakeLLM(json.dumps({
        "title": title, "caption": caption,
        "hashtags": hashtags if hashtags is not None else
        ["#Psychology", "psychology", "SHORTS", "dark psychology!!"],
    }))


def test_metadata_normalized_and_bounded():
    m = build_metadata(IDEA, FMT, _llm())
    assert len(m["title"]) <= 100
    assert len(m["hashtags"]) <= 15
    # deduped (#Psychology vs psychology), '#'/punct stripped, lowercased
    assert m["hashtags"] == ["psychology", "shorts", "darkpsychology"]


def test_cta_appended_when_missing():
    m = build_metadata(IDEA, FMT, _llm(caption="Spot them early."))
    assert "follow" in m["caption"].lower()


def test_cta_present_not_duplicated():
    m = build_metadata(IDEA, FMT, _llm(caption="Follow for part 2."))
    assert m["caption"] == "Follow for part 2."


def test_overlong_title_rejected():
    with pytest.raises(ValueError, match="100"):
        build_metadata(IDEA, FMT, _llm(title="x" * 101))


def _record(vid="v-20260914-001", published="2026-09-14T15:00:00Z"):
    return {
        "video_id": vid,
        "platform_video_ids": {"youtube": "dQw4w9WgXcQ"},
        "title": "3 Phrases Manipulators Use (Walk Away)",
        "caption": "x", "hashtags": ["psychology"],
        "published_at": published, "format_id": "fmt-dark-list-3",
        "idea_id": "idea-20260914-001", "niche": "psychology_facts",
        "variant_index": 1,
    }


def test_record_schema_valid_and_duplicate_rejected(tmp_path):
    write_record(_record(), directory=tmp_path)
    with pytest.raises(FileExistsError):
        write_record(_record(), directory=tmp_path)


def test_cadence_blocks_third_post_same_day(tmp_path):
    write_record(_record("v-1"), directory=tmp_path)
    write_record(_record("v-2"), directory=tmp_path)
    recs = [json.loads(p.read_text()) for p in tmp_path.glob("*.json")]
    when = datetime(2026, 9, 14, 20, 0, tzinfo=timezone.utc)
    with pytest.raises(CadenceBlock):
        check_cadence(recs, "youtube", when=when, max_per_day=2)


def test_cadence_allows_next_day(tmp_path):
    write_record(_record("v-1"), directory=tmp_path)
    write_record(_record("v-2"), directory=tmp_path)
    recs = [json.loads(p.read_text()) for p in tmp_path.glob("*.json")]
    when = datetime(2026, 9, 15, 9, 0, tzinfo=timezone.utc)
    assert check_cadence(recs, "youtube", when=when, max_per_day=2)
    assert posts_on(recs, "youtube", when.date()) == 0
