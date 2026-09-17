"""Adapter regression checks against installed CLI and saved pilot contracts."""
import pytest
from modules.assets.canvas_cli import CanvasCLI
from modules.factory.providers.canvas import CanvasAdapter
from modules.factory.domain.money import Money
from modules.factory.testing.fakes import FakeCanvasRunner, ProviderError

REQ = {"video_id": "video-one", "prompt": "product", "model": "seedance_2.0_fast_vip", "duration_s": 4}


def test_canvas_cannot_increase_approved_ceiling(tmp_path):
    runner = FakeCanvasRunner(tmp_path / "remote.json")
    adapter = CanvasAdapter(CanvasCLI(runner=runner), {})
    with pytest.raises(ProviderError, match="quote_exceeds_approval"):
        adapter.submit(REQ, price=Money("jimeng_credits", 1))
    assert runner.doc["ops"] == {}


def test_canvas_allocates_identities_before_create_and_uses_one_canvas(tmp_path):
    seen = []
    runner = FakeCanvasRunner(tmp_path / "remote.json")
    def checked(argv, **kw):
        if "create" in argv and "canvas" in argv:
            assert "--project-id" in argv
            assert "--title" not in argv
        if "create" in argv and "node" in argv:
            assert "--node-id" in argv and "--update-id" in argv
        seen.append(argv)
        return runner(argv, **kw)
    adapter = CanvasAdapter(CanvasCLI(runner=checked), {})
    adapter.prepare(REQ)
    adapter.prepare(dict(REQ, prompt="second shot"))
    assert sum("canvas" in x and "create" in x for x in seen) == 1


def test_canvas_detects_draft_edit_before_charging(tmp_path):
    runner = FakeCanvasRunner(tmp_path / "remote.json")
    adapter = CanvasAdapter(CanvasCLI(runner=runner), {})
    draft = adapter.prepare(REQ)
    runner.doc["nodes"][draft["node_id"]]["generation"]["prompt"] = "changed"
    runner._save()
    with pytest.raises(ProviderError, match="draft_changed"):
        adapter.submit(REQ, price=Money("jimeng_credits", 54))
    assert not runner.doc["ops"]


def test_canvas_lost_ack_recovers_from_disk_without_new_run(tmp_path):
    from modules.factory.providers.state import DurableState
    runner = FakeCanvasRunner(tmp_path / "remote.json")
    adapter = CanvasAdapter(CanvasCLI(runner=runner), DurableState(tmp_path / "adapter.json"))
    runner.lose_next_run()
    with pytest.raises(ProviderError):
        adapter.submit(REQ, price=Money("jimeng_credits", 54))
    restarted_remote = FakeCanvasRunner(tmp_path / "remote.json")
    restarted = CanvasAdapter(CanvasCLI(runner=restarted_remote), DurableState(tmp_path / "adapter.json"))
    outcome = restarted.submit(REQ, price=Money("jimeng_credits", 54))
    assert outcome["status"] in ("running", "succeeded")
    assert len(restarted_remote.doc["ops"]) == 1


def test_vertex_actual_pilot_shape_and_durable_ambiguous_submission(tmp_path):
    from modules.factory.providers.vertex import VertexAdapter
    from modules.factory.providers.vertex_auth import VertexAuth
    from modules.factory.providers.state import DurableState
    from modules.factory.testing.fakes import FakeOAuthLoader, FakeVertexTransport
    from test_factory_vertex import RATES, CAPS, REQ as request
    loader = FakeOAuthLoader(tmp_path / "oauth.json")
    transport = FakeVertexTransport(tmp_path / "remote.json", loader)
    adapter = VertexAdapter(VertexAuth(loader, "factory-proj"), transport, DurableState(tmp_path / "adapter.json"), RATES, capabilities=CAPS)
    transport.lose_next_post()
    with pytest.raises(ProviderError, match="transport_timeout"):
        adapter.submit(request)
    restarted = VertexAdapter(VertexAuth(loader, "factory-proj"), transport, DurableState(tmp_path / "adapter.json"), RATES, capabilities=CAPS)
    with pytest.raises(ProviderError, match="submission_unresolved"):
        restarted.submit(request)
    assert len(transport.doc["interactions"]) == 1
    assert "ya29" not in (tmp_path / "adapter.json").read_text()


def test_shopify_paginates_variants_and_keeps_native_currency(tmp_path):
    from modules.factory.integrations.shopify import LiveShopifyAdmin
    from modules.factory.products.importer import _money
    calls = []
    variant = {"id": "v1", "title": "Small", "availableForSale": True, "price": "29.95"}
    def transport(query, variables):
        assert "price {" not in query
        calls.append(variables)
        if variables.get("cursor"):
            return 200, {"data": {"product": {"variants": {"nodes": [dict(variant, id="v2")],
                     "pageInfo": {"hasNextPage": False, "endCursor": None}}}}}
        return 200, {"data": {"shop": {"currencyCode": "CAD"}, "productByHandle": {
            "id": "p1", "handle": "tank", "title": "Tank", "status": "ACTIVE", "variants": {
                "nodes": [variant], "pageInfo": {"hasNextPage": True, "endCursor": "v1"}},
            "media": {"nodes": [], "pageInfo": {"hasNextPage": True, "endCursor": "m1"}}}}}
    product = LiveShopifyAdmin(transport).product_by_handle("tank")
    assert len(product["variants"]) == 2 and len(calls) == 2
    assert product["media_has_next"] is True
    assert product["variants"][0]["price"]["currencyCode"] == "CAD"
    assert _money(product["variants"][0]["price"]) is None


