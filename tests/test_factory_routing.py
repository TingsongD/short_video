from modules.factory.testing.authority import approve_operation
"""F15 — shared generation contract and provider routing."""
import pytest

from modules.factory.domain.errors import ContractError
from modules.factory.domain.money import Money
from modules.factory.domain.records import (
    Authorization, GenerationRequest, ProviderPolicy)
from modules.factory.providers import (
    CapabilityCatalog, CapabilitySnapshot, ProviderRouter)
from modules.factory.providers.catalog import snapshot_id
from modules.factory.store import Database
from modules.factory.testing.clock import FakeClock
from modules.factory.testing.fakes import (
    FakeGenerationAdapter, FakeProvider, JIMENG_MODELS, VERTEX_MODELS)
from modules.factory.testing.ids import IdFactory

NOW = "2026-09-16T12:00:00Z"


@pytest.fixture
def env(tmp_path):
    db = Database(tmp_path / "f.db")
    ids = IdFactory(tmp_path / "ids.json")
    clock = FakeClock()
    jp = FakeProvider("jimeng", tmp_path / "remote", ids, clock,
                      unit="jimeng_credits")
    vp = FakeProvider("vertex", tmp_path / "remote", ids, clock,
                      unit="usd_micros")
    adapters = {
        "jimeng_canvas": FakeGenerationAdapter(
            "jimeng_canvas", jp, JIMENG_MODELS, "jimeng_credits",
            "native_quote",
            {"seedance_2.0_fast_vip": {"*": 54, 4: 30, 8: 54}}),
        "google_vertex": FakeGenerationAdapter(
            "google_vertex", vp, VERTEX_MODELS, "usd_micros",
            "usage_estimate",
            {"omni-1": {"*": 100_000, 4: 60_000, 8: 120_000}})}
    catalog = CapabilityCatalog(db)
    for provider, models, support in (
            ("jimeng_canvas", JIMENG_MODELS, "qualified"),
            ("google_vertex", VERTEX_MODELS, "observed")):
        for model, caps in models.items():
            for mode in ("text", "image_ref", "video_ref"):
                catalog.put(CapabilitySnapshot(
                    schema_version="capability.v1",
                    id=snapshot_id(provider, model, "", mode),
                    created_at=NOW, provider=provider, model=model,
                    input_mode=mode, support=support,
                    capabilities=caps, observed_at=NOW,
                    valid_until="2026-10-01T00:00:00Z"))
    router = ProviderRouter(db, adapters, catalog)
    return {"db": db, "router": router, "catalog": catalog,
            "adapters": adapters, "jp": jp, "vp": vp}


def _req(model="", provider="", duration=4.0, roles=None):
    r = GenerationRequest(
        schema_version="gen_request.v1", id="gr-1",
        created_at=NOW, experiment_id="exp1", experiment_revision=1,
        variant_key="A", segment_id="seg0", prompt="product shot",
        provider=provider, model=model,
        requested_duration_s=duration, required_usable_s=duration,
        aspect="9:16", resolution="1080x1920",
        reference_artifact_ids=list((roles or {}).keys()),
        reference_roles=roles or {})
    r.finalize_hash()
    return r


class TestExplicitRouting:
    def test_jimeng_route(self, env):
        d = env["router"].route(_req(), ProviderPolicy(choice="jimeng"),
                                now=NOW)
        assert d["provider"] == "jimeng_canvas"
        assert d["model"] == "seedance_2.0_fast_vip"
        assert d["duration_s"] == 4
        assert d["price"] == Money("jimeng_credits", 30)

    def test_vertex_route(self, env):
        d = env["router"].route(_req(), ProviderPolicy(choice="vertex"),
                                now=NOW)
        assert d["provider"] == "google_vertex"
        assert d["price"].unit == "usd_micros"

    def test_duration_rounds_up_to_supported(self, env):
        d = env["router"].route(_req(duration=5.0),
                                ProviderPolicy(choice="vertex"), now=NOW)
        assert d["duration_s"] == 6          # smallest covering choice

    def test_duration_uncovered_named(self, env):
        with pytest.raises(ContractError) as e:
            env["router"].route(_req(duration=9.0),
                                ProviderPolicy(choice="jimeng"), now=NOW)
        assert "duration_uncovered" in e.value.detail

    def test_unsupported_reference_mode(self, env):
        req = _req(roles={"art:1": "video"})
        with pytest.raises(ContractError) as e:
            env["router"].route(req, ProviderPolicy(choice="jimeng"),
                                now=NOW)
        assert "unsupported_reference_video" in e.value.detail

    def test_plan_lock_blocks_other_provider(self, env):
        req = _req(provider="google_vertex", model="omni-1")
        with pytest.raises(ContractError) as e:
            env["router"].route(req, ProviderPolicy(choice="jimeng"),
                                now=NOW)
        assert "plan_locked_to" in e.value.detail

    def test_model_lock_enforced(self, env):
        req = _req(provider="jimeng_canvas", model="some_other")
        with pytest.raises(ContractError) as e:
            env["router"].route(req, ProviderPolicy(choice="jimeng"),
                                now=NOW)
        assert "model_locked_to" in e.value.detail or \
            "no_capability_snapshot" in e.value.detail


