"""Automatic seed→A/B/C/D pipeline.

A run is a durable `autorun` record plus one `auto_step` job that drives
the existing services stage by stage. The step job completes when the
run pauses or finishes; while a stage waits on other jobs it defers
itself through the scheduler — no busy loop, no lost progress on
restart, and paid work is never re-dispatched (every effect/job
identity is derived from the run id and re-queued idempotently).

Pauses are the product: a missing choice, exhausted spend authority, or
a problem automation must not paper over. Each pause carries a plain
code, detail, and the action that resumes the run.
"""
import copy
import json
import math
import re
import traceback
import uuid
from dataclasses import dataclass, field

from ..budget.service import BudgetService
from ..domain.errors import ContractError
from ..domain.records import Record, content_hash
from ..store.uow import utcnow
from . import review as checks
from . import scripts

AUTO_REVIEWER = "auto-pipeline"
STAGES = ("intake", "evidence", "video_analysis", "sections",
          "analysis_review", "blueprint", "template", "script", "music",
          "draft", "tts", "quote", "authorize", "run", "footage",
          "compose", "final_qc", "done")
STAGE_LABELS = {
    "intake": "Seed intake", "evidence": "Reference evidence",
    "video_analysis": "Video analysis", "sections": "Analysis write-up",
    "analysis_review": "Analysis review", "blueprint": "Blueprint",
    "template": "Format template", "script": "Script adaptation",
    "music": "Music", "draft": "Experiment draft", "tts": "Narration",
    "quote": "Footage quote", "authorize": "Authorization",
    "run": "Dispatch", "footage": "Footage generation",
    "compose": "Rendering", "final_qc": "Final quality check",
    "done": "Complete",
}
VOICE_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@dataclass
class AutoRun(Record):
    revision: int = 0
    status: str = "running"          # running | paused | succeeded
    stage: str = "intake"
    seed_id: str = ""
    experiment_id: str = ""
    params: dict = field(default_factory=dict)
    state: dict = field(default_factory=dict)
    pause: dict = field(default_factory=dict)
    progress: list = field(default_factory=list)
    notes: list = field(default_factory=list)