def test_shopify_media_redirects_and_size_are_checked(tmp_path):
    from modules.factory.integrations.shopify import LiveShopifyAdmin
    from modules.factory.seeds.ssrf import SSRFError
    adapter = LiveShopifyAdmin(lambda q, v: (200, {}), resolver=lambda host: ["93.184.216.34"],
        media_transport=lambda *a: (302, {"location": "http://169.254.169.254/"}, b""))
    with pytest.raises(SSRFError):
        adapter.media_download("https://cdn.example.org/photo")
    adapter._media_transport = lambda *a: (200, {}, b"12345")
    adapter._max_bytes = 4
    with pytest.raises(ProviderError, match="oversize"):
        adapter.media_download("https://cdn.example.org/photo")


def test_synchronous_receipt_survives_restart_without_research_refetch(tmp_path):
    from modules.factory.integrations.viral_outliers import ViralOutliersSource
    calls = []
    def transport(*args):
        calls.append(args)
        return 200, {"content-type": "video/mp4"}, b"source video"
    source = ViralOutliersSource(transport, tmp_path / "receipts", resolver=lambda host: ["93.184.216.34"])
    req = {"kind": "media", "url": "https://example.org/video"}
    first = source.submit(req)
    second = ViralOutliersSource(transport, tmp_path / "receipts").submit(req)
    assert second["operation_id"] == first["operation_id"] and len(calls) == 1
    assert source.download(first["operation_id"])["bytes"] == b"source video"


def test_elevenlabs_v3_alignment_and_audio_receipt(tmp_path):
    import base64
    import json
    from modules.factory.providers.elevenlabs import ElevenLabsAdapter
    from modules.factory.testing.fakes import _wav_bytes
    calls = []
    def transport(method, url, payload, headers):
        assert "with-timestamps" in url
        body = json.loads(payload)
        assert body["model_id"] == "eleven_v3" and body["text"] == "Hi"
        calls.append(url)
        return 200, {"x-character-count": "2", "request-id": "fixture"}, json.dumps({
            "audio_base64": base64.b64encode(_wav_bytes(.5)).decode(), "alignment": {
                "characters": ["H", "i"], "character_start_times_seconds": [0, .2], "character_end_times_seconds": [.2, .4]}}).encode()
    request = {"voice_id": "TestVoice", "model": "eleven_v3", "text": "Hi", "language": "en", "settings": {}}
    first = ElevenLabsAdapter(tmp_path, transport=transport).submit(request)
    adapter = ElevenLabsAdapter(tmp_path, transport=transport)
    assert adapter.submit(request)["operation_id"] == first["operation_id"]
    assert len(calls) == 1
    assert adapter.download(first["operation_id"])["alignment"]["characters"] == ["H", "i"]


def test_native_hypit_failure_envelope_is_terminal_even_with_exit_one(tmp_path):
    import json
    from types import SimpleNamespace
    from modules.factory.rendering import HypitBuildRunner
    def runner(argv):
        assert argv == ["status", "b-existing", "--workspace", str(tmp_path)]
        return SimpleNamespace(returncode=1, stdout=json.dumps({"format": "hypit.cli-status@1", "build": {
            "id": "b-existing", "work": {"state": "done", "outcome": "failed"}, "result": {"state": "failed"}}}))
    assert HypitBuildRunner(runner).observe("b-existing", tmp_path)["status"] == "failed"


def test_research_receipt_reuses_verified_search_route(tmp_path):
    from modules.factory.integrations.research import ViralOutliersSearch
    from modules.radar.viral_client import ViralOutliersClient
    calls = []
    def transport(method, path, body):
        assert method == "POST" and path == "/api/v1/search/content"
        assert body["pageSize"] == 20 and body["sortBy"] == "views_desc"
        calls.append(body)
        return 200, {"x-credits-charged": "1"}, {"posts": [{"id": "post1", "platform": "youtube",
            "profile": {"id": "creator1", "subscriberCount": 100}, "views": 1000, "contentType": "short",
            "publishedAt": "2026-09-01T12:00:00Z", "postLink": "https://www.youtube.com/shorts/abcdefghijk"}]}
    client = ViralOutliersClient(transport=transport)
    req = {"kind": "search", "query": "fashion", "page": 1, "page_size": 20}
    first = ViralOutliersSearch(tmp_path, client, "research-account").submit(req)
    second = ViralOutliersSearch(tmp_path, client, "research-account").submit(req)
    assert first["operation_id"] == second["operation_id"] and len(calls) == 1
    assert second["result"]["posts"][0]["creator_id"] == "creator1"
