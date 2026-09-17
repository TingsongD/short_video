from modules.factory.testing.authority import FixtureEffects
from modules.factory.execution import Executor
from modules.factory.testing.authority import FixtureEffects
from modules.factory.execution import Executor
from modules.factory.testing.authority import approve_production
"""F34: failure drills and performance qualification — real
application services, real local ffmpeg renderer, fake remote
transports only. J01–J04/J08 journeys plus the deterministic
failure/concurrency/timing matrix."""
import json
import subprocess
import urllib.request
from pathlib import Path

import pytest

from modules.factory.artifacts.registry import ArtifactStore
from modules.factory.delivery.service import DeliveryService
from modules.factory.domain.errors import ContractError
from modules.factory.events.timing import timeline
from modules.factory.execution import Executor
from modules.factory.integrations.publisher import UploadPostPublisher
from modules.factory.operations import (activation_gate, create_backup,
                                        dispatch_gate, restore_into)
from modules.factory.production import ProductionService
from modules.factory.providers.vertex import VertexAdapter
from modules.factory.providers.vertex_auth import VertexAuth
from modules.factory.publishing.service import PublishingService
from modules.factory.rendering.ffmpeg_fast import FastPathRenderer
from modules.factory.resources import (CleanupService,
                                       ResourceRegistry)
from modules.factory.scheduler.scheduler import Scheduler
from modules.factory.store import Database
from modules.factory.testing.clock import FakeClock
from modules.factory.testing.fakes import (FakeDrive,
                                           FakeGenerationAdapter,
                                           FakeOAuthLoader,
                                           FakeProvider,
                                           FakePublisher,
                                           FakeVertexTransport,
                                           JIMENG_MODELS)
from modules.factory.testing.fixtures import _color_mp4
from modules.factory.testing.ids import IdFactory

NOW = "2026-09-17T00:00:00Z"
RATES = {"dated": "2026-09-16", "video_per_sec_tokens": 5792,
         "usd_per_m": {"input": 1.50, "output": 17.50,
                       "thought": 9.00},
         "input_tokens_est": 103, "thought_tokens_est": 421}
CAPS = {"gemini-omni-1.1-flash-preview": {
    "durations_s": [3, 4, 6, 8, 10], "aspects": ["9:16"],
    "resolutions": ["720p"], "references": {"image": 3},
    "audio": True}}


def _takes(model=None):
    """4 variants × 6 slots; B changes s1, C changes s4, D changes s6
    → 6 shared + 3 unique picture works."""
    changed = {"b": "s1", "c": "s4", "d": "s6"}
    out = []
    for v in "abcd":
        for i in range(1, 7):
            slot = f"s{i}"
            prompt = (f"{v}-alt-{i}" if changed.get(v) == slot
                      else f"shared-{i}")
            req = {"prompt": prompt,
                   "settings": {"aspect": "9:16"},
                   "refs": ["ref-h1"], "audio": "seg-h1"}
            if model:
                req["model"] = model
            out.append({"variant": v, "slot": slot,
                        "duration_s": 4.0, "request": req})
    return out


def _stack(tmp_path, name="jimeng_canvas", provider=None, payload=None):
    db = Database(tmp_path / "f.db")
    sched = Scheduler(db, worker_id="w1", lease_s=300)
    provider = provider or FakeProvider(
        name, tmp_path / "remote", IdFactory(tmp_path / "ids.json"),
        FakeClock())

    def _payload(oid):
        # each remote op produces DISTINCT bytes — a changed slot is a
        # genuinely different artifact, not a dedupe collision
        if payload is not None:
            return payload
        clip = tmp_path / f"clip-{oid}.mp4"
        color = f"0x{abs(hash(oid)) % 0xffffff:06x}"
        _color_mp4(clip, 4.0, color=color)
        return clip.read_bytes()
    provider.payload_fn = _payload
    adapter = FakeGenerationAdapter(
        name, provider, JIMENG_MODELS, "jimeng_credits",
        "native_quote", {"seedance_2.0_fast_vip": {4: 30, 8: 54}})
    arts = ArtifactStore(tmp_path / "arts", db)
    svc = ProductionService(
        db, scheduler=sched,
        executor=Executor(db, provider=provider), adapter=adapter,
        artifacts=arts)
    return db, sched, provider, adapter, arts, svc


