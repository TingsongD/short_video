"""B3/B4 regression tests (patch round 2).

B3: readback baseline — AnalyticsClient.channel_median_views feeds the
    verdict + format-promotion multiplier. Before the fix the baseline
    stayed 0 forever: every verdict views-leg passed (over-reporting wins)
    and promote._mult divided by zero, so no format could ever be proven.
B4: weekly composition — scan() returns {"clusters": ...} but grill.run
    expects the niche_report contract {"niches": ...}. The weekly CLI must
    compose scan -> build_report -> write_report -> grill_run; feeding raw
    scan output yielded a silently empty shortlist.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from modules.analytics.pull import AnalyticsClient
from modules.common.llm import FakeLLM
from modules.common.schema import validate
from modules.formats import promote
from modules.grill.gate import run as grill_run
from modules.orchestrate.stages import readback_stages
from modules.radar.report import build_report, write_report

FIXTURES = Path(__file__).parent / "fixtures" / "contracts"
BREAKOUT = json.loads(
    (FIXTURES / "niche_report.sample.json").read_text()
)["niches"][0]["breakout_videos"][0]

CFG = {
    "readback": {"windows_hours": [48, 168, 672],
                 "win_views_multiplier": 2.0,
                 "win_avd_ratio": 0.7},
    "grill": {"pass_hook_score": 7.0, "pass_virality_score": 6.0,
              "ideas_per_cluster": 8},
}

GENERATE_RESPONSE = json.dumps([{
    "topic": "3 phrases manipulators use in arguments",
    "hook_overlay": "If someone says these 3 phrases, walk away.",
    "target_viewer": "18-34 self-protection viewers",
    "payoff": "Viewer learns the 3 phrases, the bias each exploits, and the counter.",
    "three_bullets": ["Stakes: scripted phrases", "Mechanism: bias each exploits",
                      "Result: one-sentence counter"],
    "cta": "Follow for the next breakdown", "number_claims": [],
}])
JUDGE_RESPONSE = json.dumps({
    "virality_score": 8.0, "hook_score": 8.5, "payoff_confidence": 8.0,
    "three_bullets": ["a", "b", "c"], "judge_notes": "strong",
})


def _llm():
    def responder(system, user):
        s = system.lower()
        if "short-form video ideas" in s:
            return GENERATE_RESPONSE
        if "grill judge" in s:
            return JUDGE_RESPONSE
        raise AssertionError(f"unexpected LLM system prompt: {system[:60]}")
    return FakeLLM(responder)


class FakeMedianTransport:
    """channels -> playlistItems -> videos; viewCounts median is 1500."""
    COUNTS = {"up0": 500, "up1": 1000, "up2": 1500, "up3": 2000, "up4": 2500}

    def __call__(self, url):
        if "channels" in url:
            return {"items": [{"contentDetails":
                               {"relatedPlaylists": {"uploads": "UUfake"}}}]}
        if "playlistItems" in url:
            return {"items": [{"contentDetails": {"videoId": vid}}
                              for vid in self.COUNTS]}
        if "videos" in url:
            return {"items": [{"id": vid,
                               "statistics": {"viewCount": str(n)}}
                              for vid, n in self.COUNTS.items()]}
        raise AssertionError(f"unexpected URL {url}")


class FakeReadbackClient:
    """Own-channel analytics + baseline median for readback_stages."""
    def __init__(self, views, baseline, avd=25.0):
        self._views = views
        self._baseline = baseline
        self._avd = avd
        self.handle_seen = None

    def analytics_rows(self, yt_id, start, end):
        return {"views": self._views, "averageViewDuration": self._avd,
                "impressions": 10000, "ctr": 5.0, "subscribersGained": 3}

    def retention(self, yt_id, start, end):
        return [{"t_ratio": 0.0, "audience_ratio": 1.0}]

    def channel_median_views(self, handle=""):
        self.handle_seen = handle
        return self._baseline


def _run_readback(tmp_path, views, baseline, avd=25.0, video_id="v-b3-1"):
    """Drive the real readback stages against one publish record."""
    pub = tmp_path / "published"
    ana = tmp_path / "analytics"
    pub.mkdir(parents=True)
    rec = {
        "video_id": video_id,
        "platform_video_ids": {"youtube": f"yt-{video_id}"},
        "title": "t", "caption": "c", "hashtags": ["#x"],
        "published_at": "2026-08-01T00:00:00Z",  # all 3 windows due
        "format_id": "fmt-test", "idea_id": "idea-test",
        "niche": "psychology_facts", "variant_index": 1,
        "video_len_s": 30,
    }
    (pub / f"{video_id}.json").write_text(json.dumps(rec))
    client = FakeReadbackClient(views, baseline, avd)
    ctx = {"config": CFG, "analytics_client": client,
           "published_dir": pub, "analytics_dir": ana,
           "channel_handle": "@ourchannel"}
    for _name, stage in readback_stages(ctx):
        stage()
    doc = json.loads((ana / f"{video_id}.json").read_text())
    return doc, client


# ---- B3 ----

def test_channel_median_views_computes_median():
    client = AnalyticsClient("fake-key", transport=FakeMedianTransport())
    assert client.channel_median_views("@ourchannel") == 1500.0


def test_readback_verdict_loss_against_real_baseline(tmp_path):
    """views 1500 < 2.0x baseline 1000 -> loss. With the old zero baseline
    this same pull was a 'win' — the B3 over-reporting bug."""
    doc, client = _run_readback(tmp_path, views=1500, baseline=1000)
    assert client.handle_seen == "@ourchannel"
    assert doc["baseline_median_views"] == 1000
    assert doc["verdict"] == "loss"
    assert doc["format_promotion"] == "retire"


def test_readback_verdict_win_against_real_baseline(tmp_path):
    doc, _ = _run_readback(tmp_path, views=2500, baseline=1000)
    assert doc["verdict"] == "win"
    assert doc["format_promotion"] == "promote"


def test_promotion_path_alive_after_baseline_fix(tmp_path):
    """3 winning readbacks at 2.4x the real baseline -> format 'proven'.
    With a zero baseline _mult returned 0.0 and proven was unreachable."""
    entry = {"format_id": "fmt-test", "status": "candidate"}
    cfg = {"promote_min_videos": 3, "promote_min_multiplier": 1.5,
           "retire_consecutive_losses": 3}
    for i in range(3):
        doc, _ = _run_readback(tmp_path / f"run{i}", views=2400, baseline=1000)
        assert doc["verdict"] == "win"
        promote.apply_readback(entry, doc)
    assert entry["our_stats"]["avg_multiplier"] == 2.4
    assert promote.evaluate(entry, cfg) == "proven"


# ---- B4 ----

def test_weekly_composition_scan_report_grill(tmp_path):
    """The weekly CLI composition: scan clusters -> build_report ->
    write_report -> grill_run(report) must produce ideas (not silently
    empty, as when raw scan output was passed to grill.run)."""
    clusters = [{"niche": "psychology_facts", "topic": "dark psychology",
                 "confirmed": True, "videos": [BREAKOUT]}]
    report = build_report(
        clusters, datetime(2026, 9, 14, 8, 0, tzinfo=timezone.utc),
        ["psychology_facts", "money_tips"], 4200)
    validate(report, "niche_report.schema.json")
    rp, _ = write_report(report, tmp_path / "radar", "2026-09-14")
    assert rp.exists()
    doc, _audit = grill_run(report, _llm(), CFG["grill"])
    validate(doc, "scored_ideas.schema.json")
    assert doc["ideas"], "weekly shortlist empty — B4 regression"
