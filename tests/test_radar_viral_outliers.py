"""Offline discovery, billing and interruption tests. No real credentials/network."""
from datetime import datetime, timedelta, timezone
import io
import json

import pytest

from modules.common.llm import FakeLLM
from modules.common.schema import validate
from modules.formats.extract import draft_format
from modules.grill.generate import expand_cluster
from modules.orchestrate.ledger import BudgetExceeded, CostLedger
from modules.radar.metrics import followers_outlier, is_breakout
from modules.radar.viral_client import SEARCH_PATH, ViralError, ViralOutliersClient
from modules.radar.viral_records import normalize, records
from modules.radar.viral_scan import execute, prepare, preview, run_lock

NOW = datetime.now(timezone.utc)
THRESHOLDS = {"breakout_subs_ratio": 2.0, "max_video_age_days": 14,
              "cluster_min_channels": 2, "eligibility": "followers"}
NICHES = [{"name": "ai_tools", "keywords": ["ai tools"]}]
PRICE = {"usdPerCredit": 0.01, "skills": [
    {"key": "search_outliers", "credits": 1, "restMethod": "POST", "restPath": SEARCH_PATH}]}


def post(handle="creator", native_id="12345678901", **changes):
    return {"id": "provider-" + native_id, "title": "Three ai tools to try",
            "platform": "tiktok", "postLink": f"https://www.tiktok.com/@{handle}/video/{native_id}",
            "contentType": "Video", "views": 20001, "followerCount": 10000,
            "published_at": (NOW - timedelta(days=1)).isoformat(),
            "outlierScore": 0.5, "profile": {"handle": handle, "is_active": True}, **changes}


class Transport:
    def __init__(self, responses=None, balance=100, pricing=None):
        self.responses = list(responses or [])
        self.balance, self.price = balance, pricing or PRICE
        self.calls = []

    def __call__(self, method, path, body):
        self.calls.append((method, path, body))
        if path == "/api/v1/pricing":
            return 200, {}, self.price
        if path == "/api/v1/credits":
            return 200, {}, {"balance": self.balance}
        if path == "/api/v1/trending":
            return 200, {}, {"outliers": [post(published_at=None)]}
        assert method == "POST" and path == SEARCH_PATH
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response

    @property
    def paid_calls(self):
        return [call for call in self.calls if call[0] == "POST"]


def ok(rows=None, **headers):
    return 200, {"X-Credits-Charged": "1", **headers}, {"posts": rows if rows is not None else [post()]}


def batch(tmp_path, transport, pages=1):
    root = tmp_path / "radar"
    plan = prepare(root, "pilot", NICHES, THRESHOLDS, platforms=["tiktok"], pages=pages)
    ledger = CostLedger(tmp_path / "ledger.json", weekly_cap=1)
    return root, plan, ViralOutliersClient("fake-private-value", transport), ledger


@pytest.mark.parametrize("views,followers,expected", [(20000, 10000, False), (20001, 10000, True),
    (19999, 10000, False), (1, 0, False), (20000, None, False), (None, 20, False)])
def test_strict_unrounded_ratio(views, followers, expected):
    assert followers_outlier(views, followers) is expected
    assert is_breakout(views=views or 0, subscribers=followers or 0, baseline=99999,
                       age_days=1, thresholds=THRESHOLDS) is expected


def test_vendor_score_is_not_our_eligibility_or_channel_median():
    video, observation = normalize(post(outlierScore=0.1), NOW, THRESHOLDS)
    assert video["subs_ratio"] == 2.0001 and observation["ratio_pass"]
    assert video["vendor_outlier_score"] == 0.1
    assert video["channel_avg"] == 0 and not video["baseline_available"]
    assert normalize(post(views=20000, outlierScore=1000), NOW, THRESHOLDS)[0] is None


@pytest.mark.parametrize("changes,reason", [
    ({"followerCount": 0}, "missing_positive_followers"),
    ({"followerCount": None}, "missing_positive_followers"),
    ({"views": "20K"}, "missing_views"),
    ({"views": float("inf")}, "missing_views"),
    ({"followerCount": True}, "missing_positive_followers"),
    ({"published_at": None}, "missing_publication_date"),
    ({"published_at": "2026-09-15"}, "missing_publication_date"),
    ({"published_at": (NOW - timedelta(days=15)).isoformat()}, "outside_age_window"),
    ({"published_at": (NOW + timedelta(days=1)).isoformat()}, "outside_age_window"),
    ({"deleted_at": "2026-09-01"}, "deleted_post"),
    ({"profile": {"is_active": False}}, "inactive_profile"),
    ({"contentType": "Photo"}, "not_verified_video"),
    ({"contentType": "slideshow"}, "not_verified_video"),
    ({"title": ""}, "missing_title"),
    ({"postLink": "javascript:alert(1)"}, "missing_or_unsupported_video_url"),
    ({"postLink": "https://www.tiktok.com.evil.test/@c/video/123"}, "missing_or_unsupported_video_url"),
])
def test_incomplete_or_ineligible_evidence_never_enters_report(changes, reason):
    video, observation = normalize(post(**changes), NOW, THRESHOLDS)
    assert video is None and reason in observation["reasons"]