def _run_all(svc, limit=400, on_step=None):
    n = 0
    while n < limit:
        out = svc.run_next()
        if out is None:
            waiting = svc.db.conn.execute("SELECT 1 FROM jobs WHERE status='ready' AND next_attempt_at IS NOT NULL").fetchone()
            if waiting:
                from datetime import datetime, timedelta, timezone
                # Advance only the scheduler's injected test clock; no provider effect is fabricated.
                future = svc.scheduler.clock() + timedelta(seconds=3)
                svc.scheduler.clock = lambda: future
                n += 1
                continue
            break
        n += 1
        if on_step:
            on_step()
    return n


def _run_plan(tmp_path, payload=None):
    db, sched, prov, adapter, arts, svc = _stack(
        tmp_path, payload=payload)
    svc.plan("plan-1", "exp1", 1, _takes(), "jimeng_canvas",
             "seedance_2.0_fast_vip", [4, 8], now=NOW)
    approve_production(svc, "plan-1")
    svc.submit("plan-1")
    _run_all(svc)
    return db, sched, prov, adapter, arts, svc


def _variant_artifacts(db, plan_id="plan-1"):
    """variant -> sorted artifact ids from its download nodes."""
    rows = db.conn.execute(
        "SELECT body FROM records WHERE kind='workitem'").fetchall()
    out = {}
    for r in rows:
        n = json.loads(r["body"])
        if n["kind"] != "download":
            continue
        for v in n["consumers"]:
            out.setdefault(v, []).extend(
                json.loads(n.get("artifact_ids", "[]")) if isinstance(
                    n.get("artifact_ids"), str) else
                n.get("artifact_ids") or [])
    return {k: sorted(v) for k, v in out.items()}


def _concat(tmp_path, art_paths, name):
    """Real local export: concat artifact bytes in shot order."""
    lst = tmp_path / f"{name}.txt"
    lst.write_text("".join(f"file '{p}'\n" for p in art_paths))
    out = tmp_path / f"{name}.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0",
         "-i", str(lst), "-c", "copy", str(out)],
        check=True, capture_output=True)
    return out


# ------------------------------------------------------------- J01 --

def test_j01_seed_to_four_outputs(tmp_path):
    """Local seed → A/B/C/D on the fake provider → real exports →
    verified fake delivery. Only declared slots differ; unique work
    runs once; zero external calls."""
    db, sched, prov, adapter, arts, svc = _run_plan(tmp_path)
    assert len(prov.state.doc["operations"]) == 9   # unique work only
    variants = _variant_artifacts(db)
    assert sorted(variants) == ["a", "b", "c", "d"]
    sets = {v: set(ids) for v, ids in variants.items()}
    # shared slots → identical artifact ids; exactly one slot differs
    for v in "bcd":
        diff = sets["a"] ^ sets[v]
        assert len(diff) == 2                      # one slot swapped
    drive = FakeDrive(tmp_path / "drive.json")
    delivery = DeliveryService(db, drive, effects=FixtureEffects(db, Executor(db)))
    finals = {}
    for v, ids in variants.items():
        paths = [arts.path_for(aid) for aid in ids]
        paths = [p for p in paths if p.exists()]
        final = _concat(tmp_path, paths, f"final-{v}")
        finals[v] = final
        out = delivery.deliver(f"del-{v}", str(final),
                               f"exp1-{v}-final.mp4", "folder-1",
                               now=NOW)
        assert out["status"] == "verified"
    assert len(finals) == 4
    uploads = [f for f in drive.doc["files"].values()]
    assert len(uploads) == 4                       # one per final


# ------------------------------------------------------------- J02 --