class TestCapabilityEvidence:
    def test_advertised_only_unqualified(self, env):
        snap = env["catalog"].latest("google_vertex", "omni-1",
                                     "", "text", NOW)["snapshot"]
        snap.support = "advertised"
        snap.revision += 1
        env["catalog"].put(snap)
        with pytest.raises(ContractError) as e:
            env["router"].route(_req(), ProviderPolicy(choice="vertex"),
                                now=NOW)
        assert "unqualified_support" in e.value.detail

    def test_stale_snapshot_named(self, env):
        with pytest.raises(ContractError) as e:
            env["router"].route(
                _req(), ProviderPolicy(choice="jimeng"),
                now="2026-12-01T00:00:00Z")
        assert "stale_capability_snapshot" in e.value.detail

    def test_missing_snapshot_named(self, env):
        req = _req()
        req.provider = "jimeng_canvas"
        req.model = "seedance_2.0_fast_vip"
        req.region = "moon-base-1"          # no snapshot for location
        with pytest.raises(ContractError) as e:
            env["router"].route(req, ProviderPolicy(choice="jimeng"),
                                now=NOW)
        assert "no_capability_snapshot" in e.value.detail


class TestAuthorization:
    def test_usd_cap_enforced(self, env):
        auth = Authorization(
            schema_version="authorization.v1", id="auth-1",
            created_at=NOW, scope_hash="h",
            allowed_providers=["google_vertex"],
            caps={"usd_micros": 50_000}, status="authorized",
            allowed_models={"google_vertex": ["omni-1"]}, valid_until="2026-10-01T00:00:00Z")
        with pytest.raises(ContractError) as e:
            env["router"].route(_req(), ProviderPolicy(choice="vertex"),
                                authorization=auth, now=NOW)
        assert "exceeds_cap" in e.value.detail

    def test_credits_never_pay_usd(self, env):
        # jimeng credits budget can't satisfy a vertex request — the
        # route prices in usd_micros, a different unit entirely
        d = env["router"].route(_req(), ProviderPolicy(choice="vertex"),
                                now=NOW)
        assert d["price"].unit == "usd_micros"
        assert d["price"].unit != "jimeng_credits"


class TestFallback:
    def test_fallback_policy_prefers_jimeng(self, env):
        d = env["router"].route(
            _req(), ProviderPolicy(choice="jimeng_with_vertex_fallback"),
            now=NOW)
        assert d["provider"] == "jimeng_canvas"

    def test_fallback_to_vertex_when_jimeng_ineligible(self, env):
        # request needs a video reference — jimeng can't take it
        req = _req(roles={"art:1": "video"})
        d = env["router"].route(
            req, ProviderPolicy(choice="jimeng_with_vertex_fallback"),
            now=NOW)
        assert d["provider"] == "google_vertex"
        assert "jimeng_canvas" in d["rejected"]
        assert any("unsupported_reference_video" in w
                   for w in d["rejected"]["jimeng_canvas"])

    def test_fallback_suppressed_while_original_unresolved(self, env):
        from modules.factory.execution import Executor
        ex = Executor(env["db"], env["jp"], FakeClock())
        router = ProviderRouter(env["db"], env["adapters"],
                                env["catalog"], executor=ex)
        att = approve_operation(env["db"], ex, {"prompt": "x"}, "job:g1", kind="generation", provider="jimeng_canvas", model="fast", unit="jimeng_credits")
        ex.submit(att)
        assert router.fallback_blocked_reason(att) == \
            "original_unresolved"

    def test_fallback_allowed_after_terminal(self, env):
        from modules.factory.execution import Executor
        ex = Executor(env["db"], env["jp"], FakeClock())
        router = ProviderRouter(env["db"], env["adapters"],
                                env["catalog"], executor=ex)
        att = approve_operation(env["db"], ex, {"prompt": "x"}, "job:g2", kind="generation", provider="jimeng_canvas", model="fast", unit="jimeng_credits")
        op = ex.submit(att)
        ex.request_cancel(att)
        ex.poll(att)                     # cancellation alone does not settle charge
        assert router.fallback_blocked_reason(att) == "original_unresolved"
        from modules.factory.execution.effects import EffectService
        EffectService(env["db"]).settle(att, 0, "native_quote", "verified no charge")
        assert router.fallback_blocked_reason(att) is None