def test_nested_profile_snake_case_and_caption():
    row = post(title="", caption="Three ai tools", followerCount=None,
               profile={"followers_count": "10000", "handle": "creator"})
    video, _ = normalize(row, NOW, THRESHOLDS)
    assert video["followers"] == 10000 and video["denominator_source"] == "profile"
    assert video["title"] == "Three ai tools"


@pytest.mark.parametrize("payload", [{}, {"data": None}, {"posts": [None]}, {"error": "bad", "posts": []}])
def test_unknown_responses_are_errors_not_empty_successes(payload):
    with pytest.raises(ViralError):
        records(payload)


def test_preview_is_free_and_never_handed_to_production():
    transport = Transport()
    result = preview(ViralOutliersClient(transport=transport), THRESHOLDS, NOW)
    assert result["ratio_matches"] == 1
    assert result["review_reasons"]["missing_publication_date"] == 1
    assert not result["production_handoff"] and result["credits_spent"] == 0
    assert len(transport.calls) == 1 and not transport.paid_calls


@pytest.mark.parametrize("ceiling", [None, -1, 0, True, 1])
def test_entire_batch_must_fit_approval_before_any_network(tmp_path, ceiling):
    transport = Transport()
    root, plan, client, ledger = batch(tmp_path, transport, pages=2)
    with pytest.raises(ViralError, match="credit-ceiling 2"):
        execute(root, "pilot", client, credit_ceiling=ceiling, ledger=ledger)
    assert transport.calls == [] and ledger.entries == []


def test_zero_balance_submits_nothing(tmp_path):
    transport = Transport(balance=0)
    root, _, client, ledger = batch(tmp_path, transport)
    with pytest.raises(ViralError, match="Insufficient available API credits"):
        execute(root, "pilot", client, credit_ceiling=1, ledger=ledger)
    assert not transport.paid_calls and ledger.entries == []


def test_weekly_dollar_cap_also_blocks_before_request(tmp_path):
    transport = Transport()
    root, _, client, ledger = batch(tmp_path, transport)
    ledger.weekly_cap = 0
    with pytest.raises(BudgetExceeded):
        execute(root, "pilot", client, credit_ceiling=1, ledger=ledger)
    assert not transport.paid_calls


def test_price_change_requires_review(tmp_path):
    price = json.loads(json.dumps(PRICE))
    price["skills"][0]["credits"] = 2
    transport = Transport(pricing=price)
    root, _, client, ledger = batch(tmp_path, transport)
    with pytest.raises(ViralError, match="pricing differs"):
        execute(root, "pilot", client, credit_ceiling=100, ledger=ledger)
    assert not transport.paid_calls


def test_two_creators_confirm_but_duplicates_do_not(tmp_path):
    rows = [post(), post(), post(handle="second", native_id="22345678901")]
    transport = Transport([ok(rows), ok(rows)])
    root, plan, client, ledger = batch(tmp_path, transport, pages=2)
    report = execute(root, "pilot", client, credit_ceiling=2, ledger=ledger)
    validate(report, "niche_report.schema.json")
    assert report["niches"][0]["cluster_size"] == 2
    assert report["niches"][0]["confirmed"]
    assert report["scan_meta"]["quota_used"] == 0
    assert report["scan_meta"]["credits_reserved"] == 2
    assert report["scan_meta"]["review_reasons"]["duplicate_video"] == 4
    assert [call[2]["page"] for call in transport.paid_calls] == [1, 2]
    assert all("minOutlierScore" not in call[2] for call in transport.paid_calls)
    before = len(transport.calls)
    assert execute(root, "pilot", client) == report  # no key/network/ceiling needed for replay
    assert len(transport.calls) == before and len(ledger.entries) == 2
    saved = "".join(p.read_text() for p in (root / "pilot").glob("*.json"))
    assert "fake-private-value" not in saved and "Authorization" not in saved
    summary = (root / "pilot/niche_report.md").read_text()
    assert "tiktok.com" in summary and "channel median unavailable" in summary


def test_same_creator_multiple_videos_is_not_confirmation(tmp_path):
    transport = Transport([ok([post(), post(native_id="99999999999")])])
    root, _, client, ledger = batch(tmp_path, transport)
    report = execute(root, "pilot", client, credit_ceiling=1, ledger=ledger)
    assert report["niches"][0]["cluster_size"] == 2
    assert not report["niches"][0]["confirmed"]