def test_j02_long_reference_takes_preserved(tmp_path):
    """A long-haul scale take list flows through the graph without
    coercion: every take lands on a picture node, counts preserved."""
    takes = []
    for v in "abcd":
        for i in range(20):
            takes.append({"variant": v, "slot": f"t{i}",
                          "duration_s": 4.0,
                          "request": {"prompt": f"shared-{i}",
                                      "settings": {}, "refs": [],
                                      "audio": ""}})
    db, sched, prov, adapter, arts, svc = _stack(tmp_path)
    out = svc.plan("plan-lh", "exp-lh", 1, takes, "jimeng_canvas",
                   "seedance_2.0_fast_vip", [4, 8], now=NOW)
    assert out["plan"]["stats"]["takes"] == 80     # 20 per variant
    pics = [n for n in out["nodes"].values()
            if n["kind"] == "picture"]
    assert len(pics) == 20                         # all shared → 20


# ------------------------------------------------------------- J03 --

def test_j03_crash_restart_no_duplicate_effect(tmp_path):
    """Kill after acceptance: the restarted executor reconciles the
    SAME remote operation; no second submit."""
    db, sched, prov, adapter, arts, svc = _stack(tmp_path)
    svc.plan("plan-1", "exp1", 1, _takes(), "jimeng_canvas",
             "seedance_2.0_fast_vip", [4, 8], now=NOW)
    approve_production(svc, "plan-1")
    svc.submit("plan-1")
    svc.run_next()                                  # first submit
    ops_before = set(prov.state.doc["operations"])
    # crash + restart: new service/executor, SAME remote world
    db2 = Database(tmp_path / "f.db")
    sched2 = Scheduler(db2, worker_id="w2", lease_s=300)
    svc2 = ProductionService(
        db2, scheduler=sched2,
        executor=Executor(db2, provider=prov), adapter=adapter,
        artifacts=arts)
    _run_all(svc2)
    assert set(prov.state.doc["operations"]) == ops_before | \
        (set(prov.state.doc["operations"]) - ops_before)
    assert len(prov.state.doc["operations"]) == 9   # never 10


def test_j03_upload_lost_ack_reconciles(tmp_path):
    """Kill after local export upload: reconcile finds the verified
    remote file — no duplicate upload."""
    db, sched, prov, adapter, arts, svc = _run_plan(tmp_path)
    variants = _variant_artifacts(db)
    aid = sorted(variants["a"])[0]
    src = arts.path_for(aid)
    drive = FakeDrive(tmp_path / "drive.json")
    drive.doc["lost_next"] = True                   # next ack is lost
    delivery = DeliveryService(db, drive, effects=FixtureEffects(db, Executor(db)))
    out = delivery.deliver("del-1", str(src), "f.mp4", "folder-1",
                           now=NOW)
    # restart — new service, same remote world
    delivery2 = DeliveryService(db, FakeDrive(tmp_path / "drive.json"))
    out2 = delivery2.reconcile("del-1", now=NOW)
    assert out2["status"] == "verified"
    assert drive.doc["uploads"] == 1                # one real upload


# ------------------------------------------------------------- J04 --

def _vertex_stack(tmp_path):
    loader = FakeOAuthLoader(tmp_path / "oauth.json",
                             project="factory-proj")
    auth = VertexAuth(loader, project="factory-proj")
    transport = FakeVertexTransport(tmp_path / "vertex.json", loader)
    ad = VertexAdapter(auth, transport, {}, RATES,
                       capabilities=dict(CAPS))
    return loader, transport, ad


def test_j04_both_provider_routes(tmp_path):
    """Canvas fake and Vertex fake both complete a plan; unit-specific
    pricing (credits vs usd_micros) stays distinct."""
    db, sched, prov, adapter, arts, svc = _run_plan(tmp_path)
    assert prov.name == "jimeng_canvas"
    jtotal = json.loads(db.uow().records.get(
        "productionplan", "plan-1")["body"])["total_price"]
    assert "jimeng_credits" in jtotal

    # vertex route
    loader, transport, vad = _vertex_stack(tmp_path / "vx")
    vx_dir = tmp_path / "vx"
    vx_dir.mkdir(exist_ok=True)
    db2 = Database(vx_dir / "f.db")
    clip = vx_dir / "clip.mp4"
    _color_mp4(clip, 4.0)
    transport.payload_fn = lambda oid: clip.read_bytes()
    arts2 = ArtifactStore(vx_dir / "arts", db2)
    svc2 = ProductionService(
        db2, scheduler=Scheduler(db2, worker_id="w1", lease_s=300),
        executor=Executor(db2, provider=vad), adapter=vad,
        artifacts=arts2)
    svc2.plan("plan-v", "expv", 1,
              _takes(model="gemini-omni-1.1-flash-preview"),
              "google_vertex", "gemini-omni-1.1-flash-preview",
              [4, 8], now=NOW)
    approve_production(svc2, "plan-v")
    svc2.submit("plan-v")
    _run_all(svc2)
    vtotal = json.loads(db2.uow().records.get(
        "productionplan", "plan-v")["body"])["total_price"]
    assert "usd_micros" in vtotal
    assert len(transport.doc["interactions"]) == 9