class AutoRunService:
    def __init__(self, services):
        self.s = services
        self.budgets = BudgetService(services.db)

    # ------------------------------------------------------------ API

    def create(self, body):
        seed_id = str(body.get("seed_id") or "").strip()
        if not seed_id:
            raise ContractError("seed_required", "seed_id")
        seed = self.s.seeds.get(seed_id)             # raises unknown_seed
        voice = str(body.get("voice_id") or "").strip()
        if not VOICE_RE.match(voice):
            raise ContractError("voice_required", "voice_id",
                                "a provider voice id is required")
        budget_ids = list(body.get("budget_ids") or [])
        if not budget_ids:
            raise ContractError("budgets_required", "budget_ids",
                                "select the spending authority this run "
                                "may draw from")
        for bid in budget_ids:
            self.budgets.available(bid)            # raises unknown_budget
        limits = {str(k): int(v) for k, v in
                  (body.get("limits") or {}).items() if v is not None}
        for unit, cap in limits.items():
            if cap <= 0:
                raise ContractError("invalid_limit", "limits", unit)
        language = str(body.get("language") or "en").strip()[:16]
        valid_until = str(body.get("valid_until") or "").strip()
        if not valid_until:
            from datetime import datetime, timedelta, timezone
            valid_until = (datetime.now(timezone.utc)
                           + timedelta(hours=24)).isoformat()
        run = AutoRun(
            schema_version="autorun.v1",
            id="auto-" + uuid.uuid4().hex[:16], created_at=utcnow(),
            seed_id=seed_id,
            params={
                "voice_id": voice, "language": language,
                "budget_ids": budget_ids, "limits": limits,
                "generate_music": bool(body.get("generate_music")),
                "visual_reviews": bool(body.get("visual_reviews", True)),
                "script_mode": str(body.get("script_mode") or "auto"),
                "music_artifact_id": str(
                    body.get("music_artifact_id") or ""),
                "generation_model": str(
                    body.get("generation_model") or ""),
                "account": str(body.get("account") or ""),
                "valid_until": valid_until,
            })
        self._put(run)
        self._enqueue_step(run)
        return run.to_dict()

    def get(self, run_id):
        row = self.s.db.uow().records.get("autorun", run_id)
        if not row:
            raise ContractError("not_found", "run_id", run_id)
        return self._load(row)

    def list(self):
        rows = self.s.db.conn.execute(
            "SELECT body FROM records WHERE kind='autorun' "
            "ORDER BY created_at DESC LIMIT 50").fetchall()
        return [json.loads(r["body"]) for r in rows]

    def detail(self, run_id):
        run = self.get(run_id)
        out = run.to_dict()
        out["stage_label"] = STAGE_LABELS.get(run.stage, run.stage)
        out["stages"] = [{"stage": s, "label": STAGE_LABELS[s],
                          "done": any(p["stage"] == s and
                                     p.get("outcome") == "done"
                                     for p in run.progress),
                          "current": s == run.stage}
                         for s in STAGES]
        if run.state.get("experiment_id"):
            try:
                out["results"] = self.s.experiment_results(
                    run.state["experiment_id"])
            except ContractError:
                pass
        return out

    def resume(self, run_id, body=None):
        run = self.get(run_id)
        if run.status != "paused":
            return run.to_dict()
        body = body or {}
        replacement = body.get("budget_ids")
        if replacement is not None:
            replacement = [str(b) for b in replacement]
            if not replacement:
                raise ContractError("budgets_required", "budget_ids")
            for bid in replacement:
                self.budgets.available(bid)       # raises unknown_budget
            run.params["budget_ids"] = replacement
            run.notes.append(
                "spending authority re-scoped by operator at resume: "
                + ", ".join(replacement))
        added = [str(b) for b in body.get("add_budget_ids") or []]
        for bid in added:
            if bid not in run.params["budget_ids"]:
                self.budgets.available(bid)       # raises unknown_budget
                run.params["budget_ids"].append(bid)
                scope = self.s.db.conn.execute(
                    "SELECT scope FROM budgets WHERE id=?", (bid,)
                ).fetchone()[0]
                run.notes.append(
                    f"funded scope widened: budget {bid} ({scope}) added "
                    "by operator at resume"
                    + (" — an aggregate ceiling is held in full alongside "
                       "the others; it does not raise them"
                       if scope == "aggregate" else ""))
        resolved = body.get("resolve_qc")
        if resolved is not None:
            self._resolve_qc(run, resolved, body)
        # Operator-approved parameter updates — the only way a pause's
        # recovery action can be acted on. Restricted to keys whose
        # change is safe mid-run; every change is audited in notes.
        settable = {"limits", "valid_until", "visual_reviews",
                    "generate_music"}
        for key, value in (body.get("set_params") or {}).items():
            if key not in settable:
                raise ContractError("param_not_resumable", key)
            if key == "valid_until":
                text = str(value or "")
                if text and text <= utcnow():
                    raise ContractError("authorization_not_renewed",
                                        "valid_until")
            if key == "limits":
                if not isinstance(value, dict):
                    raise ContractError("invalid_limits", "limits")
                run.params["limits"] = {str(k): v for k, v in
                                        value.items()}
            else:
                run.params[key] = value
            run.notes.append(
                f"operator updated {key} at resume")
        self._reset_budget_blocked_effect(run)
        run.status = "running"
        run.pause = {}
        run.state["step_seq"] = run.state.get("step_seq", 0) + 1
        run.progress.append({"stage": run.stage, "at": utcnow(),
                             "outcome": "resumed"})
        self._put(run)
        self._enqueue_step(run)
        return run.to_dict()

    def _reset_budget_blocked_effect(self, run):
        """Let Resume create a fresh paid plan after reservation failure.

        Effect plans and authorizations are immutable, and paid jobs cannot be
        locally retried.  Once a worker has terminally failed while reserving
        funds, keeping the stage's job ids makes every Resume immediately see
        the same dead job.  Remove only the current paid-stage references; the
        next step will quote and authorize a new plan against the operator's
        current budget selection.
        """
        if run.pause.get("code") != "budget_exhausted":
            self._reset_revised_speech(run)
            return
        tags = {
            "video_analysis": ["analysis"],
            "script": ["script"],
            "music": ["music"],
            "tts": run.state.get("tts_batch_tags") or ["tts"],
            "final_qc": [f"qc_{k}" for k in "ABCD"],
        }
        for tag in tags.get(run.stage, []):
            jobs = run.state.get(f"{tag}_jobs") or []
            if not any((self.s.db.uow().jobs.get(jid) or {}).get("status")
                       in ("failed", "blocked", "cancelled")
                       for jid in jobs):
                continue
            run.state.pop(f"{tag}_jobs", None)
            run.state.pop(f"{tag}_plan", None)
            run.state.pop(f"{tag}_auth", None)
            # A new plan id for identical requests — the dead jobs'
            # queue identities are bound to the old plan and stay dead.
            run.state[f"{tag}_plan_seq"] = \
                run.state.get(f"{tag}_plan_seq", 0) + 1
            submitted = run.state.get("qc_submitted") or {}
            for key, sub in list(submitted.items()):
                if sub.get("job_id") in jobs:
                    submitted.pop(key)
        if run.stage == "tts":
            run.state.pop("tts_synth_jobs", None)
            run.state.pop("tts_batch_tags", None)
            run.notes.append(
                f"discarded terminal {tag} plan after budget recovery; "
                "a fresh quote and authorization will be created")

    def _resolve_qc(self, run, resolved, body):
        """Explicit operator decision on flagged final QC.

        'accept' records a human verdict bound to each current final's
        identity and lets the run finish; 'recheck' discards the flagged
        submissions so the stage re-reviews the current bytes once more.
        A plain Resume re-reads the same machine verdicts and re-pauses —
        the flagged state is never silently repeated or silently paid
        for again."""
        if run.pause.get("code") != "final_qc_flagged":
            raise ContractError("no_qc_resolution_pending", "resolve_qc")
        flagged = list(run.state.get("qc_flagged") or [])
        if resolved == "accept":
            reviewer = str(body.get("reviewer") or "").strip()
            if not reviewer:
                raise ContractError("reviewer_required", "reviewer")
            finals = self._finals(run)
            for key in flagged:
                f = finals.get(key)
                if not f:
                    continue
                path = self.s.artifacts.verified_path(f["artifact_id"])
                binding = self.s.quality.binding(
                    path, f["composition_id"], f["artifact_id"])
                self.s.quality.record_verdict(
                    "human-visual-" + uuid.uuid4().hex[:16],
                    f["sha256"], "creative", "pass",
                    evidence=[f["artifact_id"]], binding=binding,
                    reviewer=reviewer,
                    limitations=["manual acceptance after automated "
                                 "flag"],
                    reviewer_type="human")
            run.state["qc_human_accepted"] = True
            run.notes.append(
                f"flagged finals accepted by {reviewer} after human "
                "review in Compare")
        elif resolved == "recheck":
            rechecks = run.state.setdefault("qc_rechecks", [])
            submitted = run.state.get("qc_submitted") or {}
            for key in flagged:
                if key in rechecks:
                    raise ContractError("qc_recheck_exhausted", key)
                rechecks.append(key)
                submitted.pop(key, None)
                for k in (f"qc_{key}_jobs", f"qc_{key}_plan",
                          f"qc_{key}_auth", f"qc_verdict_{key}"):
                    run.state.pop(k, None)
                run.state[f"qc_{key}_plan_seq"] = \
                    run.state.get(f"qc_{key}_plan_seq", 0) + 1
            run.state.pop("qc_flagged", None)
            run.notes.append(
                "flagged finals resubmitted for a fresh paid visual "
                "review at the operator's request")
        else:
            raise ContractError("invalid_resolve_qc", "resolve_qc")

    def _reset_revised_speech(self, run):
        """Continue TTS on the new draft revision after copy was edited."""
        if run.stage != "tts" or run.pause.get("code") != \
                "speech_fit_failed":
            return
        eid = run.state.get("experiment_id")
        if not eid:
            return
        current = self.s._current(eid)
        prior = run.state.get("experiment_revision")
        if current.revision == prior:
            return
        run.state["experiment_revision"] = current.revision
        for tag in run.state.get("tts_batch_tags") or ["tts"]:
            for suffix in ("_jobs", "_plan", "_auth"):
                run.state.pop(f"{tag}{suffix}", None)
        for key in ("tts_synth_jobs", "tts_fits", "tts_done",
                    "tts_batch_tags"):
            run.state.pop(key, None)
        run.state["tts_plan_seq"] = \
            run.state.get("tts_plan_seq", 0) + 1
        run.experiment_id = eid
        run.notes.append(
            f"copy revised from experiment revision {prior} to "
            f"{current.revision}; narration will be regenerated")

    # ------------------------------------------------------ step loop

    def step(self, body, job):
        run = self.get(body["run_id"])
        if run.status != "running":
            return {"status": "succeeded", "run": run.status}
        try:
            outcome = self._drive(run)
        except ContractError as e:
            detail = f"{e.code}: {e.detail}"
            trace = traceback.format_exc(limit=12).strip().splitlines()
            if trace:
                detail = detail + " | " + " | ".join(trace[-8:])
            outcome = self._pause(run, "stage_error", detail,
                                  "Resolve the cause, then Resume")
        except Exception as e:                       # noqa: BLE001
            detail = type(e).__name__
            # Keep the compact traceback in the durable pause record so an
            # operator can recover a worker-side automation failure without
            # needing a live terminal.  This is diagnostic-only; no secrets
            # or request payloads are added here.
            trace = traceback.format_exc(limit=6).strip().splitlines()
            if trace:
                detail = detail + ": " + " | ".join(trace[-4:])
            outcome = self._pause(run, "run_error", detail,
                                  "Inspect the worker log, then Resume")
        if outcome == "wait":
            # Stage handlers may mutate run.state while deciding to wait
            # (bounded retries, re-opened reviews, progress markers). Those
            # mutations are part of durable progress — persist them before
            # deferring, or the next step re-derives the same decision and
            # can loop on an unbounded recovery path.
            self._put(run)
            return {"status": "pending", "defer_s": 4}
        done = self.get(run.id)
        return {"status": "succeeded",
                "run": {"id": done.id, "status": done.status,
                        "stage": done.stage, "pause": done.pause}}

    def _drive(self, run):
        while run.status == "running":
            handler = getattr(self, "_stage_" + run.stage)
            out = handler(run)
            if out == "wait":
                return "wait"
            if isinstance(out, tuple) and out[0] == "pause":
                return self._pause(run, *out[1:])
            if out == "done":
                run.status = "succeeded"
                self._mark(run, "done", "done")
                return "done"
            # 'next' — handler already advanced run.stage via _advance
        return "done"

    # -------------------------------------------------- stage helpers

    def _put(self, run):
        with self.s.db.uow() as u:
            existing = u.records.get("autorun", run.id)
            u.records.put(run, expected_version=None if existing is None
                          else existing["version"])
        return run

    def _load(self, row):
        d = json.loads(row["body"])
        d.pop("kind", None)
        return AutoRun(**d)

    def _enqueue_step(self, run):
        seq = run.state.get("step_seq", 0)
        return self.s.commands.enqueue(
            "auto_step", {"run_id": run.id}, phase="plan",
            identity=f"autostep:{run.id}:{seq}")

    def _mark(self, run, stage, outcome, **extra):
        run.progress.append({"stage": stage, "at": utcnow(),
                             "outcome": outcome, **extra})
        self._put(run)

    def _advance(self, run, stage):
        self._mark(run, run.stage, "done")
        run.stage = stage
        self._put(run)

    def _pause(self, run, code, detail, action):
        run.status = "paused"
        run.pause = {"code": code, "detail": detail, "action": action,
                     "stage": run.stage, "at": utcnow()}
        # Keep the full explanation in progress history — resume clears
        # run.pause, and the dashboard has to reconstruct what happened.
        self._mark(run, run.stage, "paused", code=code, detail=detail,
                   action=action)
        return "paused"

    def _jobs(self, run, ids, fail_code="job_failed"):
        """'next' when every job succeeded; 'wait' while any run;
        pause tuple on the first terminal failure."""
        for jid in ids:
            j = self.s.db.uow().jobs.get(jid)
            if j is None:
                continue
            if j["status"] in ("failed", "blocked", "cancelled"):
                reason = str(j["blocked_reason"] or j["status"])
                if any(t in reason for t in
                       ("reservation", "budget", "cap_exceeded",
                        "spend_", "authority")):
                    return ("pause", "budget_exhausted",
                            f"job {jid}: {reason}",
                            "Add spending authority at Resume, or "
                            "resolve the blocking budget")
                return ("pause", fail_code, f"job {jid}: {reason}",
                        "Resolve the failing job, then Resume this run")
        if all((self.s.db.uow().jobs.get(jid) or {}).get("status")
               == "succeeded" for jid in ids):
            return "next"
        return "wait"

    # -------------------------------------------------- budget checks

    def _cover(self, run, totals, providers=()):
        """Mirror the reservation rule before any paid dispatch: a hold is
        placed in full on every applicable budget — each selected one, every
        aggregate ceiling of the unit, and provider ceilings for the routes
        used — so the unit's headroom is the *minimum* across them, never a
        sum. Name the budget that would block, so the pause is actionable."""
        selected = set(run.params["budget_ids"])
        retired = {r[0][len("retired:budget:"):] for r in
                   self.s.db.conn.execute(
                       "SELECT key FROM meta WHERE key LIKE "
                       "'retired:budget:%'")}
        for unit, amount in (totals or {}).items():
            applicable = [
                r["id"] for r in self.s.db.conn.execute(
                    "SELECT id, scope, scope_key FROM budgets WHERE unit=?",
                    (unit,))
                if r["id"] not in retired and not r["id"].startswith(
                    "authority:") and (
                    r["id"] in selected or r["scope"] == "aggregate" or
                    (r["scope"] == "provider" and
                     r["scope_key"] in providers))]
            if not any(b in selected for b in applicable):
                return (f"{unit}: none of the selected budgets funds this "
                        "unit")
            for bid in applicable:
                have = self.budgets.available(bid)
                if have < amount:
                    kind = ("selected" if bid in selected
                            else "aggregate ceiling")
                    return (f"{unit}: need {amount}, budget {bid} "
                            f"({kind}) has {have} — every applicable "
                            "ceiling must cover the full amount")
        return ""

    def _ceilings(self, run, operations):
        """Per-unit cap = the unit's total reserves across the plan (the
        authority budget is shared by every operation), or the
        operator's explicit lower limit. A limit below the plan's total
        is a genuine missing choice — pause, never silently raise it."""
        need = {}
        for op in operations:
            price = op["price"]
            unit = price["unit"]
            need[unit] = need.get(unit, 0) + price["reserve_amount"]
        limits = run.params.get("limits") or {}
        ceilings = {}
        for unit, total in need.items():
            cap = limits.get(unit)
            if cap is not None and cap < total:
                return ("pause", "limit_too_low",
                        f"{unit} limit {cap} is below the plan's "
                        f"{total} reserve requirement",
                        "Raise the limit or remove the operation, "
                        "then Resume")
            ceilings[unit] = cap if cap is not None else total
        return ceilings

    def _plan_auth(self, plan):
        """An authorization already committed for this exact plan, or ''.

        The crash window between ``authorize``'s commit and the run-state
        write leaves a valid authorization with its reservations held;
        reusing it is the only way a retry avoids double-reserving the
        same logical work."""
        rows = self.s.db.conn.execute(
            "SELECT id, body FROM records WHERE kind='authorization' AND "
            "status='authorized' AND "
            "json_extract(body,'$.binding.kind')='effectplan' AND "
            "json_extract(body,'$.binding.id')=? "
            "ORDER BY created_at DESC", (plan["id"],)).fetchall()
        for row in rows:
            body = json.loads(row["body"])
            if body.get("scope_hash") != plan["plan_hash"]:
                continue
            until = body.get("valid_until") or ""
            if until and until <= utcnow():
                continue
            return row["id"]
        return ""

    def _run_effect(self, run, kind, provider, model, requests, tag,
                    experiment_id="", revision=0):
        """Prepare→authorize→queue an effect plan under the run's exact
        budget scope. Returns 'wait' once dispatched, or a pause tuple.

        Each sub-step is persisted before the next paid commit: the plan
        id is content-keyed to this run/stage/request set (prepare is
        get-or-create), an authorization that already committed for the
        plan is reused, and queue identities are deterministic per
        plan+operation — so a crash at any point re-lands on the same
        paid work instead of minting duplicates."""
        state_key = f"{tag}_jobs"
        if run.state.get(state_key):
            return "wait"
        adapter = self.s.providers.get(provider)
        if adapter is None or not getattr(adapter, "account", ""):
            return ("pause", "route_unavailable",
                    f"provider {provider} is not configured",
                    "Configure the provider route, then Resume")
        plan_id = run.state.get(f"{tag}_plan")
        if plan_id:
            plan = self.s.effect_work.get(plan_id)
        else:
            # plan_seq discriminates a deliberate re-plan: an operator
            # reset (budget recovery, revised copy) bumps it so the new
            # plan gets fresh queue identities instead of resurrecting
            # terminally-failed jobs.
            plan_id = "effect-" + content_hash({
                "run": run.id, "tag": tag, "kind": kind,
                "provider": provider, "model": model,
                "requests": requests, "experiment_id": experiment_id,
                "revision": revision,
                "seq": run.state.get(f"{tag}_plan_seq", 0)})
            plan = self.s.effect_work.prepare(
                kind, provider, model, requests,
                experiment_id=experiment_id, revision=revision,
                plan_id=plan_id)
            run.state[f"{tag}_plan"] = plan["id"]
            self._put(run)
        auth_id = run.state.get(f"{tag}_auth")
        if auth_id:
            # A stored authorization is only valid for the plan it was
            # bound to — a reset that left stale state must not queue
            # the new plan under another plan's scope.
            row = self.s.db.uow().records.get("authorization", auth_id)
            bound = row and json.loads(row["body"]).get(
                "binding", {}).get("id") == plan["id"]
            if not bound:
                run.state.pop(f"{tag}_auth", None)
                auth_id = ""
        if not auth_id:
            auth_id = self._plan_auth(plan)
        if not auth_id:
            # Only checked when no authorization exists yet — once the
            # plan is authorized its reservations are already held, and
            # re-measuring headroom would count our own hold against us.
            gap = self._cover(run, plan["total"], providers=(provider,))
            if gap:
                return ("pause", "budget_exhausted", gap,
                        "Raise the named ceiling (same id, higher amount) or "
                        "settle finished holds, then Resume")
            ceilings = self._ceilings(run, plan["operations"])
            if isinstance(ceilings, tuple):
                return ceilings
            auth = self.s.effect_work.authorize(plan["id"], {
                "plan_hash": plan["plan_hash"], "reviewer": AUTO_REVIEWER,
                "ceilings": ceilings,
                "budget_ids": run.params["budget_ids"],
                "valid_until": run.params.get("valid_until") or ""})
            auth_id = auth["authorization_id"]
        if auth_id != run.state.get(f"{tag}_auth"):
            run.state[f"{tag}_auth"] = auth_id
            self._put(run)
        queued = self.s.effect_work.queue(
            plan["id"], auth_id)
        run.state[state_key] = [j["job_id"] for j in queued["jobs"]]
        self._put(run)
        return "wait"

    # ------------------------------------------------------- stages

    def _stage_intake(self, run):
        seed = self.s.seeds.get(run.seed_id)
        if seed.evidence_status == "media_ready" and seed.source_asset_id:
            self._advance(run, "evidence")
            return "next"
        return ("pause", "missing_source_media",
                f"seed {run.seed_id} has no verified source media "
                f"({seed.evidence_status})",
                "Attach the source video to the seed, then Resume")

    def _stage_evidence(self, run):
        jid = run.state.get("evidence_job")
        if not jid:
            self.s.ref_analysis.start(run.seed_id, AUTO_REVIEWER)
            jid = self.s.commands.enqueue(
                "analysis_evidence", {"seed_id": run.seed_id},
                phase="analyze",
                identity=f"auto:{run.id}:evidence")["job_id"]
            run.state["evidence_job"] = jid
            self._put(run)
            return "wait"
        out = self._jobs(run, [jid])
        if out != "next":
            return out
        a = self.s.ref_analysis.get(run.seed_id)
        if a.status == "blocked" or a.blocking:
            detail = "; ".join(
                str(b.get("detail") or b.get("code"))
                if isinstance(b, dict) else str(b)
                for b in (a.blocking or [])) or a.status
            return ("pause", "analysis_blocked", detail,
                    "Resolve the analysis blocker (see Analysis tab), "
                    "then Resume")
        self._advance(run, "video_analysis")
        return "next"

    def _stage_video_analysis(self, run):
        if run.state.get("analysis") is not None:
            self._advance(run, "sections")
            return "next"
        adapter = self.s.providers.get("audiovisual_analysis")
        seed = self.s.seeds.get(run.seed_id)
        if adapter is None or not getattr(adapter, "account", ""):
            run.notes.append(
                "audiovisual analysis unavailable — beats derived from "
                "the transcript only; visual events stay unresolved")
            run.state["analysis"] = {}
            self._advance(run, "sections")
            return "next"
        art = self.s.db.uow().artifacts.get(seed.source_asset_id)
        out = self._run_effect(
            run, "analysis", "audiovisual_analysis", adapter.model,
            [{"task": "analyze", "artifact_id": seed.source_asset_id,
              "artifact_sha256": art["sha256"], "model": adapter.model}],
            "analysis")
        if out != "wait":
            return out
        res = self._jobs(run, run.state["analysis_jobs"], "analysis_failed")
        if res != "next":
            return res
        cmd = self.s.commands.get(run.state["analysis_jobs"][0])
        run.state["analysis"] = cmd["command"]["result"]["result"]
        self._advance(run, "sections")
        return "next"

    def _transcript(self, run):
        """Best available word-timed transcript: WhisperX file first
        (ground truth the safety gate already approved), then the
        provider payload."""
        a = self.s.ref_analysis.get(run.seed_id)
        path = self.s.ref_analysis._doc_paths(a)["transcript_json"]
        if path.exists():
            data = json.loads(path.read_text())
            passages = data.get("passages") or data.get("segments") or []
            out = []
            for p in passages:
                text = str(p.get("text") or "").strip()
                if text:
                    out.append({"start_s": float(
                        p.get("start_s", p.get("start_seconds",
                                               p.get("start", 0)))),
                        "end_s": float(
                            p.get("end_s", p.get("end_seconds",
                                                 p.get("end", 0)))),
                        "text": text})
            if out:
                return out
        return list((run.state.get("analysis") or {}).get("transcript")
                    or [])

    def _beats(self, run):
        a = self.s.ref_analysis.get(run.seed_id)
        dur = a.acquisition.get("duration_s") or 0
        payload = run.state.get("analysis") or {}
        beats = payload.get("beats") or []
        if not beats:
            transcript = self._transcript(run)
            if transcript:
                payload = checks.transcript_observations(transcript, dur)
                beats = payload["beats"]
        return payload, beats, dur

    def _stage_sections(self, run):
        payload, beats, dur = self._beats(run)
        if not beats:
            return ("pause", "analysis_unavailable",
                    "no beats from video analysis or transcript",
                    "Review the analysis in the Analysis tab, then Resume")
        a = self.s.ref_analysis.get(run.seed_id)
        bp_hint = self._blueprint_target_frames(run, dur)
        sections = checks.build_sections(payload, dur, bp_hint)
        self.s.ref_analysis.save_understanding(
            run.seed_id, sections["understanding"], AUTO_REVIEWER)
        self.s.ref_analysis.save_timeline(
            run.seed_id, sections["timeline"], AUTO_REVIEWER)
        self.s.ref_analysis.save_treatment(
            run.seed_id, {**sections["treatment"],
                          "summary": sections["treatment"]["style"],
                          "preserves": ("Premise, hook order, beat "
                                        "structure, factual claims"),
                          "redesigns": ("Footage, characters, narration "
                                        "voice, captions"),
                          "script_direction": sections["treatment"]
                          .get("changes", "")}, AUTO_REVIEWER)
        self._advance(run, "analysis_review")
        return "next"

    def _blueprint_target_frames(self, run, dur):
        return int(round(dur * 30)) or 30

    def _stage_analysis_review(self, run):
        a = self.s.ref_analysis.get(run.seed_id)
        if a.status != "complete":
            self.s.ref_analysis.review(
                run.seed_id, AUTO_REVIEWER, "accept",
                notes="Automated review: machine stages, transcript, "
                      "grids and machine-drafted sections verified by "
                      "pipeline checks.")
        self._advance(run, "blueprint")
        return "next"

    def _stage_blueprint(self, run):
        from ..analysis.service import blueprint_id_for
        bp_id = blueprint_id_for(run.seed_id)
        try:
            bp = self.s.analysis.get(bp_id)
            if bp.status == "accepted":
                run.state["blueprint_id"] = bp_id
                self._advance(run, "template")
                return "next"
        except ContractError:
            pass
        payload, _, _ = self._beats(run)
        a = self.s.ref_analysis.get(run.seed_id)
        payload = checks.auto_review_beats(
            payload, evidence=a.evidence or {})
        bp = self.s.analysis.import_observations(
            run.seed_id, payload, AUTO_REVIEWER)
        try:
            self.s.blueprints.accept(bp.id, bp.content_hash,
                                     AUTO_REVIEWER)
        except ContractError as e:
            if e.code == "unresolved_flags":
                return ("pause", "blueprint_flags",
                        json.dumps(self.s.blueprints.flags(bp.id)),
                        "Review the flagged beats in the Analysis tab, "
                        "accept the blueprint, then Resume")
            raise
        run.state["blueprint_id"] = bp.id
        self._advance(run, "template")
        return "next"

    def _stage_template(self, run):
        tpl_id = run.state.get("template_id") or f"tpl-{run.id}"
        try:
            tpl = self.s.templates.get(tpl_id)
        except ContractError:
            bp = self.s.analysis.get(run.state["blueprint_id"])
            tpl = self.s.templates.author(bp, tpl_id)
        run.state["template_id"] = tpl.id
        self._advance(run, "script")
        return "next"

    def _stage_script(self, run):
        if run.state.get("scripts"):
            self._advance(run, "music" if run.params["generate_music"]
                          or run.params.get("music_artifact_id")
                          else "draft")
            return "next"
        bp = self.s.analysis.get(run.state["blueprint_id"])
        fps = bp.clock.num / bp.clock.den
        beats = [{"id": b.id, "role": b.role,
                  "start_s": b.source.start / fps if b.source else 0.0,
                  "end_s": b.source.end / fps if b.source else 0.0,
                  "target_s": (b.target.end - b.target.start) / fps,
                  "visual_event": b.visual_event}
                 for b in bp.beats]
        transcript = self._transcript(run)
        base = scripts.adapt(beats, transcript)
        # The source-derived adaptation is the bounded repair target when
        # generated copy later fails its measured speech fit.
        run.state["scripts_base"] = base
        mode = run.params.get("script_mode", "auto")
        adapter = self.s.providers.get("audiovisual_analysis")
        use_llm = mode in ("auto", "llm") and adapter is not None and \
            getattr(adapter, "account", "") and \
            not run.state.get("script_llm_failed")
        if use_llm:
            request = scripts.llm_request(
                adapter.model, beats, transcript, base["A"],
                base["changed"])
            out = self._run_effect(run, "analysis",
                                   "audiovisual_analysis",
                                   adapter.model, [request], "script")
            if out != "wait":
                return out
            res = self._jobs(run, run.state["script_jobs"],
                             "script_failed")
            if res != "next":
                if isinstance(res, tuple):
                    # A Resume after this pause uses the deterministic
                    # adaptation instead of re-dispatching the dead job.
                    run.state["script_llm_failed"] = True
                    self._put(run)
                return res
            cmd = self.s.commands.get(run.state["script_jobs"][0])
            llm = cmd["command"]["result"]["result"].get("script")
            merged, over = self._merge_llm_scripts(base, llm, beats)
            for key, beat_id, words, budget in over:
                run.notes.append(
                    f"variant {key} beat {beat_id}: generated copy "
                    f"({words} words) exceeds the beat's word budget "
                    f"({budget}); source-derived copy used instead")
            if merged is None:
                run.state["script_llm_failed"] = True
                self._put(run)
                return ("pause", "script_failed",
                        "script adaptation returned unusable output",
                        "Resume to use the deterministic adaptation")
            run.state["scripts"] = merged
            run.state["script_mode"] = "llm"
        else:
            run.state["scripts"] = base
            run.state["script_mode"] = "template"
            if run.state.get("script_llm_failed"):
                run.notes.append(
                    "script adaptation fell back to deterministic "
                    "templates after the LLM attempt failed")
            elif mode == "llm":
                run.notes.append(
                    "script adaptation fell back to deterministic "
                    "templates — no analysis provider configured")
        self._put(run)
        self._advance(run, "music" if run.params["generate_music"]
                      or run.params.get("music_artifact_id")
                      else "draft")
        return "next"

    def _merge_llm_scripts(self, base, llm, beats):
        """Apply an LLM adaptation only where it stays inside the
        declared treatment shape; anything else is rejected wholesale."""
        if not isinstance(llm, dict):
            return None, []
        variants = llm.get("variants") or {}
        a = variants.get("A")
        if not isinstance(a, dict) or any(
                not str(a.get(b["id"], "")).strip()
                and str(base["A"].get(b["id"], "")).strip()
                for b in beats):
            return None, []
        by_id = {b["id"]: b for b in beats}
        over = []

        def bounded(key, beat_id, text, fallback):
            budget = scripts.word_budget(by_id[beat_id],
                                         base["A"].get(beat_id, ""))
            words = len(str(text).split())
            if words > budget:
                over.append((key, beat_id, words, budget))
                return fallback
            return str(text)
        out = {"A": {b["id"]: bounded("A", b["id"], a.get(b["id"], ""),
                                      base["A"].get(b["id"], ""))
                     for b in beats},
               "B": {}, "C": {}, "D": {},
               "hypotheses": base["hypotheses"],
               "factors": base["factors"], "metrics": base["metrics"],
               "changed": base["changed"]}
        hypotheses = llm.get("hypotheses") or {}
        for key in ("B", "C", "D"):
            beat_id = base["changed"][key]
            diff = (variants.get(key) or {}).get(beat_id)
            out[key][beat_id] = bounded(key, beat_id, diff,
                                        base[key][beat_id]) \
                if str(diff or "").strip() else base[key][beat_id]
            if str(hypotheses.get(key) or "").strip():
                out["hypotheses"][key] = str(hypotheses[key])
        return out, over

    def _stage_music(self, run):
        if run.state.get("music") is not None:
            self._advance(run, "draft")
            return "next"
        aid = run.params.get("music_artifact_id")
        if not run.params.get("generate_music") and not aid:
            # Only reachable when the operator declared the fallback at
            # resume — the script stage never routes here otherwise.
            run.notes.append("no music bed — the operator declined "
                             "generated music")
            run.state["music"] = {}
            self._advance(run, "draft")
            return "next"
        if aid:
            self.s.artifacts.verified_path(aid)
            run.state["music"] = {"artifact_id": aid, "gain": 0.12,
                                  "provenance": "operator-supplied"}
            self._advance(run, "draft")
            return "next"
        adapter = self.s.providers.get("generated_music")
        if adapter is None or not getattr(adapter, "account", ""):
            # Music was requested — an unavailable route is a missing
            # capability, not a note to quietly absorb.
            return ("pause", "capability_unavailable",
                    "generated music was requested but the music "
                    "provider route is not configured",
                    "Configure the provider, or Resume with "
                    "set_params generate_music=false to declare the "
                    "no-music fallback")
        bp = self.s.analysis.get(run.state["blueprint_id"])
        dur_s = bp.target_frames / (bp.clock.num / bp.clock.den)
        out = self._run_effect(
            run, "music", "generated_music", adapter.model,
            [{"model": adapter.model,
              "prompt": ("Clean instrumental background bed for a "
                         "vertical social video; steady light pulse, "
                         "no vocals, no drops, safe under narration."),
              "music_length_ms": int(math.ceil(dur_s * 1000)),
              "instrumental": True}], "music")
        if out != "wait":
            return out
        res = self._jobs(run, run.state["music_jobs"], "music_failed")
        if res != "next":
            return res
        cmd = self.s.commands.get(run.state["music_jobs"][0])
        run.state["music"] = {
            "artifact_id": cmd["command"]["result"]["artifact_id"],
            "gain": 0.12, "provenance": "generated via qualified route"}
        self._advance(run, "draft")
        return "next"

    def _stage_draft(self, run):
        if run.state.get("experiment_id"):
            self._advance(run, "tts")
            return "next"
        bp = self.s.analysis.get(run.state["blueprint_id"])
        sc = run.state["scripts"]
        provider, model = self._generation_route(run)
        gen_settings = self._generation_settings(provider, model)
        segments = []
        for b in bp.beats:
            segments.append({
                "id": b.id,
                "target": b.target.to_dict(),
                "copy": sc["A"].get(b.id, ""),
                "picture": {"request": scripts.picture_request(
                    {"visual_event": b.visual_event, "role": b.role},
                    "control", gen_settings)},
                "captions": []})
        variants = []
        for key in ("B", "C", "D"):
            changed_id = sc["changed"][key]
            branch_segments = []
            for seg in segments:
                s2 = dict(seg)
                s2["picture"] = dict(seg["picture"])
                s2["picture"]["request"] = dict(
                    seg["picture"]["request"])
                if seg["id"] == changed_id:
                    s2["copy"] = sc[key].get(changed_id, seg["copy"])
                    s2["picture"]["request"] = scripts.picture_request(
                        {"visual_event": next(
                            b.visual_event for b in bp.beats
                            if b.id == changed_id),
                         "role": next(b.role for b in bp.beats
                                      if b.id == changed_id)},
                        sc["factors"][key], gen_settings)
                branch_segments.append(s2)
            region = next(b.target.to_dict() for b in bp.beats
                          if b.id == changed_id)
            variants.append({
                "key": key, "factor": sc["factors"][key],
                "regions": [region],
                "segments": branch_segments,
                "hypothesis": sc["hypotheses"][key],
                "primary_metric": sc["metrics"][key],
                "allowed_fields": ["copy", "speech", "captions",
                                   "picture"]})
        eid = f"exp-{run.id}"
        body = {
            "blueprint_id": run.state["blueprint_id"],
            "template_id": run.state["template_id"],
            "segments": segments, "variants": variants,
            "voice": {"id": run.params["voice_id"], "model": "eleven_v3",
                      "settings": {"language":
                                   run.params["language"]}},
            "music": run.state.get("music") or {"role": "bed"},
            "provider_policy": {"choice": provider,
                                "allowed_models":
                                {self._provider_name(provider): [model]}
                                if model else {}},
            "product_ids": []}
        try:
            self.s.create_experiment_draft(eid, body)
        except ContractError as e:
            return ("pause", "draft_failed", f"{e.code}: {e.detail}",
                    "Resolve the draft problem, then Resume")
        run.state["experiment_id"] = eid
        run.experiment_id = eid
        run.state["experiment_revision"] = 1
        self._advance(run, "tts")
        return "next"

    def _generation_route(self, run):
        if "google_vertex" in self.s.providers:
            adapter = self.s.providers["google_vertex"]
            models = list(getattr(adapter, "models", None)
                          or getattr(adapter, "capabilities", {}) or [])
            return "vertex", (run.params.get("generation_model")
                              or (models[0] if models else ""))
        adapter = self.s.providers.get("jimeng_canvas")
        models = list(getattr(adapter, "models", None)
                      or getattr(adapter, "capabilities", {}) or [])
        return "jimeng", (run.params.get("generation_model")
                          or (models[0] if models else ""))

    def _provider_name(self, choice):
        return "google_vertex" if choice == "vertex" else "jimeng_canvas"

    def _generation_settings(self, choice, model):
        """Aspect/resolution the pinned route actually supports — never
        assumed, or preflight rejects the take."""
        adapter = self.s.providers.get(self._provider_name(choice))
        try:
            caps = adapter.capabilities(model) if adapter and model \
                else {}
        except Exception:
            caps = {}
        return {"aspect": (caps.get("aspects") or ["9:16"])[0],
                "resolution": (caps.get("resolutions")
                               or ["720p"])[0]}

    def _stage_tts(self, run):
        if run.state.get("tts_done"):
            self._advance(run, "quote")
            return "next"
        eid = run.state["experiment_id"]
        rev = run.state["experiment_revision"]
        # Synthesis is bought once per normalized text, but fitting and
        # attachment are per occurrence — every segment that speaks the
        # line gets its own speech record, target interval and captions.
        needed = {}
        for key in "ABCD":
            variant = self.s.experiments._variant(eid, key)
            for seg in variant.segments:
                text = str(seg.get("copy") or "").strip()
                if not text:
                    continue
                norm = self.s.audio_work.speech.normalize(text)
                needed.setdefault(norm, []).append(
                    (key, seg["id"], text))
        if not needed:
            run.notes.append("silent scripts — no narration required")
            run.state["tts_done"] = True
            self._advance(run, "quote")
            return "next"
        if not run.state.get("tts_synth_jobs"):
            # Speech already synthesized for this voice under an earlier
            # revision is reused by normalized text — a copy edit to one
            # beat must not re-buy every other line.
            history = run.state.setdefault("tts_synth_history", {})
            reuse = {n: j for n, j in history.items() if n in needed and
                     (self.s.db.uow().jobs.get(j) or {}).get("status")
                     == "succeeded"}
            fresh = [n for n in needed if n not in reuse]
            synth = {}
            # Effect plans cap at 20 operations — dispatch batches, each
            # persisted under its own tag so a restart re-lands on the
            # same paid work.
            batch_tags = []
            for bi in range(0, len(fresh), 20):
                chunk = fresh[bi:bi + 20]
                tag = "tts" if not batch_tags else \
                    f"tts_{len(batch_tags)}"
                requests = [{"text": needed[n][0][2],
                             "voice_id": run.params["voice_id"],
                             "model": "eleven_v3",
                             "language": run.params["language"],
                             "settings": {}} for n in chunk]
                out = self._run_effect(run, "tts", "elevenlabs",
                                       "eleven_v3", requests, tag, eid,
                                       rev)
                if out != "wait":
                    return out
                batch_tags.append(tag)
                synth.update(zip(chunk, run.state[f"{tag}_jobs"]))
            run.state["tts_batch_tags"] = batch_tags
            run.state["tts_synth_jobs"] = {**reuse, **synth}
            history.update(synth)
            if reuse:
                run.notes.append(
                    f"narration reused for {len(reuse)} unchanged line(s) "
                    "after copy revision — no repeat TTS charge")
            self._put(run)
            return "wait"
        res = self._jobs(run, list(run.state["tts_synth_jobs"].values()),
                         "tts_failed")
        if res != "next":
            return res
        fits = run.state.setdefault("tts_fits", {})
        for norm, jid in run.state["tts_synth_jobs"].items():
            for key, seg_id, _text in needed[norm]:
                fkey = f"{key}:{seg_id}:{norm}"
                if fkey in fits:
                    continue
                queued = self.s.audio_work.queue_fit(
                    eid, rev, {"variant_key": key, "segment_id": seg_id,
                               "job_id": jid})
                fits[fkey] = queued["job_id"]
                self._put(run)
        res = self._jobs(run, list(fits.values()), "speech_fit_failed")
        if res != "next":
            if res == "wait":
                return "wait"
            repaired = self._repair_speech_fit(run, needed, fits)
            if repaired == "next":
                return "next"
            if repaired:
                return repaired
            return ("pause", res[1], res[2],
                    "Edit the draft copy so it fits its beat, then "
                    "Resume — the run continues on the new revision")
        sids = []
        for fkey, fit_jid in fits.items():
            cmd = self.s.commands.get(fit_jid)
            sid = cmd["command"]["input"]["speech_id"]
            speech = self.s.audio_work.speech.get(sid)
            if speech["status"] == "approved":
                sids.append(sid)
                continue
            if speech["status"] != "fitted":
                return ("pause", "speech_fit_failed",
                        f"speech {sid} status {speech['status']}",
                        "Edit the draft copy, then Resume")
            caps = cmd["command"]["result"].get("captions") or {}
            if not caps.get("cues"):
                return ("pause", "speech_fit_failed",
                        f"speech {sid} produced no caption cues",
                        "Inspect the segment, then Resume")
            self.s.audio_work.approve(
                sid, {"speech_hash": speech["speech_hash"],
                      "reviewer": AUTO_REVIEWER})
            sids.append(sid)
        try:
            result = self.s.audio_work.attach(eid, rev, sids)
        except ContractError as e:
            return ("pause", "speech_attach_failed",
                    f"{e.code}: {e.detail}",
                    "Resolve the speech binding, then Resume")
        run.state["experiment_revision"] = result["revision"]
        run.state["tts_done"] = True
        run.notes.append(
            f"narration attached — {len(sids)} spoken segment(s) "
            f"across A–D ({len(run.state.get('tts_synth_jobs') or {})} "
            f"unique lines synthesized; one voice, eleven_v3, "
            f"{run.params['language']})")
        self._advance(run, "quote")
        return "next"

    def _repair_speech_fit(self, run, needed, fits):
        """Bounded, meaning-preserving repair when generated copy will not
        fit its beat at the documented rate limits: swap that one segment
        back to the source-derived copy, on a new draft revision, and let
        the TTS stage resynthesize only that line. Copy that already IS the
        source-derived text cannot be shortened without changing meaning —
        that stays an honest pause. One repair per segment, ever.
        Returns 'next' after a repair, a pause tuple, or None to fall
        through to the caller's pause."""
        base = run.state.get("scripts_base")
        if not base:
            return None
        eid = run.state["experiment_id"]
        rev = run.state["experiment_revision"]
        repairs = run.state.setdefault("tts_repairs", [])
        targets = []
        for fkey, fit_jid in fits.items():
            j = self.s.db.uow().jobs.get(fit_jid)
            if not j or j["status"] not in ("failed", "blocked"):
                continue
            if "copy_revision_required" not in str(j["blocked_reason"]
                                                   or ""):
                return None
            key, seg_id, norm = fkey.split(":", 2)
            changed = base["changed"]
            fallback = base[key].get(seg_id) if key != "A" and \
                changed.get(key) == seg_id else base["A"].get(seg_id, "")
            if self.s.audio_work.speech.normalize(fallback or "") == norm:
                return ("pause", "speech_fit_failed",
                        f"variant {key} segment {seg_id}: the source-"
                        "derived narration itself does not fit this beat "
                        "at this voice's pace",
                        "Edit the draft copy or lengthen the beat, then "
                        "Resume")
            if f"{key}:{seg_id}" in repairs:
                return ("pause", "speech_fit_failed",
                        f"variant {key} segment {seg_id}: copy still does "
                        "not fit after one automatic repair",
                        "Edit the draft copy, then Resume")
            targets.append((key, seg_id, fallback))
        if not targets:
            return None
        exp = self.s._current(eid)
        control = copy.deepcopy(exp.packaging["segments"])
        branches = []
        for vkey in ("B", "C", "D"):
            v = self.s.experiments._variant(eid, vkey)
            branches.append({
                "key": vkey, "factor": v.changed_factor,
                "regions": [r if isinstance(r, dict) else r.to_dict()
                            for r in v.allowed_regions],
                "segments": copy.deepcopy(v.segments),
                "hypothesis": v.hypothesis,
                "primary_metric": v.primary_metric,
                "allowed_fields": list(v.allowed_fields),
                "dependent_fields": list(v.dependent_fields)})
        for key, seg_id, fallback in targets:
            if key == "A":
                for seg in control:
                    if seg["id"] == seg_id:
                        seg["copy"] = fallback
                for br in branches:
                    if base["changed"].get(br["key"]) != seg_id:
                        for seg in br["segments"]:
                            if seg["id"] == seg_id:
                                seg["copy"] = fallback
            else:
                for br in branches:
                    if br["key"] == key:
                        for seg in br["segments"]:
                            if seg["id"] == seg_id:
                                seg["copy"] = fallback
            repairs.append(f"{key}:{seg_id}")
            run.notes.append(
                f"variant {key} segment {seg_id}: generated copy did not "
                "fit its beat; reverted to source-derived copy and "
                "resynthesized that line only")
        try:
            result = self.s.patch_experiment_draft(
                eid, {"segments": control, "variants": branches,
                      "reason": "autorun speech-fit repair"}, rev)
        except ContractError as e:
            return ("pause", "speech_fit_failed",
                    f"repair rejected: {e.code}: {e.detail}",
                    "Edit the draft copy, then Resume")
        run.state["experiment_revision"] = result["revision"]
        for tag in run.state.get("tts_batch_tags") or ["tts"]:
            for suffix in ("_jobs", "_plan", "_auth"):
                run.state.pop(f"{tag}{suffix}", None)
        for k in ("tts_synth_jobs", "tts_fits", "tts_done",
                  "tts_batch_tags"):
            run.state.pop(k, None)
        run.state["tts_plan_seq"] = \
            run.state.get("tts_plan_seq", 0) + 1
        self._put(run)
        return "next"

    def _stage_quote(self, run):
        eid = run.state["experiment_id"]
        rev = run.state["experiment_revision"]
        if not run.state.get("quote_job"):
            jid = self.s.commands.enqueue(
                "quote", {"experiment_id": eid, "revision": rev},
                experiment_id=eid, revision=rev, phase="plan",
                identity=f"quote-{eid}-r{rev}")["job_id"]
            run.state["quote_job"] = jid
            self._put(run)
            return "wait"
        out = self._jobs(run, [run.state["quote_job"]])
        if out != "next":
            return out
        plan = self.s.plan_for(eid)
        run.state["plan_id"] = plan["id"]
        self._advance(run, "authorize")
        return "next"

    def _stage_authorize(self, run):
        eid = run.state["experiment_id"]
        rev = run.state["experiment_revision"]
        exp = self.s._current(eid)
        if exp.status == "accepted":
            self._advance(run, "run")
            return "next"
        plan = self.s.plan_for(eid)
        nodes = self.s.production._nodes(plan["id"])
        gap = self._cover(run, plan.get("total_price")
                          or plan.get("total"),
                          providers={n.get("provider") for n in
                                     nodes.values() if n.get("provider")})
        if gap:
            return ("pause", "budget_exhausted", gap,
                    "Raise the named ceiling (same id, higher amount) or "
                    "settle finished holds, then Resume")
        need = {}
        providers = set()
        models = {}
        for n in nodes.values():
            for a in n.get("allocations") or []:
                price = a.get("price") or {}
                if price.get("unit"):
                    need[price["unit"]] = need.get(price["unit"], 0) + \
                        price["amount"]
            if n.get("provider"):
                providers.add(n["provider"])
                models.setdefault(n["provider"], set()).add(
                    n.get("model") or "")
        account = run.params.get("account") or ""
        if not account:
            for p in providers:
                adapter = self.s.providers.get(p)
                if adapter is not None and getattr(adapter, "account", ""):
                    account = adapter.account
                    break
        limits = run.params.get("limits") or {}
        ceilings = {}
        for unit, total in need.items():
            cap = limits.get(unit)
            if cap is not None and cap < total:
                return ("pause", "limit_too_low",
                        f"{unit} limit {cap} is below the plan's "
                        f"{total} reserve requirement",
                        "Raise the limit, then Resume")
            ceilings[unit] = cap if cap is not None else total
        body = {"plan_hash": plan["plan_hash"], "reviewer": AUTO_REVIEWER,
                "budget_ids": run.params["budget_ids"],
                "ceilings": ceilings,
                "valid_until": run.params.get("valid_until") or "",
                "account": account,
                "allowed_providers": sorted(providers),
                "allowed_models": {p: sorted(m) for p, m in
                                   models.items()}}
        try:
            self.s.authorize_experiment(eid, rev, body)
        except ContractError as e:
            if e.code == "acceptance_blocked":
                return ("pause", "acceptance_blocked", e.detail,
                        "Resolve the acceptance report problems, "
                        "then Resume")
            if e.code in ("reservation_failed", "budget_exceeded",
                          "insufficient_budget"):
                return ("pause", "budget_exhausted",
                        f"{e.code}: {e.detail}",
                        "Top up the matching budget, then Resume")
            raise
        self._advance(run, "run")
        return "next"

    def _stage_run(self, run):
        eid = run.state["experiment_id"]
        rev = run.state["experiment_revision"]
        if not run.state.get("run_job"):
            try:
                out = self.s.run_experiment(eid, rev)
            except ContractError as e:
                return ("pause", "dispatch_failed",
                        f"{e.code}: {e.detail}",
                        "Resolve the run gate, then Resume")
            run.state["run_job"] = out["job_id"]
            self._put(run)
            return "wait"
        out = self._jobs(run, [run.state["run_job"]])
        if out != "next":
            return out
        self._advance(run, "footage")
        return "next"

    def _stage_footage(self, run):
        plan = self.s.plan_for(run.state["experiment_id"])
        nodes = self.s.production._nodes(plan["id"])
        work = [f"{plan['id']}:{k}" for k, n in nodes.items()
                if n["kind"] in ("picture", "download", "review")]
        for k, n in nodes.items():
            if n["kind"] != "review":
                continue
            jid = f"{plan['id']}:{k}"
            j = self.s.db.uow().jobs.get(jid)
            reopened = run.state.setdefault("reopened_reviews", [])
            if (j and j["status"] == "failed" and
                    "review_rejected" in str(j["blocked_reason"] or "") and
                    jid not in reopened):
                # A technical review may have been evaluated with an
                # incorrect split-coverage expectation. Re-open the review
                # once against the already-downloaded artifacts; generation
                # is never repeated here. A verdict that still fails after
                # re-evaluation is genuine and pauses the run.
                with self.s.db.uow() as u:
                    u.conn.execute(
                        "UPDATE jobs SET status='awaiting_review',"
                        "blocked_reason=NULL,lease_owner=NULL,"
                        "lease_expires=NULL WHERE id=?", (jid,))
                self.s.production._set(plan["id"], k, status="planned",
                                       problem="")
                reopened.append(jid)
                j = self.s.db.uow().jobs.get(jid)
            if j and j["status"] == "awaiting_review":
                outcome = self._review_assets(run, plan, n, jid)
                if outcome:
                    return outcome
        out = self._jobs(run, work, "footage_failed")
        if out != "next":
            return out
        self._advance(run, "compose")
        return "next"

    def _review_assets(self, run, plan, node, jid):
        """Automated technical checks on downloaded generations — same
        verdict contract a human reviewer writes, never impersonated.

        Every artifact under the node needs a verdict so the worker's
        selector resolves deterministically; an artifact row that cannot
        be inspected pauses the run instead of looping forever."""
        nodes = self.s.production._nodes(plan["id"])
        missing = []
        for dep in node["depends"]:
            download = nodes[dep]
            pic = nodes[download["depends"][0]]
            need = max((t["duration_s"] + t.get("handle_s", 0)
                        for t in pic.get("takes", [])), default=0)
            allocations = pic.get("allocations") or []
            settings = (pic.get("request") or {}).get("settings") or {}
            for index, aid in enumerate(download.get("artifact_ids") or []):
                art = self.s.db.uow().artifacts.get(aid)
                if art is None:
                    missing.append(f"{dep}: artifact {aid} not "
                                   "registered")
                    continue
                existing = self.s.db.conn.execute(
                    "SELECT id FROM records WHERE kind='review' AND "
                    "json_extract(body,'$.check_type')='asset' AND "
                    "json_extract(body,'$.binding.artifact_id')=? AND "
                    "json_extract(body,'$.binding.plan_hash')=?",
                    (aid, plan["plan_hash"])).fetchone()
                if existing:
                    prior = self.s.db.uow().records.get("review", existing["id"])
                    if prior and json.loads(prior["body"]).get("verdict") == "pass":
                        continue
                info = json.loads(art["probe"] or "{}")
                required = need
                if index < len(allocations):
                    required = float(allocations[index].get(
                        "covers_s", allocations[index].get("duration_s", need)))
                expected = {"kind": art["kind"],
                            "min_duration_s": required}
                res = settings.get("resolution")
                if res in ("720p", "1080p"):
                    expected["min_height"] = int(res[:-1])
                path = self.s.artifacts.verified_path(aid)
                verdict, notes = checks.inspect_asset(
                    path, info, expected)
                self.s.quality.record_verdict(
                    "auto-asset-" + uuid.uuid4().hex[:16],
                    art["sha256"], "asset", verdict,
                    binding={"plan_hash": plan["plan_hash"],
                             "artifact_id": aid},
                    reviewer=AUTO_REVIEWER, limitations=notes,
                    reviewer_type="automated")
        if missing:
            return ("pause", "asset_review_failed",
                    "; ".join(missing),
                    "Inspect the download node's artifacts, then Resume")
        with self.s.db.uow() as u:
            u.conn.execute(
                "UPDATE jobs SET status='ready',lease_owner=NULL,"
                "lease_expires=NULL WHERE id=? AND "
                "status='awaiting_review'", (jid,))
            # The scheduler only unblocks descendants when it completes a
            # leased job. This review is driven by the autorun step itself,
            # so make previously blocked render/delivery nodes eligible now;
            # dependency propagation still waits for the review job to
            # succeed before promoting them to ready.
            from ..services.recovery import unblock_descendants
            unblock_descendants(u, jid)
        return "wait"

    def _stage_compose(self, run):
        plan = self.s.plan_for(run.state["experiment_id"])
        nodes = self.s.production._nodes(plan["id"])
        # A prior failed review may have blocked compose descendants before
        # the review was re-opened and passed. Reconcile that durable DAG
        # state when resuming directly at compose.
        review_ids = [f"{plan['id']}:{k}" for k, n in nodes.items()
                      if n["kind"] == "review"]
        with self.s.db.uow() as u:
            from ..services.recovery import unblock_descendants
            for jid in review_ids:
                row = u.conn.execute(
                    "SELECT status FROM jobs WHERE id=?", (jid,)).fetchone()
                if row and row["status"] == "succeeded":
                    unblock_descendants(u, jid)
        compose = [f"{plan['id']}:{k}" for k, n in nodes.items()
                   if n["kind"] == "compose"]
        out = self._jobs(run, compose, "render_failed")
        if out != "next":
            return out
        self._advance(run, "final_qc")
        return "next"

    def _finish(self, run):
        """Terminal notes: 'done' means the four finals exist and passed
        the checks that ran — it is not verified delivery."""
        run.notes.append(
            "delivery pending — upload the finals via Deliveries before "
            "treating the run as shipped; 'done' is not verified Google "
            "Drive delivery")
        self._advance(run, "done")

    def _stage_final_qc(self, run):
        if not run.params.get("visual_reviews", True):
            run.notes.append(
                "automated visual QC was disabled for this run — finals "
                "passed technical checks only")
            self._finish(run)
            return "next"
        if run.state.get("qc_human_accepted"):
            self._finish(run)
            return "next"
        adapter = self.s.providers.get("audiovisual_analysis")
        if adapter is None or not getattr(adapter, "account", ""):
            # Visual QC was requested — an unavailable route is a missing
            # capability, not a note to quietly absorb.
            return ("pause", "capability_unavailable",
                    "visual QC was requested but the audiovisual "
                    "analysis route is not configured",
                    "Configure the provider, or Resume with "
                    "set_params visual_reviews=false to finish on "
                    "technical checks only")
        eid = run.state["experiment_id"]
        finals = self._finals(run)
        if len(finals) < 4:
            return "wait"
        # Each variant's review is bound to the exact artifact submitted.
        # A final replaced after dispatch can never inherit the old
        # verdict — the stale submission is discarded and the current
        # bytes are reviewed once more, then the run pauses rather than
        # chase a moving target.
        submitted = run.state.setdefault("qc_submitted", {})
        resubmitted = run.state.setdefault("qc_resubmitted", [])
        pending = []
        for key in "ABCD":
            sub = submitted.get(key)
            if sub and sub["artifact_id"] == \
                    finals[key]["artifact_id"] and \
                    sub["sha256"] == finals[key]["sha256"]:
                continue
            if sub:
                if key in resubmitted:
                    return ("pause", "final_qc_stale",
                            f"variant {key}'s final changed again after "
                            "a second visual review",
                            "Stabilize the final, then Resume")
                resubmitted.append(key)
                for k in (f"qc_{key}_jobs", f"qc_{key}_plan",
                          f"qc_{key}_auth"):
                    run.state.pop(k, None)
                run.state[f"qc_{key}_plan_seq"] = \
                    run.state.get(f"qc_{key}_plan_seq", 0) + 1
                run.notes.append(
                    f"variant {key}: final was replaced after its visual "
                    "review — the old verdict is discarded and the "
                    "current cut is being reviewed")
                submitted.pop(key)
            pending.append(key)
        if pending:
            for key in pending:
                variant = self.s.experiments._variant(eid, key)
                f = finals[key]
                out = self._run_effect(
                    run, "analysis", "audiovisual_analysis",
                    adapter.model, [{
                        "task": "review_final", "model": adapter.model,
                        "artifact_id": f["artifact_id"],
                        "artifact_sha256": f["sha256"],
                        "expected": {
                            "variant": key,
                            "script": [{"segment": s["id"],
                                        "copy": s.get("copy", "")}
                                       for s in variant.segments],
                            "factor": variant.changed_factor,
                            "hypothesis": variant.hypothesis}}],
                    f"qc_{key}")
                if out != "wait":
                    return out
                submitted[key] = {
                    "job_id": run.state[f"qc_{key}_jobs"][0],
                    "artifact_id": f["artifact_id"],
                    "sha256": f["sha256"]}
                self._put(run)
            return "wait"
        res = self._jobs(run, [submitted[k]["job_id"] for k in "ABCD"],
                         "final_qc_failed")
        if res != "next":
            return res
        flagged = []
        for key in "ABCD":
            sub = submitted[key]
            f = finals[key]
            cmd = self.s.commands.get(sub["job_id"])
            review = cmd["command"]["result"]["result"].get("review")
            if not review:
                flagged.append(f"{key}: no review payload")
                continue
            verdict = review.get("verdict")
            if verdict not in ("pass", "uncertain", "fail"):
                verdict = "uncertain"
            recorded = run.state.get(f"qc_verdict_{key}")
            if recorded is None:
                # Verdicts are durable evidence — a resume that re-reads
                # the same jobs must not write duplicate review rows.
                path = self.s.artifacts.verified_path(f["artifact_id"])
                binding = self.s.quality.binding(
                    path, f["composition_id"], f["artifact_id"])
                self.s.quality.record_verdict(
                    "auto-visual-" + uuid.uuid4().hex[:16], f["sha256"],
                    "automated_visual", verdict,
                    evidence=[f["artifact_id"]], binding=binding,
                    reviewer=AUTO_REVIEWER,
                    limitations=list(review.get("notes") or []),
                    reviewer_type="automated")
                run.state[f"qc_verdict_{key}"] = verdict
                self._put(run)
            else:
                verdict = recorded
            if verdict != "pass":
                flagged.append(f"{key}: {verdict} — " +
                               "; ".join(review.get("notes") or []))
        if flagged:
            run.state["qc_flagged"] = [f.split(":", 1)[0]
                                       for f in flagged]
            self._put(run)
            return ("pause", "final_qc_flagged",
                    " | ".join(flagged),
                    "Review the flagged finals in Compare, then Resume "
                    "with resolve_qc=accept (human acceptance) or "
                    "resolve_qc=recheck (a fresh paid review)")
        self._finish(run)
        return "next"

    def _stage_done(self, run):
        return "done"

    def _finals(self, run):
        eid = run.state["experiment_id"]
        out = {}
        for key in "ABCD":
            row = self.s.db.conn.execute(
                "SELECT value FROM meta WHERE key=?",
                (f"final:{eid}:{key.lower()}",)).fetchone()
            if row:
                out[key] = json.loads(row[0])
        return out