def test_partial_acceptance_and_timeout_never_duplicates(tmp_path):
    transport = Transport([ok(), TimeoutError("do not log private details")])
    root, _, client, ledger = batch(tmp_path, transport, pages=2)
    with pytest.raises(ViralError, match="outcome unknown"):
        execute(root, "pilot", client, credit_ceiling=2, ledger=ledger)
    state = json.loads((root / "pilot/state.json").read_text())
    assert state["requests"]["0"]["status"] == "received"
    assert state["requests"]["1"]["status"] == "outcome_unknown"
    with pytest.raises(ViralError, match="unknown outcome"):
        execute(root, "pilot", client, credit_ceiling=2, ledger=ledger)
    assert len(transport.paid_calls) == 2 and len(ledger.entries) == 2
    assert "private details" not in json.dumps(state)


@pytest.mark.parametrize("status,body", [(401, {}), (402, {}), (429, {}), (500, {}), (200, None),
                                         (200, {"unexpected": []})])
def test_error_receipts_do_not_retry_on_resume(tmp_path, status, body):
    transport = Transport([(status, {}, body)])
    root, _, client, ledger = batch(tmp_path, transport)
    for _ in range(2):
        with pytest.raises(ViralError):
            execute(root, "pilot", client, credit_ceiling=1, ledger=ledger)
    assert len(transport.paid_calls) == 1
    assert (root / "pilot/state.json").exists()