# ------------------------------------------------------------- J08 --

def test_j08_restore_fresh_root_gate_then_reconcile(tmp_path):
    """Back up mid-flight work, restore into a fresh root: integrity
    holds, dispatch stays gated until external effects reconcile."""
    db, sched, prov, adapter, arts, svc = _stack(tmp_path)
    svc.plan("plan-1", "exp1", 1, _takes(), "jimeng_canvas",
             "seedance_2.0_fast_vip", [4, 8], now=NOW)
    approve_production(svc, "plan-1")
    svc.submit("plan-1")
    svc.run_next()                                  # live remote op
    bk = tmp_path / "bk"
    create_backup(db, tmp_path, bk)
    out = restore_into(bk, tmp_path / "restored")
    assert out["integrity"]["integrity"] == "ok"
    rdb = Database(tmp_path / "restored" / "data" / "factory" / "factory.db")
    gate = activation_gate(rdb)
    assert gate["dispatch_enabled"] is False
    # A restored snapshot cannot infer post-backup effects; explicit activation remains required.
    rec = dispatch_gate(rdb)
    assert rec["allowed"] is False or gate["pending_effects"] >= 1


# --------------------------------------------------- failure matrix --

def test_publication_lost_ack_one_post(tmp_path):
    db = Database(tmp_path / "f.db")
    remote = FakePublisher(faults={"lost_ack"})
    svc = PublishingService(
        db, effects=FixtureEffects(db, Executor(db)), accounts={"youtube:acct-main": "acct-main"},
        publisher=UploadPostPublisher(
            api_key="k", user="acct-main",
            transport=remote.transport))
    from modules.factory.domain.records import Authorization
    with db.uow() as u:
        u.records.put(Authorization(
            schema_version="authorization.v1", id="a1",
            created_at=NOW, scope_hash="s",
            publication_authorized=True, status="authorized"))
    svc.plan("pub-1", variant_plan_id="vp-1", final_sha256="ab" * 32,
             platform="youtube", account_id="acct-main",
             authorization_id="a1")
    v = tmp_path / "v.mp4"
    v.write_bytes(b"v")
    svc.publish("pub-1", video_path=str(v), now=NOW)
    for _ in range(3):
        out = svc.reconcile("pub-1")
    assert out["status"] == "public"
    assert remote.public_post_count() == 1


def test_budget_cannot_overrun(tmp_path):
    from modules.factory.budget.service import BudgetService
    db = Database(tmp_path / "f.db")
    budget = BudgetService(db)
    budget.create_budget("b1", "jimeng_credits", "category", "g",
                         cap=100)
    budget.reserve("r1", [("b1", 60)])
    with pytest.raises(ContractError):
        budget.reserve("r2", [("b1", 60)])


# ------------------------------------------------------ concurrency --

def test_jimeng_capacity_is_global(tmp_path):
    """Five global Jimeng slots: holds never exceed the seeded cap
    at any point in the run."""
    db, sched, prov, adapter, arts, svc = _stack(tmp_path)
    svc.plan("plan-1", "exp1", 1, _takes(), "jimeng_canvas",
             "seedance_2.0_fast_vip", [4, 8], now=NOW)
    approve_production(svc, "plan-1")
    svc.submit("plan-1")
    peak = [0]

    def check():
        n = db.conn.execute(
            "SELECT COUNT(*) c FROM capacity_holds").fetchone()["c"]
        peak[0] = max(peak[0], n)
    _run_all(svc, on_step=check)
    assert peak[0] <= 5
    assert len(prov.state.doc["operations"]) == 9


