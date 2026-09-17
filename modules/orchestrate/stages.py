"""M11 stage wiring for run.sh commands.

Externals (LLM, TTS, YouTube, Pexels, MPT runner, uploader) arrive via a
ctx dict so unit tests stay offline; the CLI builds real clients from
config/secrets. Paid stages always run authorize -> approval -> call ->
ledger record — in that order, so an unapproved or over-cap run never
reaches the vendor.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from modules.common.config import DATA_DIR
from modules.orchestrate import approval

STAGE_ORDER_PRODUCE = ["hook", "script", "assets", "voice",
                     "assemble", "qc", "publish"]
STAGE_ORDER_WEEKLY = ["radar", "grill", "formats"]
STAGE_ORDER_READBACK = ["due", "pull", "record"]


def find_idea(idea_id, grill_dir=None):
    """Return the grill-passed idea; produce only runs on approved ideas."""
    d = Path(grill_dir or DATA_DIR / "grill")
    for p in sorted(d.glob("*.json"), reverse=True):
        doc = json.loads(p.read_text())
        for idea in doc.get("ideas", []):
            if idea.get("idea_id") == idea_id:
                if idea.get("status") != "pass":
                    raise ValueError(
                        f"idea {idea_id} status={idea.get('status')!r} — "
                        "produce only runs on grill-approved ideas")
                return idea
    raise KeyError(f"idea {idea_id} not found in {d}")


def paid_call(ledger, service, est_cost, fn, cost_of, approvals_dir=None, now=None):
    """Hard cap -> approval gate -> paid call -> ledger entry."""
    ledger.authorize(service, est_cost)
    approval.require("spend", f"{service} ~${est_cost:.3f}", approvals_dir, now=now)
    result = fn()
    cost, extra = cost_of(result)
    ledger.record(service, cost, **extra)
    return result


def produce_stages(idea_id, ctx):
    """Ordered M4->M9 stage closures for `run.sh produce <idea_id>`.

    ctx keys: config, ledger, llm, tts, pexels, mpt_runner, uploader,
    hooks_path, formats_path; optional: grill_dir, base_dir, approvals_dir,
    video_id, est (cost estimates), published_dir, analytics hooks.
    """
    from modules.assets import queue
    from modules.assets.canvas import fingerprint
    from modules.assets.canvas_state import atomic_json
    from modules.assemble.materials import prepare_clips, narration_duration, file_hash
    from modules.orchestrate.assets import production_assets
    from modules.orchestrate.checkpoint import Checkpoint
    from modules.assemble import qc as qc_mod
    from modules.assemble import task_builder
    from modules.formats import library as format_lib
    from modules.formats import match as match_mod
    from modules.hooks import select as hook_sel
    from modules.publish import metadata as meta_mod
    from modules.publish import record as rec_mod
    from modules.script import engine

    cfg = ctx["config"]
    ledger = ctx["ledger"]
    est = ctx.get("est", {})
    approvals_dir = ctx.get("approvals_dir")
    base = Path(ctx.get("base_dir") or DATA_DIR / "production")

    idea = find_idea(idea_id, ctx.get("grill_dir"))
    video_id = ctx.get("video_id") or f"v-{idea_id}"
    queue.validate_video_id(video_id)
    directory = base / video_id
    checkpoint = Checkpoint(directory, video_id, idea_id)
    state = {}

    def hook():
        saved = directory / "shot_list.json"
        if saved.exists():
            if not ctx.get("resume"):
                raise ValueError("production already exists; use --resume or a new --video-id")
            doc = queue.validate_shots(json.loads(saved.read_text()))
            if doc["video_id"] != video_id or doc["idea_id"] != idea_id:
                raise ValueError("saved shot list belongs to a different production")
            checkpoint.script(doc)
            state["shot_list"] = doc
            state["shot_list_path"] = saved
            lib = format_lib.load(ctx["formats_path"])
            state["format"] = format_lib.get(lib, doc["format_id"])
            return
        if ctx.get("resume"):
            raise ValueError("no saved shot list to resume")
        hooks = hook_sel.load_bank(ctx["hooks_path"])
        lib = format_lib.load(ctx["formats_path"])
        fmt_id = match_mod.match_ideas(
            [idea], lib["formats"])[idea["idea_id"]]["format_id"]
        state["format"] = format_lib.get(lib, fmt_id)
        state["hook"] = hook_sel.select(
            hooks, idea["niche"], state["format"].get("hook_type"))

    def script():
        if "shot_list" in state:
            return
        e = est.get("llm", 0.05)
        doc = paid_call(
            ledger, "llm", e,
            lambda: engine.build_shot_list(
                idea, state["format"], state["hook"]["text"],
                video_id, ctx["llm"]),
            lambda d: (e, {"units": len(d.get("voice_text", "")),
                           "unit_type": "chars", "video_id": video_id}),
            approvals_dir)
        state["shot_list"] = doc
        state["shot_list_path"] = engine.save_shot_list(doc, out_dir=base)
        checkpoint.script(doc)

    def assets():
        state["manifest"] = production_assets(state["shot_list"], ctx, base)
        state["assets_dir"] = directory / "assets"

    def voice():
        e = est.get("elevenlabs", 0.20)
        out = directory / "voice.mp3"
        identity = fingerprint({"text": state["shot_list"]["voice_text"], "settings": cfg["voice"]})
        saved = checkpoint.data.get("voice", {})
        if saved and saved.get("fingerprint") != identity:
            raise ValueError("narration settings changed; review before starting a new production")
        if out.exists():
            if not saved or (saved.get("sha256") and saved["sha256"] != file_hash(out)):
                raise ValueError("existing narration has no matching receipt; review it before reuse")
        else:
            if saved:
                raise RuntimeError("narration file missing after a previous attempt; restore it or review before regenerating")
            def synthesize():
                checkpoint.save(voice={"fingerprint": identity, "state": "submitting"})
                result = ctx["tts"].synthesize(state["shot_list"]["voice_text"], out)
                if Path(result).resolve() != out.resolve():
                    raise ValueError("TTS returned an unexpected output path")
                return result
            paid_call(
                ledger, "elevenlabs", e, synthesize,
                lambda p: (e, {"units": len(state["shot_list"]["voice_text"]),
                               "unit_type": "chars", "video_id": video_id}),
                approvals_dir)
        lo, hi = cfg["voice"]["min_duration_s"], cfg["voice"]["max_duration_s"]
        duration = narration_duration(out)
        if not lo <= duration <= hi:
            raise RuntimeError(f"voice duration out of bounds {lo}-{hi}s")
        checkpoint.save(voice={"fingerprint": identity, "state": "validated", "sha256": file_hash(out)})
        state["voice_path"], state["voice_duration"] = out, duration

    def assemble():
        resolution = tuple(map(int, cfg["assembly"]["resolution"].split("x")))
        prepared = ctx.get("prepare_clips", prepare_clips)(
            directory, state["shot_list"], state["manifest"], resolution)
        task = task_builder.build_task(
            video_id, state["shot_list"], state["manifest"],
            cfg["assembly"], idea["topic"], prepared=prepared)
        identity = fingerprint({"prepared": prepared["fingerprint"], "task": task})
        cached = checkpoint.valid_final(identity) if ctx.get("resume") else None
        if cached and all(qc_mod.qc_video(f, expected_res=resolution,
                                        voice_duration=state["voice_duration"])[0] for f in cached):
            state["finals"] = cached
            return
        task_builder.write_task(task, video_dir=base / video_id)
        batch = task_builder.write_batch([task], base / video_id / "batch.json")
        from modules.assemble.runner import run_batch
        runner = ctx.get("mpt_runner")
        state["assemble_result"] = run_batch(
            batch, output_dir=directory, **({"runner": runner} if runner else {}))
        finals = [Path(p) for p in state["assemble_result"]["finals"]]
        state["finals"] = finals
        checkpoint.save(assembly={"fingerprint": identity, "finals": [
            {"path": str(p.resolve()), "sha256": file_hash(p)} for p in finals]})
        atomic_json(directory / "assembly_result.json", state["assemble_result"])

    def qc():
        durations = []
        for f in state["finals"]:
            ok, failures = qc_mod.qc_video(
                f, expected_res=tuple(
                    int(x) for x in cfg["assembly"]["resolution"].split("x")),
                voice_duration=state["voice_duration"])
            if not ok:
                raise RuntimeError(f"QC failed for {f.name}: {failures}")
            data = qc_mod.probe_full(f)
            durations.append(
                float(data.get("format", {}).get("duration") or 0))
        # B2 fix: publish record carries the measured length so M10 verdicts
        # compare AVD against the real duration, not a 30s default.
        state["video_len_s"] = round(durations[0], 2) if durations else None
        atomic_json(directory / "qc_report.json", {
            "passed": True, "voice_duration_s": state["voice_duration"],
            "video_durations_s": durations, "finals": [str(f) for f in state["finals"]]})
        qc_mod.extract_frame(state["finals"][0])

    def publish():
        records = rec_mod.load_records(ctx.get("published_dir"))
        rec_mod.check_cadence(
            records, "youtube",
            max_per_day=cfg["publish"]["max_posts_per_day"])
        approval.require(
            "publish", f"upload {video_id} to YouTube", approvals_dir)
        meta = paid_call(
            ledger, "llm", est.get("llm", 0.05),
            lambda: meta_mod.build_metadata(idea, state["format"], ctx["llm"]),
            lambda m: (est.get("llm", 0.05),
                       {"units": len(json.dumps(m)), "unit_type": "chars",
                        "video_id": video_id}),
            approvals_dir)
        result = ctx["uploader"](state["finals"][0], meta)
        rec = {
            "video_id": video_id,
            "platform_video_ids": result,
            "title": meta["title"],
            "caption": meta["caption"],
            "hashtags": meta.get("hashtags", []),
            "published_at": datetime.now(timezone.utc).isoformat(),
            "format_id": state["format"]["format_id"],
            "idea_id": idea_id,
            "niche": idea["niche"],
            "variant_index": 1,
            "video_len_s": state.get("video_len_s"),
        }
        rec_mod.write_record(rec, directory=ctx.get("published_dir"))
        state["publish_record"] = rec

    stop_after = ctx.get("stop_after", "qc")
    if stop_after not in {"assets", "qc", "publish"}:
        raise ValueError("stop_after must be assets, qc or publish")
    sequence = list(zip(STAGE_ORDER_PRODUCE,
                        [hook, script, assets, voice, assemble, qc, publish]))
    return sequence[:STAGE_ORDER_PRODUCE.index(stop_after) + 1]


def _pull_window(client, rec):
    """One analytics pull -> readback window dict (same shape as M10 CLI)."""
    yt_id = rec["platform_video_ids"].get("youtube")
    start, end = "2005-01-01", datetime.now(timezone.utc).date().isoformat()
    stats = client.analytics_rows(yt_id, start, end)
    return {
        "pulled_at": datetime.now(timezone.utc).isoformat().replace(
            "+00:00", "Z"),
        "views": int(stats.get("views", 0)),
        "avg_view_duration_s": float(stats.get("averageViewDuration", 0)),
        "ctr": float(stats.get("ctr", 0)) / 100,
        "impressions": int(stats.get("impressions", 0)),
        "retention_points": client.retention(yt_id, start, end),
        "subs_gained": int(stats.get("subscribersGained", 0)),
    }


def readback_stages(ctx):
    """Ordered stages for `run.sh readback` — process due analytics windows."""
    from modules.analytics import readback as rb_mod
    from modules.analytics import windows
    from modules.publish import record as rec_mod

    cfg = ctx["config"]
    hours = cfg["readback"]["windows_hours"]
    state = {"due": []}

    def due():
        for rec in rec_mod.load_records(ctx.get("published_dir")):
            doc = rb_mod.load_or_new(
                rec["video_id"], ctx.get("analytics_dir"))
            todo = windows.due_windows(rec, doc["windows"], hours)
            state["due"] += [(rec, doc, w) for w in todo]

    def pull():
        state["pulled"] = []
        for rec, doc, name in state["due"]:
            w = _pull_window(ctx["analytics_client"], rec)
            state["pulled"].append((rec, doc, name, w))

    def record():
        # B3 fix: compute our channel's recent-uploads median once per run so
        # verdicts and format promotions compare against reality, not a zero
        # default. A baseline failure is loud (record stage fails), never silent.
        baseline = 0.0
        client = ctx.get("analytics_client")
        if client is not None and hasattr(client, "channel_median_views"):
            baseline = client.channel_median_views(ctx.get("channel_handle", ""))
        for rec, doc, name, w in state["pulled"]:
            if not doc.get("baseline_median_views"):
                doc["baseline_median_views"] = baseline
            rb_mod.record_window(
                doc, name, w, rec.get("video_len_s", 30), cfg["readback"])
            rb_mod.write_readback(doc, ctx.get("analytics_dir"))

    return list(zip(STAGE_ORDER_READBACK, [due, pull, record]))


def weekly_stages(ctx):
    """Ordered stages for the weekly cron run: M1 -> M2 -> M3 -> shortlist."""
    state = {}

    def radar():
        state["report"] = ctx["radar_scan"]()

    def grill():
        e = ctx.get("est", {}).get("llm", 0.05)
        state["doc"], state["audit"] = paid_call(
            ctx["ledger"], "llm", e,
            lambda: ctx["grill_run"](state["report"]),
            lambda r: (e, {"note": "weekly grill"}),
            ctx.get("approvals_dir"))

    def formats():
        from modules.formats import library as format_lib
        from modules.formats import match as match_mod
        lib = format_lib.load(ctx["formats_path"])
        matches = match_mod.match_ideas(
            state["doc"]["ideas"], lib["formats"])
        out = Path(ctx.get("weekly_dir") or DATA_DIR / "weekly")
        out.mkdir(parents=True, exist_ok=True)
        day = datetime.now(timezone.utc).date().isoformat()
        state["shortlist"] = out / f"{day}.md"
        lines = [f"# Weekly shortlist {day}", ""]
        passing = [i for i in state["doc"]["ideas"] if i["status"] == "pass"]
        for i in sorted(passing,
                        key=lambda x: -(x["hook_score"] + x["virality_score"])):
            m = matches[i["idea_id"]]
            lines.append(
                f"- **{i['topic']}** (`{i['idea_id']}`, {i['niche']}) "
                f"score {i['hook_score'] + i['virality_score']:.1f} "
                f"-> format `{m['format_id']}`")
        killed = [i for i in state["doc"]["ideas"] if i["status"] != "pass"]
        lines += ["", f"{len(killed)}/{len(state['doc']['ideas'])} ideas killed "
                      f"by the grill."]
        state["shortlist"].write_text("\n".join(lines) + "\n")

    return list(zip(STAGE_ORDER_WEEKLY, [radar, grill, formats]))