def test_restart_after_receipt_resumes_only_unsent_queries(tmp_path, monkeypatch):
    from modules.radar import viral_scan
    transport = Transport([ok(), ok()])
    root, _, client, ledger = batch(tmp_path, transport, pages=2)
    real_records = viral_scan.records
    monkeypatch.setattr(viral_scan, "records", lambda payload: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        execute(root, "pilot", client, credit_ceiling=2, ledger=ledger)
    monkeypatch.setattr(viral_scan, "records", real_records)
    execute(root, "pilot", client, credit_ceiling=2, ledger=ledger)
    assert len(transport.paid_calls) == 2 and len(ledger.entries) == 2


def test_unexpected_charge_blocks_remainder_and_restart(tmp_path):
    transport = Transport([ok(**{"X-Credits-Charged": "2"})])
    root, _, client, ledger = batch(tmp_path, transport, pages=2)
    for _ in range(2):
        with pytest.raises(ViralError, match="credit charge"):
            execute(root, "pilot", client, credit_ceiling=2, ledger=ledger)
    assert len(transport.paid_calls) == 1


def test_changed_plan_and_concurrent_run_are_blocked(tmp_path):
    root, _, client, ledger = batch(tmp_path, Transport([ok()]))
    with pytest.raises(ViralError, match="different plan"):
        prepare(root, "pilot", NICHES, THRESHOLDS, platforms=["youtube"])
    with run_lock(root), pytest.raises(ViralError, match="Another"):
        execute(root, "pilot", client, credit_ceiling=1, ledger=ledger)


def test_tiktok_evidence_reaches_grill_and_format_with_original_link():
    video, _ = normalize(post(), NOW, THRESHOLDS)
    grill_llm = FakeLLM('[]')
    expand_cluster({"niche": "ai_tools", "breakout_videos": [video]}, grill_llm, 1)
    evidence = grill_llm.calls[0]["user"]
    assert '"views_to_followers": 2.0001' in evidence
    assert '"multiplier_vs_median": null' in evidence
    assert video["source_url"] in evidence
    format_llm = FakeLLM(json.dumps({"name": "Quick reveal", "hook_type": "onscreen",
        "beats": ["Problem", "Reveal", "Payoff"], "visual_payoff": "Show result", "cta_pattern": "Follow"}))
    entry = draft_format(video, "ai_tools", format_llm)
    assert entry["watch_reference"] == video["source_url"]
    assert "channel median unavailable" in format_llm.calls[0]["user"]


def test_http_transport_redacts_reflected_key_and_forbids_redirects(monkeypatch):
    from modules.radar import viral_client
    key = "fake-secret-for-transport-test"
    class Response(io.BytesIO):
        code = 200
        headers = {"X-Credits-Charged": "1", "Authorization": "private"}
    class Opener:
        def open(self, request, timeout):
            assert request.get_header("Authorization") == "Bearer " + key
            assert timeout == 30
            return Response(json.dumps({"posts": [], "message": key}).encode())
    def opener(handler):
        assert handler.redirect_request(None, None, 302, None, None, "https://evil.test") is None
        return Opener()
    monkeypatch.setattr(viral_client.urllib.request, "build_opener", opener)
    result = ViralOutliersClient(key).request("POST", SEARCH_PATH, {})
    assert key not in json.dumps(result) and "Authorization" not in json.dumps(result)
    with pytest.raises(ViralError, match="Unsupported"):
        ViralOutliersClient(key).request("POST", "/api/v1/credits/topup", {})


def test_missing_key_stops_auth_request_without_network():
    with pytest.raises(ViralError, match="VIRAL_OUTLIERS_API_KEY"):
        ViralOutliersClient().credits()


@pytest.mark.parametrize('field,value', [('credit_quote', 0), ('criteria', {}), ('jobs', [])])
def test_invalid_saved_plan_cannot_bypass_credit_or_parameter_validation(tmp_path, field, value):
    transport = Transport()
    root, plan, client, ledger = batch(tmp_path, transport)
    plan[field] = value
    (root / 'pilot/plan.json').write_text(json.dumps(plan))
    with pytest.raises(ViralError, match='Invalid saved search plan'):
        execute(root, 'pilot', client, credit_ceiling=100, ledger=ledger)
    assert not transport.calls


def test_youtube_reference_and_subscribers():
    row = post(platform='youtube', postLink='https://youtu.be/abcdefghijk?si=tracking',
               followerCount=None, profile={'channel_id': 'UCabcDeF', 'subscriber_count': 10000})
    video, _ = normalize(row, NOW, THRESHOLDS)
    assert video['video_id'] == 'abcdefghijk'
    assert video['channel_id'] == 'youtube:UCabcDeF'
    assert video['source_url'] == 'https://www.youtube.com/watch?v=abcdefghijk'


def test_provider_selection_wired_to_weekly_without_youtube_or_llm_calls(tmp_path, monkeypatch):
    from modules.common import config
    from modules.orchestrate.__main__ import _live_weekly_clients
    from modules.radar import service
    transport = Transport([ok()])
    root = tmp_path / 'radar' / 'viral-outliers'
    prepare(root, 'pilot', NICHES, THRESHOLDS, platforms=['tiktok'])
    monkeypatch.setattr(service, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(config, 'secrets', lambda: {'VIRAL_OUTLIERS_API_KEY': 'fake'})
    monkeypatch.setattr(config, 'niches', lambda: {'niche': NICHES})
    monkeypatch.setattr(ViralOutliersClient, '_http', lambda self, *a: transport(*a))
    ledger = CostLedger(tmp_path / 'ledger.json', weekly_cap=1)
    clients = _live_weekly_clients({'radar': {**THRESHOLDS, 'provider': 'viral-outliers'}, 'grill': {}},
                                   ledger=ledger, run_id='pilot', credit_ceiling=1)
    report = clients['radar_scan']()
    assert report['scan_meta']['provider'] == 'viral-outliers'
    assert len(transport.paid_calls) == 1
    assert (tmp_path / 'radar' / (report['scan_meta']['scanned_at'][:10] + '.json')).exists()


def test_cli_default_plans_without_secrets_or_network(tmp_path, monkeypatch, capsys):
    from modules.radar import __main__ as cli
    monkeypatch.setattr(cli, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(cli, 'system', lambda: {'radar': {**THRESHOLDS, 'provider': 'viral-outliers'}})
    monkeypatch.setattr(cli, 'niches', lambda: {'niche': NICHES})
    monkeypatch.setattr(cli, 'secrets', lambda: pytest.fail('Plan must not read credentials'))
    assert cli.main(['--run-id', 'cli-pilot']) == 0
    assert 'credit-ceiling 2' in capsys.readouterr().out
    assert (tmp_path / 'radar/viral-outliers/cli-pilot/plan.json').exists()


def test_restart_validates_saved_charge_before_submitting_next_page(tmp_path, monkeypatch):
    from modules.radar import viral_scan
    transport = Transport([ok(**{'X-Credits-Charged': '2'})])
    root, _, client, ledger = batch(tmp_path, transport, pages=2)
    real_check = viral_scan.check_charge
    monkeypatch.setattr(viral_scan, 'check_charge', lambda *args: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        execute(root, 'pilot', client, credit_ceiling=2, ledger=ledger)
    monkeypatch.setattr(viral_scan, 'check_charge', real_check)
    with pytest.raises(ViralError, match='credit charge'):
        execute(root, 'pilot', client, credit_ceiling=2, ledger=ledger)
    assert len(transport.paid_calls) == 1


def test_youtube_handle_change_does_not_create_another_creator():
    a = post(platform='youtube', postLink='https://youtu.be/abcdefghijk',
             profile={'handle': 'before', 'channel_id': 'UCabcDeF'})
    b = {**a, 'profile': {'handle': 'after', 'channel_id': 'UCabcDeF'}}
    assert normalize(a, NOW, THRESHOLDS)[0]['channel_id'] == normalize(b, NOW, THRESHOLDS)[0]['channel_id']