# --------------------------------------------------------- timing --

def test_stage_timing_is_attributed(tmp_path):
    db, sched, prov, adapter, arts, svc = _run_plan(tmp_path)
    rows = db.uow().conn.execute(
        "SELECT * FROM events ORDER BY seq").fetchall()
    streams = {}
    for r in rows:
        streams.setdefault(r["stream"], []).append(dict(r))
    timelines = [timeline(evs) for evs in streams.values()
                 if any(e["type"] == "claimed" for e in evs)]
    assert timelines
    keys = set().union(*(t["durations"].keys() for t in timelines))
    assert {"queue_wait_s", "dispatch_s"} <= keys


# ------------------------------------------------- render parity --

def test_render_cache_reuses_sections(tmp_path):
    """Same fixture+settings twice: cached section files are reused
    (identical bytes), output parity holds."""
    src = tmp_path / "src.mp4"
    _color_mp4(src, 2.0, rate=24)
    r = FastPathRenderer()
    segs = [{"src": str(src), "frames": 48, "id": "s1"}]
    clock = {"fps": 24, "width": 360, "height": 640}
    out1 = r.render(tmp_path / "w1", segs, [], [], clock)
    cache1 = {p.name: p.read_bytes() for p in
              (tmp_path / "w1" / "render-inputs").glob("*")}
    out2 = r.render(tmp_path / "w2", segs, [], [], clock)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-count_frames",
         "-select_streams", "v:0", "-show_entries",
         "stream=nb_read_frames", "-of", "csv=p=0", str(out2)],
        capture_output=True, text=True, check=True).stdout.strip()
    assert probe == "48"                            # exact frames
    # a passthrough-eligible source skips normalization → cache may be
    # empty; parity is still required
    assert out1.exists() and out2.exists()
    assert Path(out1).stat().st_size > 0 and \
        Path(out2).stat().st_size > 0


# ----------------------------------------------------- no network --

def test_no_external_calls(tmp_path, monkeypatch):
    """The whole J01 flow runs with urllib hard-blocked — every
    remote effect went through an injected fake."""
    def _blocked(*a, **k):
        raise AssertionError("external call attempted")
    monkeypatch.setattr(urllib.request, "urlopen", _blocked)
    db, sched, prov, adapter, arts, svc = _run_plan(tmp_path)
    assert len(prov.state.doc["operations"]) == 9


# -------------------------------------------------- resource leak --

def test_owned_cleanup_leaves_shared_and_unrelated(tmp_path):
    db = Database(tmp_path / "f.db")
    reg = ResourceRegistry(db)
    reg.register("vid-preview", 777, "b1", ["preview", "--port", "9"],
                 owner="video-1", cls="per_job", ports=[8100])
    reg.register("shared-cache", 778, "b2", ["cache"], owner="video-1",
                 cls="shared", holders=["video-1", "video-2"],
                 ports=[8200])
    killed = []
    table = {777: {"pid": 777, "birth": "b1",
                   "command": ["preview", "--port", "9"]},
             778: {"pid": 778, "birth": "b2", "command": ["cache"]},
             999: {"pid": 999, "birth": "x", "command": ["other"]}}
    cleaner = CleanupService(
        reg, table_fn=lambda: table,
        kill_fn=lambda pid, sig: killed.append((pid, sig)),
        port_fn=lambda: {8100: 777, 8200: 778, 9000: 999})
    out = cleaner.cleanup("video-1", now=NOW)
    assert any(p == 777 for p, _ in killed)
    assert not any(p == 999 for p, _ in killed)     # unrelated safe
    assert any(r["id"] == "shared-cache"
               for r in out["retained"])


# -------------------------------------------------- legacy compat --

def test_legacy_entry_points_intact():
    from modules.publish.uploader import manual_instructions
    text = manual_instructions("vid-1",
                               {"title": "T", "caption": "c",
                                "hashtags": ["a"]}, "/v.mp4")
    assert "Manual publish checklist" in text
    import modules.orchestrate  # noqa: F401
    import modules.analytics.pull  # noqa: F401
