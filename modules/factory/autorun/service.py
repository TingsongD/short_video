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

from ..analysis.analyzer import validate_temporal
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
    "analysis_review": "Analysis checks", "blueprint": "Blueprint",
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
        body=dict(body)
        if 'spending_policy' in body:
            raise ContractError('server_managed_policy', 'spending_policy')
        profile=body.get('profile_id','legacy')
        if profile not in ('legacy','flashcut_hypit.v1'):
            raise ContractError('unsupported_profile','profile_id')
        if profile=='flashcut_hypit.v1':
            if body.get('reference_policy','disabled')!='disabled':
                raise ContractError('reference_route_disabled','profile_id')
            from .policies import new_policies
            body['policies']=new_policies(body.get('policies') or {},authorized_destination=bool(self.s.config.get('drive_folder_id')))
            if body['policies']['captions']!='phrases.v1' or body.get('visual_reviews',True) is not True:
                raise ContractError('flashcut_quality_policy_required','profile_id')
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
        self.budgets.require_selection(budget_ids)
        from .readiness import runtime_ready
        runtime_ready(self.s)
        reference_policy = body.get('reference_policy', 'disabled')
        if reference_policy not in ('disabled', 'first_clip.v1'):
            raise ContractError('invalid_reference_policy', 'reference_policy')
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
        run_id = "auto-" + uuid.uuid4().hex[:16]
        from .policies import new_spending_policy
        spending_policy = new_spending_policy(run_id)
        budget_ids.append(spending_policy['budget_id'])
        run = AutoRun(
            schema_version="autorun.v1",
            id=run_id, created_at=utcnow(),
            seed_id=seed_id,
            params={
                "workflow": {"version": 2, "prompt_policy": "scene.v2", "qc_policy": "visual.v2",
                             "visual_qc": bool(body.get('visual_reviews', True)), 'reference_policy': reference_policy},
                "source_timing_policy": "source_timing.v1",
                "delivery_tracking": "verified_receipts.v1",
                "voice_id": voice, "language": language,
                "budget_ids": budget_ids, "limits": limits,
                "spending_policy": spending_policy,
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
        if 'policies' in body:
            from .policies import new_policies
            run.params['policies'] = new_policies(body['policies'],
                authorized_destination=bool(self.s.config.get('drive_folder_id')))
            if run.params['policies']['delivery'] == 'after_qc':
                if not self.s.config.get('drive_folder_id'):
                    raise ContractError('destination_not_authorized', 'drive_folder_id')
                if not run.params['visual_reviews']:
                    raise ContractError('visual_qc_required', 'visual_reviews')
                run.params['delivery_folder_id'] = self.s.config['drive_folder_id']
                account = getattr(getattr(self.s.delivery, 'drive', None), 'expected_account', '')
                if not account and self.s.config.get('mode') == 'offline':
                    account = 'fixture-drive'
                if not account:
                    raise ContractError('delivery_account_required', 'account')
                run.params['delivery_account'] = account
        if profile=='flashcut_hypit.v1':
            from ..analysis.evidence_policy import new_flashcut_policy
            run.params.update(profile_id=profile,flashcut_policy=new_flashcut_policy())
        # The server-issued guardrail and its run record must either both
        # exist or neither exist. Nested unit-of-work calls use savepoints
        # beneath this outer transaction.
        with self.s.db.uow():
            self.budgets.create_budget(
                spending_policy['budget_id'], spending_policy['unit'],
                'experiment', run.id, spending_policy['cap_amount'])
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
        return [self._recovery_view(self._load(r)) for r in rows]

    def _recovery_view(self, run):
        from .recovery import AnalysisRecovery
        from .scene_review import SceneReview
        out = run.to_dict()
        from .policies import run_spending_policy
        spending = run_spending_policy(run.params)
        if spending:
            remaining = self.budgets.available(spending['budget_id'])
            out['spending_policy'] = {
                **spending,
                'committed': spending['cap_amount'] - remaining,
                'remaining': remaining,
            }
        if run.params.get('flashcut_policy'):
            from .flashcut import FlashcutAnalysis
            out['source_analysis']=FlashcutAnalysis(self).status(run)
        wait = run.state.get('provider_wait')
        if isinstance(wait, dict) and wait.get('job_id'):
            out['provider_wait'] = self._provider_wait_view(wait)
        out['recovery'] = AnalysisRecovery(self.s).describe(run)
        if run.status == 'paused' and (run.pause.get('code', '').startswith('ai_scene_review_')
                                      or run.pause.get('code') == 'blueprint_flags'):
            unknown = SceneReview(self.s).unfinished(run)
            out['recovery'] = {
                'title': 'Earlier provider request needs reconciliation' if unknown else 'Ready to continue',
                'message': ('Resolve the earlier paid request before continuing. No automatic retry will run.'
                            if unknown else 'The scene-review step has been removed. Resume to continue with technical validation.'),
                'can_resume': not unknown,
            }
            out['pause'] = {**out['pause'], 'action': out['recovery']['message']}
        return out

    def _provider_wait_view(self, wait):
        from datetime import datetime, timezone
        from .waiting import provider_wait_view
        jid = wait['job_id']
        job = self.s.db.uow().jobs.get(jid)
        attempts = list(self.s.db.conn.execute(
            'SELECT id, remote_id, status, created_at FROM attempts WHERE job_id=? ORDER BY attempt_seq',
            (jid,)))
        observations = []
        for attempt in attempts:
            row = self.s.db.conn.execute(
                "SELECT created_at FROM events WHERE stream=? AND type='observed' ORDER BY seq DESC LIMIT 1",
                ('attempt:' + attempt['id'],)).fetchone()
            if row:
                observations.append({'attempt_id': attempt['id'], 'created_at': row['created_at']})
        return provider_wait_view(wait, job, attempts, observations, now=datetime.now(timezone.utc))

    def detail(self, run_id):
        run = self.get(run_id)
        out = self._recovery_view(run)
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
            out["finals_state"] = self._finals_state(run)
        return out

    def _finals_state(self, run):
        """Per-variant final state for the dashboard: missing → rendered
        (awaiting mandatory checks) → ready_for_review (mandatory checks
        pass, visual review pending/disabled) → validation_blocked
        (checks failed, stale or missing) → done (run finished). A file
        existing is never reported as validated on its own."""
        finals = self._finals(run)
        state = {}
        problems = []
        no_plan = ""
        if finals and run.state.get("experiment_id"):
            try:
                plan = self.s.plan_for(run.state["experiment_id"])
                if len(finals) == 4:
                    problems = self._mandatory_qc(run, plan, finals)
                else:
                    problems = [(f"{k}: final was rendered under "
                                 "superseded plan "
                                 f"{finals[k].get('plan_id')}", True)
                                for k in finals
                                if finals[k].get("plan_id") != plan["id"]]
            except ContractError as e:
                no_plan = f"no current production plan ({e.code})"
        by_key = {}
        for msg, _sup in problems:
            key = msg.split(":", 1)[0]
            by_key.setdefault(key, []).append(msg)
        delivered = {r[0] for r in self.s.db.conn.execute(
            "SELECT DISTINCT json_extract(body,'$.file_sha256') "
            "FROM records WHERE kind='delivery' AND "
            "json_extract(body,'$.status')='verified'").fetchall()}
        passed = {r[0] for r in self.s.db.conn.execute(
            "SELECT DISTINCT json_extract(body,'$.target_hash') "
            "FROM records WHERE kind='review' AND "
            "json_extract(body,'$.verdict') IN ('pass','accepted') AND "
            "json_extract(body,'$.invalidated_by') IS NULL").fetchall()}
        for key in "ABCD":
            f = finals.get(key)
            if not f:
                state[key] = {"state": "missing", "problems": []}
                continue
            entry = {"state": "ready_for_review",
                     "artifact_id": f["artifact_id"],
                     "problems": by_key.get(key, [])}
            if no_plan:
                entry["problems"].append(f"{key}: {no_plan}")
            if entry["problems"]:
                entry["state"] = "validation_blocked"
            elif not (f.get("check_ids") or []):
                # Rendered bytes with no recorded checks are not yet
                # validated — the mandatory gate has not evaluated them.
                entry["state"] = "rendered"
            elif f.get("sha256") in delivered:
                entry["state"] = "delivered"
            elif run.status == "succeeded":
                entry["state"] = "done"
            elif f.get("sha256") in passed:
                entry["state"] = "validated"
            state[key] = entry
        return state

    def recover_analysis_response(self, run_id, body):
        from .recovery import AnalysisRecovery
        return AnalysisRecovery(self.s).recover(run_id, body)

    def resume(self, run_id, body=None):
        with self.s.db.uow():
            return self._resume(run_id, body)

    def _resume(self, run_id, body=None):
        run = self.get(run_id)
        if run.status != "paused":
            return run.to_dict()
        body = body or {}
        for selection in ('budget_ids', 'add_budget_ids'):
            if selection in body:
                self.budgets.require_selection(body[selection])
        from .recovery import AnalysisRecovery
        retry_approval = AnalysisRecovery(self.s).guard_resume(run, body)
        from .scene_review import SceneReview
        scene_review = SceneReview(self.s)
        if body.get('scene_review_action') is not None:
            raise ContractError('scene_review_removed', 'scene_review_action',
                                'Scene review was removed. Use Resume without a review action.')
        scene_review.guard_resume(run)
        from .readiness import runtime_ready
        runtime_ready(self.s)
        if body.get('approve_flashcut_response_recovery') is True:
            from .flashcut_recovery import FlashcutResponseRecovery
            FlashcutResponseRecovery(self).enable(run, body.get('reviewer'))
        if body.get('approve_flashcut_format_recovery') is not None:
            from .flashcut_format_recovery import FlashcutFormatRecovery
            FlashcutFormatRecovery(self).enable(run,body['approve_flashcut_format_recovery'],body.get('reviewer'))
        if body.get('approve_flashcut_evidence_reuse') is True:
            from .flashcut_format_recovery import FlashcutFormatRecovery
            FlashcutFormatRecovery(self).enable_context_reuse(run,body)
        replacement = body.get("budget_ids")
        if replacement is not None:
            replacement = [str(b) for b in replacement]
            if not replacement:
                raise ContractError("budgets_required", "budget_ids")
            for bid in replacement:
                self.budgets.available(bid)       # raises unknown_budget
            from .policies import run_spending_policy
            spending = run_spending_policy(run.params)
            if spending:
                replacement.append(spending['budget_id'])
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
                    "generate_music", "account"}
        for key, value in (body.get("set_params") or {}).items():
            if key not in settable:
                raise ContractError("param_not_resumable", key)
            if key == 'visual_reviews' and run.params.get('workflow') and value != run.params.get(key):
                raise ContractError('new_draft_required', key,
                                    'QC requirements are frozen with this workflow; start a new run to change them.')
            if key == "account":
                choice, _ = self._generation_route(run)
                adapter = self.s.providers.get(self._provider_name(choice))
                if not value or value != getattr(adapter, 'account', None):
                    raise ContractError('provider_account_mismatch', 'account',
                                        'Use the configured generation provider account.')
                if (run.state.get('plan_id') and value != run.params.get('account')
                        and self.s._current(run.state['experiment_id']).revision ==
                        run.state.get('experiment_revision')):
                    raise ContractError('new_draft_required', 'account',
                                        'Save a new draft revision before changing production authority.')
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
        self._rebind_current_revision(run)
        self._reset_budget_blocked_effect(run)
        if run.params.get('workflow') and run.pause.get('code') == 'delivery_failed':
            run.state['delivery_recovery_requested'] = True
        run.status = "running"
        run.pause = {}
        run.state["step_seq"] = run.state.get("step_seq", 0) + 1
        if retry_approval:
            run.progress.append({'stage':run.stage, 'at':utcnow(), 'outcome':'paid_retry_approved',
                **retry_approval, 'budget_ids':list(run.params.get('budget_ids') or []),
                'limits':dict(run.params.get('limits') or {})})
        run.progress.append({"stage": run.stage, "at": utcnow(),
                             "outcome": "resumed"})
        self._put(run)
        self._enqueue_step(run)
        return run.to_dict()

    def _rebind_current_revision(self, run):
        """A draft edit during ANY pause invalidates downstream work that
        was quoted, authorized, rendered or reviewed against the old
        revision. Rebind the run to the current revision and rewind so a
        Resume re-quotes current content instead of reusing stale paid
        state. Old verdicts and finals never authorize new bytes."""
        eid = run.state.get("experiment_id")
        if not eid:
            return
        current = self.s._current(eid)
        prior = run.state.get("experiment_revision")
        if not prior or current.revision == prior:
            return
        stage = run.stage
        # Reconcile before replace: a job or attempt that may still be
        # dispatching must reach a terminal state (or be reconciled)
        # before a fresh paid scope can be created — otherwise the old
        # plan keeps billing in parallel.
        job_refs = list(run.state.get("production_jobs") or [])
        if run.state.get('plan_id'):
            job_refs += [r['id'] for r in self.s.db.conn.execute(
                'SELECT id FROM jobs WHERE id LIKE ?', (run.state['plan_id'] + ':%',))]
        for tag in run.state.get("tts_batch_tags") or ["tts"]:
            job_refs += run.state.get(f"{tag}_jobs") or []
        if run.params.get('workflow'):
            for key, value in run.state.items():
                if key.startswith(('reference_clip_', 'reference_overlay_', 'reference_check_')) and key.endswith('_jobs'):
                    job_refs += value or []
        pending = [jid for jid in job_refs
                   if (self.s.db.uow().jobs.get(jid) or {})
                   .get("status") not in
                   ("succeeded", "failed", "blocked", "cancelled")]
        for jid in job_refs:
            pending += [str(a["id"]) for a in self.s.db.conn.execute(
                "SELECT id,status FROM attempts WHERE job_id=?",
                (jid,)).fetchall()
                if a["status"] in ("prepared", "dispatching",
                                   "unknown", "accepted", "running",
                                   "cancel_requested")]
        if stage in ("tts", "quote", "authorize", "run", "footage",
                     "compose", "final_qc") and pending:
            if run.params.get('workflow'):
                raise ContractError('prior_revision_inflight', 'attempts',
                    'Resolve the original revision’s pending or unknown operations before adopting this edit. No replacement work was submitted.')
            run.notes.append(
                f"draft revision changed {prior}→{current.revision} but "
                f"the prior revision still has in-flight work "
                f"({len(pending)} job/attempt refs); it must reach a "
                "terminal state or be reconciled before the run can "
                "re-quote — the stage was left in place")
            return
        run.state["experiment_revision"] = current.revision
        if stage == "tts":
            for tag in run.state.get("tts_batch_tags") or ["tts"]:
                for suffix in ("_jobs", "_plan", "_auth"):
                    run.state.pop(f"{tag}{suffix}", None)
            for key in ("tts_synth_jobs", "tts_fits", "tts_done",
                        "tts_batch_tags"):
                run.state.pop(key, None)
            run.state["tts_plan_seq"] = \
                run.state.get("tts_plan_seq", 0) + 1
            run.notes.append(
                f"copy revised from experiment revision {prior} to "
                f"{current.revision}; narration will be regenerated")
        elif stage in ("quote", "authorize", "run", "footage",
                       "compose", "final_qc"):
            for key in ("quote_job", "plan_id", "authorize_job", "run_job",
                        "production_jobs", "qc_submitted",
                        "qc_resubmitted", "qc_rechecks", "qc_flagged",
                        "qc_human_accepted"):
                run.state.pop(key, None)
            for key in list(run.state):
                if key.startswith("qc_verdict_") or (
                        key.startswith("qc_") and key.endswith(
                            ("_jobs", "_plan", "_auth"))):
                    run.state.pop(key, None)
            run.stage = "quote"
            run.notes.append(
                f"production state invalidated after draft revision "
                f"{prior}→{current.revision}; a fresh quote, render and "
                "review will be created on Resume")

    def _reset_budget_blocked_effect(self, run):
        """Let Resume create a fresh paid plan after a recoverable failure.

        Effect plans and authorizations are immutable, and paid jobs cannot be
        locally retried.  Once a worker has terminally failed while reserving
        funds, keeping the stage's job ids makes every Resume immediately see
        the same dead job.  Remove only the current paid-stage references
        after every attempt is terminal and its reservation is released or
        settled; the next step will quote and authorize a new plan against
        the operator's current budget selection.
        """
        safe_qc_recovery = (run.params.get('workflow', {}).get('version') == 2 and run.stage == 'final_qc'
                            and run.pause.get('code') in ('capability_unavailable', 'final_qc_failed'))
        if not safe_qc_recovery and run.pause.get("code") not in (
                "budget_exhausted", "analysis_failed", "analysis_invalid",
                "analysis_unavailable"):
            return
        tags = {
            "video_analysis": ["analysis"],
            "sections": ["analysis"],
            "blueprint": ["analysis"],
            "script": ["script", "script_repair"],
            "music": ["music"],
            "tts": run.state.get("tts_batch_tags") or ["tts"],
            "final_qc": [f"qc_{k}" for k in "ABCD"],
        }
        cleared = set()
        for tag in tags.get(run.stage, []):
            jobs = run.state.get(f"{tag}_jobs") or []
            attempts = []
            for jid in jobs:
                attempts.extend(self.s.db.conn.execute(
                    "SELECT status,json_extract(body,'$.reservation_id') "
                    "AS reservation_id FROM attempts WHERE job_id=?",
                    (jid,)).fetchall())
            # An unknown or still-dispatching attempt may have reached the
            # provider.  It must be reconciled by identity before any fresh
            # paid plan can be created.
            if any(a["status"] in ("prepared", "dispatching", "unknown",
                                   "accepted", "running", "cancel_requested")
                   for a in attempts):
                continue
            if any(a["reservation_id"] and
                   (self.s.db.conn.execute(
                       "SELECT status FROM reservations WHERE id=?",
                       (a["reservation_id"],)).fetchone() or {"status": "held"})["status"]
                   not in ("released", "settled") for a in attempts):
                continue
            # Terminal jobs justify a reset outright; an *invalid result*
            # pause is different — the attempt succeeded and was billed,
            # so the operator must have settled its hold first (the
            # reservation guard above), then the dead reference clears.
            if not any((self.s.db.uow().jobs.get(jid) or {}).get("status")
                       in ("failed", "blocked", "cancelled")
                       for jid in jobs) and \
                    run.pause.get("code") not in (
                        "analysis_invalid", "analysis_unavailable"):
                continue
            run.state.pop(f"{tag}_jobs", None)
            run.state.pop(f"{tag}_plan", None)
            run.state.pop(f"{tag}_auth", None)
            # A new plan id for identical requests — the dead jobs'
            # queue identities are bound to the old plan and stay dead.
            run.state[f"{tag}_plan_seq"] = \
                run.state.get(f"{tag}_plan_seq", 0) + 1
            cleared.add(tag)
            submitted = run.state.get("qc_submitted") or {}
            for key, sub in list(submitted.items()):
                if sub.get("job_id") in jobs:
                    submitted.pop(key)
        if "analysis" in cleared:
            run.state.pop("analysis", None)
            run.state.pop("blueprint_id", None)
            run.state["analysis_reset"] = True
            if run.stage in ("sections", "blueprint"):
                run.stage = "video_analysis"
            run.notes.append(
                "invalid analysis discarded after settlement; a fresh "
                "analysis attempt will be planned on Resume")
        if run.stage == "tts":
            run.state.pop("tts_synth_jobs", None)
            run.state.pop("tts_batch_tags", None)
            if cleared:
                run.notes.append(
                    f"discarded terminal {tag} plan after budget "
                    "recovery; a fresh quote and authorization will be "
                    "created")

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
            if run.params.get('workflow'):
                for key in flagged:
                    self._begin_visual(run, key, self._finals(run)[key])
            run.notes.append(
                "flagged finals resubmitted for a fresh paid visual "
                "review at the operator's request")
        else:
            raise ContractError("invalid_resolve_qc", "resolve_qc")

    # ------------------------------------------------------ step loop

    def step(self, body, job):
        run = self.get(body["run_id"])
        if run.status != "running":
            return {"status": "succeeded", "run": run.status}
        try:
            outcome = self._drive(run)
        except ContractError as e:
            from ..diagnostics import event
            from ..events.redact import redact
            event("run_contract_error", run_id=run.id, stage=run.stage,
                  code=e.code, error_type=type(e).__name__)
            detail = redact(f"{e.code}: {e.detail}")[:800]
            action = "Correct the reported validation problem, then Resume; completed work is preserved."
            if e.code.startswith("review_proxy_"):
                detail = ("The final video's analysis copy could not be prepared or verified. "
                          "The original final video is preserved; no new footage is needed.")
                action = ("Repair the local review copy preparation and verify its size, timeline and audio, "
                          "then Resume final quality checks.")
            outcome = self._pause(run, e.code, detail, action)
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
        from ..diagnostics import event
        event("run_paused", run_id=run.id, stage=run.stage, code=code)
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
        if (run.state.get('provider_wait') or {}).get('job_id') in ids:
            run.state.pop('provider_wait', None)
        for jid in ids:
            j = self.s.db.uow().jobs.get(jid)
            if j is None:
                continue
            if j['status'] == 'ready' and j.get('blocked_reason') in ('analysis_throttled', 'retry_backoff', 'remote_unfinished', 'capacity_full'):
                run.state['provider_wait'] = {'job_id': jid, 'reason': j['blocked_reason'],
                                              'next_attempt_at': j.get('next_attempt_at')}
            if j["status"] in ("failed", "blocked", "cancelled"):
                reason = str(j["blocked_reason"] or j["status"])
                if reason == 'analysis_http_error' and self.s.effect_work.resume_throttled_job(jid):
                    return 'wait'
                from ..providers.recovery import credential_recovery, analysis_recovery
                recovery = credential_recovery(reason) or analysis_recovery(reason)
                if recovery:
                    return ("pause", fail_code, f"job {jid}: {reason}", recovery)
                if any(t in reason for t in ('authority_required', 'provider_account_mismatch',
                                             'reservation_identity_conflict')):
                    return ("pause", fail_code, f"job {jid}: {reason}",
                            "Verify the provider account and exact plan authorization, then "
                            "reconcile failed attempts before recovery. Raising a budget "
                            "does not fix an identity mismatch.")
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
                cap_row = self.s.db.conn.execute(
                    "SELECT cap_amount FROM budgets WHERE id=?",
                    (bid,)).fetchone()
                cap = cap_row["cap_amount"] if cap_row else None
                committed = self.budgets._committed(self.s.db.conn, bid)
                have = 0 if cap is None else cap - committed
                if have < amount:
                    kind = ("selected" if bid in selected
                            else "aggregate ceiling")
                    cap_txt = "uncapped" if cap is None else str(cap)
                    return (f"{unit}: need {amount}, budget {bid} "
                            f"({kind}): cap {cap_txt}, committed "
                            f"{committed}, available {have} — every "
                            "applicable ceiling must cover the full "
                            "amount")
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
        if run.params.get('workflow') and provider not in ('audiovisual_analysis_flashcut','jev_decisions'):
            requests = [{**request, 'workflow_version': 2, 'autorun_id': run.id, 'workflow_effect': tag}
                        for request in requests]
        state_key = f"{tag}_jobs"
        if run.state.get(state_key):
            return "wait"
        adapter = self.s.providers.get(provider)
        if adapter is None or not getattr(adapter, "account", ""):
            return ("pause", "route_unavailable",
                    f"provider {provider} is not configured",
                    "Configure the provider route, then Resume")
        from .readiness import provider_ready
        blocked = provider_ready(self.s, provider, run_id=run.id)
        if blocked:
            return blocked
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
                plan_id=plan_id, valid_until=run.params.get('valid_until', ''))
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
            self.s.ref_analysis.start(run.seed_id, AUTO_REVIEWER,
                                      evidence_policy='immutable.v2' if run.params.get('workflow') else 'legacy')
            seq = run.state.get("evidence_seq", 0)
            ident = f"auto:{run.id}:evidence" if seq == 0 else \
                f"auto:{run.id}:evidence:{seq}"
            jid = self.s.commands.enqueue(
                "analysis_evidence", {"seed_id": run.seed_id},
                phase="analyze",
                identity=ident)["job_id"]
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
        # A recovered transcript (import/declare) pops the evidence
        # stage so grids can be rebuilt against the new words. The
        # original evidence job already succeeded — enqueue a new
        # identity instead of treating that old success as current.
        evidence_done = (a.stages or {}).get("evidence", {}).get("done")
        if a.status == "in_progress" and not evidence_done:
            run.state["evidence_seq"] = run.state.get("evidence_seq", 0) + 1
            run.state.pop("evidence_job", None)
            self._put(run)
            return "next"
        self._advance(run, "video_analysis")
        return "next"

    def _stage_video_analysis(self, run):
        if run.params.get('flashcut_policy'):
            from .flashcut import FlashcutAnalysis
            return FlashcutAnalysis(self).advance(run)
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
        # Analysis runs on the production master unless the operator
        # explicitly selected a registered analysis derivative — a proxy
        # is consumed by choice, never by silently becoming the master.
        asset_id = seed.source_asset_id
        if run.params.get("analysis_asset_id"):
            wanted = run.params["analysis_asset_id"]
            if wanted != seed.analysis_asset_id:
                return ("pause", "analysis_scope_mismatch",
                        f"requested analysis asset {wanted} is not the "
                        "seed's registered analysis derivative",
                        "Attach it with role=analysis on the seed, then "
                        "Resume")
            asset_id = wanted
            run.notes.append(
                f"analysis input is the registered derivative {asset_id}"
                f" — the production master remains "
                f"{seed.source_asset_id}")
        art = self.s.db.uow().artifacts.get(asset_id)
        run.state['analysis_source_sha'] = self.s.db.uow().artifacts.get(seed.source_asset_id)['sha256']
        out = self._run_effect(
            run, "analysis", "audiovisual_analysis", adapter.model,
            [{"task": "analyze", "artifact_id": asset_id,
              "artifact_sha256": art["sha256"], "model": adapter.model,
              **({'creative_policy': 'scene.v2', 'workflow_version': 2} if run.params.get('workflow') else {})}],
            "analysis")
        if out != "wait":
            return out
        res = self._jobs(run, run.state["analysis_jobs"], "analysis_failed")
        if res != "next":
            return res
        cmd = self.s.commands.get(run.state["analysis_jobs"][0])
        payload = cmd["command"]["result"]["result"]
        a = self.s.ref_analysis.get(run.seed_id)
        try:
            validate_temporal(payload, a.acquisition.get("duration_s") or 0)
        except ContractError as e:
            run.state.pop("analysis", None)
            run.notes.append("analysis rejected: structurally invalid "
                             "timing — never stored or built on")
            return ("pause", "analysis_invalid",
                    f"the analysis result failed timing validation: "
                    f"{e.code} {e.detail}",
                    "Settle the completed analysis hold (the provider "
                    "billed the call), then Resume to buy a fresh "
                    "analysis — or attach corrected observations")
        run.state["analysis"] = payload
        self._advance(run, "sections")
        return "next"

    def _transcript(self, run):
        """Best available word-timed transcript: the approved aligned
        file first (ground truth the safety gate already approved), then
        the provider payload. A file on disk that no longer belongs to
        an *aligned* transcript of the current source is not evidence —
        it is never silently substituted for one."""
        a = self.s.ref_analysis.get(run.seed_id)
        from .scene_review import SceneReview
        review=SceneReview(self.s)
        if review.verified(run,a.source_sha256) or review.manual_verified(run,a.source_sha256):
            transcript=copy.deepcopy(run.state['analysis']['transcript'])
            prior=run.state.get('analysis_before_manual_review') if review.manual_verified(run,a.source_sha256) else run.state.get('analysis_before_ai_review')
            # Corrected audible words can reveal that the old language label
            # described translated subtitles instead of speech. Do not label
            # new words with stale metadata: the existing explicit translation
            # stage will detect their language and produce the requested one.
            changed_words=([t['text'] for t in transcript] !=
                [t.get('text','') for t in (prior or {}).get('transcript',[])])
            run.state['source_language'] = 'auto' if changed_words else self.s.ref_analysis.source_language(a)
            return transcript
        if a.transcript.get("status") == "aligned" and \
                a.transcript.get("source_sha256") in (None, "",
                                                      a.source_sha256):
            path = self.s.ref_analysis.verified_transcript(a)
            if path.exists():
                data = json.loads(path.read_text())
                passages = data.get("passages") or data.get("segments") \
                    or []
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
                            "text": text, "words": copy.deepcopy(p.get("words") or [])})
                if out:
                    # Source language provenance travels with the words —
                    # script adaptation decides whether translation is an
                    # explicit paid stage before any copy is written.
                    run.state["source_language"] = \
                        a.transcript.get("language") or \
                        data.get("language") or \
                        self.s.ref_analysis.source_language(a)
                    return out
        run.state["source_language"] = \
            self.s.ref_analysis.source_language(a)
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
        try:
            sections = checks.build_sections(payload, dur, bp_hint)
        except ContractError as e:
            return ("pause", "analysis_invalid",
                    f"observations failed timing validation: "
                    f"{e.code} {e.detail}",
                    "Correct the beats/observations in the Analysis "
                    "tab, then Resume — or settle the analysis hold and "
                    "Resume to buy a fresh analysis")
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
        from .scene_review import SceneReview
        scene_review = SceneReview(self.s)
        # Retired reviews are never replayed, and removing the feature must
        # not erase an unknown paid operation's recovery requirement.
        scene_review.guard_resume(run)
        bp_id = blueprint_id_for(run.seed_id)
        payload, _, _ = self._beats(run)
        seed = self.s.seeds.get(run.seed_id)
        source = self.s.db.uow().artifacts.get(seed.source_asset_id)
        if not source:
            raise ContractError('source_not_ready', 'artifact_id')
        if run.state.get('analysis_source_sha') and run.state['analysis_source_sha'] != source['sha256']:
            return ('pause', 'analysis_source_changed', 'The source bytes changed after analysis.',
                    'Start a new run for the changed source; previous analysis and approvals cannot be reused.')
        binding = content_hash({'source_sha256': source['sha256'], 'analysis': payload})
        run.state['scene_review_policy'] = 'removed'
        note = 'Scene review is disabled: scene descriptions were not independently reviewed; technical checks remain enforced.'
        if note not in run.notes:
            run.notes.append(note)
        bp = None
        try:
            bp = self.s.analysis.get(bp_id)
            prior_binding = bp.provenance.get('autorun_analysis_hash')
            manual_bound=(scene_review.manual_verified(run,source['sha256'])
                and run.state['manual_scene_review']['blueprint_hash']==bp.content_hash
                and bp.status=='accepted')
            if not manual_bound and prior_binding != binding and not (not prior_binding and
                    checks.legacy_observations_match(bp, payload, source['sha256'])):
                bp = None
            if bp is not None and bp.status == "accepted":
                if manual_bound:
                    # Refresh only the derived-analysis revision link. The
                    # user already accepted these exact unchanged bytes.
                    self.s.blueprints.accept(bp.id,bp.content_hash,
                        run.state['manual_scene_review']['reviewer'],allow_flags=True,
                        notes='Rebound unchanged manually accepted blueprint after derived-analysis refresh.')
                else:
                    # Identical observations can outlive their derived
                    # analysis revision when another run uses the seed.
                    # Revalidate the current evidence and refresh its link;
                    # content equality alone does not prove that link current.
                    self.s.blueprints.prepare_automatically(bp.id, bp.content_hash)
                run.state.pop('analysis_reset', None)
                run.state["blueprint_id"] = bp_id
                self._advance(run, "template")
                return "next"
        except ContractError:
            pass
        payload = copy.deepcopy(payload)
        try:
            if bp is None:
                bp = self.s.analysis.import_observations(
                    run.seed_id, payload, AUTO_REVIEWER,
                    provenance={'autorun_analysis_hash': binding, 'autorun_id': run.id,
                                'scene_review_policy': 'removed', 'review_performed': False})
            # Building the new draft fulfils the reset. Acceptance is a
            # separate durable decision and must survive a worker restart.
            run.state.pop('analysis_reset', None)
            run.state['blueprint_id'] = bp.id
            self._put(run)
        except ContractError as e:
            return ("pause", "analysis_invalid",
                    f"blueprint construction refused the analysis: "
                    f"{e.code} {e.detail}",
                    "Correct the beats/observations in the Analysis "
                    "tab, then Resume — or settle the analysis hold and "
                    "Resume to buy a fresh analysis")
        self.s.blueprints.prepare_automatically(bp.id, bp.content_hash)
        run.state.pop('analysis_reset', None)
        run.state["blueprint_id"] = bp.id
        self._advance(run, "template")
        return "next"

    def _stage_template(self, run):
        tpl_id = run.state.get("template_id") or f"tpl-{run.id}"
        try:
            tpl = self.s.templates.get(tpl_id)
        except ContractError:
            bp = self.s.analysis.get(run.state["blueprint_id"])
            tpl = self.s.templates.author(bp, tpl_id, renderer_policy=(run.params.get('flashcut_policy') or {}).get('renderer'))
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
        if run.params.get('source_timing_policy') == 'source_timing.v1':
            from .source_timing import LocalTimingRepair, SourceTimingService
            source = self.s.seeds.get(run.seed_id)
            path = self.s.artifacts.verified_path(source.source_asset_id)
            artifact = self.s.db.uow().artifacts.get(source.source_asset_id)
            repair = LocalTimingRepair(path, self.s.config.get('source_timing_local_url', 'http://127.0.0.1:8765'))
            if self.s.config.get('mode', 'offline') != 'live':
                # Offline execution never reaches a real local model or port.
                repair = getattr(self.s, 'source_timing_repair', lambda *args: [])
            def progress(receipt):
                run.state['source_timing'] = receipt
                self._put(run)
            timing = SourceTimingService(self.s.db, repair, progress)
            try:
                result = timing.review(run.id, artifact['sha256'], transcript, beats,
                    self.s.ref_analysis.get(run.seed_id).acquisition['duration_s'],
                    run.state.get('source_language') or 'en')
                run.state['source_timing'] = result
                transcript = result['transcript']
                self._put(run)
            except ContractError as error:
                if error.code != 'source_timing_unreliable': raise
                from .source_timing import POLICY
                binding = content_hash({'source':artifact['sha256'], 'transcript':transcript,
                    'policy':POLICY, 'language':run.state.get('source_language') or 'en'})
                run.state['source_timing'] = timing.receipt(run.id, binding)
                self._put(run)
                return ('pause', error.code, error.detail, 'Restore reliable source transcript timing, then Resume. No scene review or paid retry will run.')
        src_lang = (run.state.get("source_language") or
                    "").split("-")[0].lower()
        out_lang = (run.params.get("language") or "en") \
            .split("-")[0].lower()
        if transcript and src_lang and src_lang != out_lang:
            # Source and output languages differ: translation is an
            # explicit, receipted stage — never an English re-transcript
            # or invented copy.
            adapter = self.s.providers.get("audiovisual_analysis")
            if adapter is None or not getattr(adapter, "account", ""):
                return ("pause", "capability_unavailable",
                        f"source language is {src_lang} but narration is "
                        f"{out_lang} — translation needs the analysis "
                        "route",
                        "Configure the provider, or Resume with "
                        f"set_params language={src_lang} to keep "
                        "source-language narration")
            if not run.state.get("translation"):
                out = self._run_effect(
                    run, "analysis", "audiovisual_analysis",
                    adapter.model, [{
                        "task": "translate", "model": adapter.model,
                        "translation_input": {
                            "source_language": src_lang,
                            "target_language": out_lang,
                            "passages": [
                                {"index": i, "text": t["text"]}
                                for i, t in enumerate(transcript)]}}],
                    "translate")
                if out != "wait":
                    return out
                res = self._jobs(run, run.state["translate_jobs"],
                                 "translation_failed")
                if res != "next":
                    return res
                cmd = self.s.commands.get(run.state["translate_jobs"][0])
                texts = (cmd["command"]["result"]["result"]
                         .get("translation") or {}).get("texts") or {}
                if any(str(i) not in texts
                       or not str(texts[str(i)]).strip()
                       for i in range(len(transcript))):
                    return ("pause", "translation_incomplete",
                            "the translation response did not cover "
                            "every source passage",
                            "Resume to retry once, or supply an aligned "
                            "transcript in the output language")
                run.state["translation"] = texts
                run.notes.append(
                    f"translated {len(texts)} transcript passages "
                    f"{src_lang}→{out_lang} (paid analysis route)")
                self._put(run)
            transcript = [{**t,
                           "text": run.state["translation"][str(i)]}
                          for i, t in enumerate(transcript)]
        base = scripts.adapt(beats, transcript)
        for warning in base.get('timing_warnings') or []:
            if warning not in run.notes:
                run.notes.append(warning)
        if base.get("unplaced"):
            run.notes.append(
                f"{len(base['unplaced'])} transcript passage(s) could "
                "not be assigned to any beat — excluded from copy, "
                "visible here for audit")
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
                if isinstance(res, tuple) and not run.params.get('workflow'):
                    # A Resume after this pause uses the deterministic
                    # adaptation instead of re-dispatching the dead job.
                    run.state["script_llm_failed"] = True
                    self._put(run)
                return res
            cmd = self.s.commands.get(run.state["script_jobs"][0])
            llm = cmd["command"]["result"]["result"].get("script")
            if run.params.get('workflow'):
                from ..analysis.scripts import validate_script_response
                validate_script_response(llm, [b['id'] for b in beats], base['changed'])
            merged, over = self._merge_llm_scripts(base, llm, beats)
            if merged is None and any(n[-1] == "rewrite_required" for n in over):
                # The first request completed; this is a separately quoted
                # bounded copy rewrite, never a replay of an unknown attempt.
                repair = scripts.llm_request(adapter.model, beats, transcript,
                                             base["A"], base["changed"])
                repair["script_input"]["previous_script"] = llm
                repair["script_input"]["rewrite_feedback"] = [
                    {"variant": key, "beat": bid, "max_words": budget,
                     "instruction": "Rewrite as a complete shorter sentence."}
                    for key, bid, words, budget, action in over
                    if action == "rewrite_required"]
                out = self._run_effect(run, "analysis", "audiovisual_analysis",
                                       adapter.model, [repair], "script_repair")
                if out != "wait":
                    return out
                result = self._jobs(run, run.state["script_repair_jobs"],
                                    "script_repair_failed")
                if result != "next":
                    return result
                cmd = self.s.commands.get(run.state["script_repair_jobs"][0])
                merged, over = self._merge_llm_scripts(
                    base, cmd["command"]["result"]["result"].get("script"), beats)
                if merged is None:
                    return ("pause", "script_repair_failed",
                            "The bounded rewrite did not produce complete in-budget copy",
                            "Correct the script adaptation before narration; no automatic repeat request")
            for key, beat_id, words, budget, action in over:
                run.notes.append(
                    f"variant {key} beat {beat_id}: generated copy "
                    f"({words} words) exceeds the beat's word budget "
                    f"({budget}); {action}")
            if merged is None:
                if run.params.get('workflow'):
                    return ('pause', 'invalid_script_response',
                            'Script copy is incomplete or malformed. No draft or narration was created.',
                            'Correct the saved script response and reconcile its original operation; Resume never silently selects fallback copy.')
                run.state["script_llm_failed"] = True
                self._put(run)
                return ("pause", "script_failed",
                        "script adaptation returned unusable output",
                        "Resume to use the deterministic adaptation")
            chosen, chosen_mode = merged, "llm"
        else:
            chosen, chosen_mode = base, "template"
            if run.state.get("script_llm_failed"):
                run.notes.append(
                    "script adaptation fell back to deterministic "
                    "templates after the LLM attempt failed")
            elif mode == "llm":
                run.notes.append(
                    "script adaptation fell back to deterministic "
                    "templates — no analysis provider configured")
        # The experiment contract is enforced before anything is stored:
        # a variant whose changed copy is normalization-equivalent to the
        # control is not a variation — that limitation is reported, never
        # silently shipped as an identical variant.
        problems = scripts.validate_variations(chosen, beats)
        if problems:
            self._put(run)
            return ("pause", "variation_missing",
                    "; ".join(problems),
                    "Fix the adaptation (edit observations or provide "
                    "LLM output that actually differs) — the run does "
                    "not produce identical variants silently")
        run.state["scripts"] = chosen
        run.state["script_mode"] = chosen_mode
        self._put(run)
        self._advance(run, "music" if run.params["generate_music"]
                      or run.params.get("music_artifact_id")
                      else "draft")
        return "next"

    def _merge_llm_scripts(self, base, llm, beats):
        """Apply an LLM adaptation only where it stays inside the
        declared treatment shape; anything else is rejected wholesale."""
        from ..analysis.scripts import validate_script_response
        try:
            validate_script_response(llm, [b['id'] for b in beats], base['changed'])
        except ContractError:
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
            words = str(text).split()
            if len(words) <= budget:
                return str(text)
            # Never purchase a waveform for a mid-sentence word slice.
            if key == "A" and str(fallback).strip():
                over.append((key, beat_id, len(words), budget,
                             "source-derived copy used instead"))
                return fallback
            sentences = re.findall(r'[^.!?]+[.!?]+(?:["\u201d\u2019])?', str(text))
            retained = []
            for sentence in sentences:
                if len(" ".join(retained + [sentence.strip()]).split()) > budget:
                    break
                retained.append(sentence.strip())
            if retained:
                over.append((key, beat_id, len(words), budget,
                             "retained complete sentences within word budget"))
                return " ".join(retained)
            if (str(fallback).strip() and len(str(fallback).split()) <= budget
                    and scripts._norm_words(fallback) != scripts._norm_words(base["A"].get(beat_id, ""))):
                over.append((key, beat_id, len(words), budget,
                             "source-derived treatment used instead"))
                return fallback
            over.append((key, beat_id, len(words), budget,
                         "rewrite_required"))
            return ""
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
        return (None if any(n[-1] == "rewrite_required" for n in over) else out), over

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
        from ..analysis.deep import bound_gate
        try:
            bound_gate(self.s.db, bp.seed_id,
                       bp.provenance.get('artifact_sha256', ''), bp.analysis)
        except ContractError as error:
            if error.code != 'analysis_stale':
                raise
            # Resume an already-paused repeat-seed run without buying its
            # analysis or script again. Blueprint preparation retains the
            # source/hash guards and validates current structural evidence.
            self._advance(run, 'blueprint')
            return 'next'
        sc = run.state["scripts"]
        provider, model = self._generation_route(run)
        gen_settings = self._generation_settings(provider, model)
        from .policies import run_policies
        policies = run_policies(run.params)
        full_video = policies['variation'] == 'full_video'
        continuity = ' Continuity reference for this entire video: ' + ' | '.join(str(b.visual_event) for b in bp.beats)
        context = None
        if run.params.get('workflow'):
            from ..creative.context import from_analysis, scene_request
            context = from_analysis(run.state.get('analysis') or {}, bp.beats)
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
        if 'policies' in run.params:
            for seg in segments:
                seg['picture']['request']['prompt'] += (
                    ' No subtitles, captions, title cards, decorative lettering, logos or watermarks.'
                    ' Text will be added separately after footage checks.' + continuity)
        variants = []
        if context:
            for seg in segments:
                seg['picture']['request'] = scene_request(context, seg['id'], 'A', gen_settings)
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
                if full_video:
                    beat = next(b for b in bp.beats if b.id == seg['id'])
                    s2['picture']['request'] = scripts.variant_picture_request(
                        {'visual_event': beat.visual_event, 'role': beat.role},
                        key, gen_settings)
                    s2['picture']['request']['prompt'] += continuity
                if context:
                    s2['picture']['request'] = scene_request(context, seg['id'], key if full_video or seg['id'] == changed_id else 'A', gen_settings)
                branch_segments.append(s2)
            region = next(b.target.to_dict() for b in bp.beats
                          if b.id == changed_id)
            if full_video:
                region = {'start_frame': 0, 'end_frame': bp.target_frames}
            variants.append({
                "key": key, "factor": sc["factors"][key],
                "regions": [region],
                "segments": branch_segments,
                "hypothesis": sc["hypotheses"][key],
                "primary_metric": sc["metrics"][key],
                "allowed_fields": ["copy", "speech", "captions",
                                   "picture"]})
        eid = f"exp-{run.id}"
        # One output profile is frozen at draft creation — every variant
        # renders to the same canvas, and technical QC validates exports
        # against this declaration, never against whichever input frame
        # happened to be first.
        try:
            ow, oh = scripts.output_dims(gen_settings["aspect"],
                                         gen_settings["resolution"])
        except ContractError as e:
            return ("pause", "draft_failed",
                    f"cannot declare an output profile: {e.code} "
                    f"{e.detail}",
                    "Choose a generation route with a known aspect/"
                    "resolution, then Resume")
        body = {
            "blueprint_id": run.state["blueprint_id"],
            "template_id": run.state["template_id"],
            "segments": segments, "variants": variants,
            "output_profile": {"width": ow, "height": oh,
                               "fps": bp.clock.num / bp.clock.den,
                               "aspect": gen_settings["aspect"],
                               "resolution": gen_settings["resolution"]},
            "voice": {"id": run.params["voice_id"], "model": "eleven_v3",
                      "settings": {"language":
                                   run.params["language"]}},
            "music": run.state.get("music") or {"role": "bed"},
            "provider_policy": {"choice": provider,
                                "allowed_models":
                                {self._provider_name(provider): [model]}
                                if model else {}},
            "product_ids": []}
        if 'policies' in run.params:
            body['run_policies'] = policies
        if 'workflow' in run.params:
            body['workflow'] = run.params['workflow']
            body['creative_context'] = context
        if run.state.get('source_timing'):
            body['source_timing'] = {key:run.state['source_timing'][key] for key in
                ('policy','binding','source_sha256','transcript_hash')}
        if run.params.get('flashcut_policy'):
            body['flashcut_policy'] = run.params['flashcut_policy']
            body['flashcut_editorial'] = {'version': 'flashcut_editorial.v1',
                'evidence_sha256': self.s.source_evidence.get(run.state['source_evidence_id'])['manifest']['sha256'],
                'understanding': run.state['flashcut_understanding']}
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
        base = run.state.get("scripts_base") or {}
        bp = self.s.analysis.get(run.state["blueprint_id"])
        fps = bp.clock.num / bp.clock.den
        # Synthesis is bought once per normalized text, but fitting and
        # attachment are per occurrence — every segment that speaks the
        # line gets its own speech record, target interval and captions.
        needed = {}
        over_budget = []
        for key in "ABCD":
            variant = self.s.experiments._variant(eid, key)
            for seg in variant.segments:
                text = str(seg.get("copy") or "").strip()
                if not text:
                    continue
                norm = self.s.audio_work.speech.normalize(text)
                needed.setdefault(norm, []).append(
                    (key, seg["id"], text))
                # Pre-spend feasibility: a line provably over its beat's
                # word budget is never synthesized — the measured fit
                # stays authoritative for everything inside the bound.
                target = seg.get("target") or {}
                target_s = (target.get("end_frame", 0) -
                            target.get("start_frame", 0)) / fps
                budget = scripts.word_budget(
                    {"target_s": target_s},
                    (base.get("A") or {}).get(seg["id"], ""))
                if len(text.split()) > budget:
                    over_budget.append((key, seg["id"], text, budget))
        if over_budget:
            repaired = self._repair_overlong(
                run, needed, over_budget, base)
            if repaired == "next":
                return "next"
            if repaired:
                return repaired
            return ("pause", "speech_fit_failed",
                    "; ".join(f"{k}:{s} copy is {len(t.split())} words, "
                              f"beat allows ~{b}" for k, s, t, b
                              in over_budget),
                    "Edit the draft copy so it fits its beat, then "
                    "Resume — the run continues on the new revision")
        if not needed:
            run.notes.append("silent scripts — no narration required")
            run.state["tts_done"] = True
            self._advance(run, "quote")
            return "next"
        if not run.state.get("tts_synth_jobs"):
            # Speech already synthesized for this voice under an earlier
            # revision is reused by normalized text — a copy edit to one
            # beat must not re-buy every other line. Reuse requires the
            # stored attempt's request to be identical in every identity
            # input — text, voice, model, language — not just the same
            # normalized key.
            history = run.state.setdefault("tts_synth_history", {})
            reuse = {n: j for n, j in history.items() if n in needed and
                     (self.s.db.uow().jobs.get(j) or {}).get("status")
                     == "succeeded" and
                     self._synth_job_matches(j, needed[n][0][2], run)}
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
                    prior = self.s.db.uow().jobs.get(fits[fkey]) or {}
                    if prior.get("status") == "succeeded":
                        continue
                    retried = run.state.setdefault("tts_fit_retried", [])
                    if prior.get("status") in ("failed", "blocked") \
                            and fkey not in retried:
                        # One retry after a fit-policy fix, reusing the
                        # paid waveform. A second failure pauses.
                        retried.append(fkey)
                        fits.pop(fkey, None)
                    else:
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
            if any(code in str(res[2]) for code in ('caption_', 'alignment', 'word_times_not_monotonic')):
                return ('pause', 'caption_timing_unreliable', res[2],
                        'Restore reliable word timing for the final replacement narration and verify complete text coverage within this beat. '
                        'For an overlong caption word, revise that word instead of shrinking the text. Then Resume; existing audio is retained.')
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

    def _synth_job_matches(self, jid, text, run):
        """Reuse is safe only when the paid request was identical in
        every identity input — text, voice, model, language — not merely
        the same normalized key."""
        from ..execution.effects import wire_hash
        request = {"text": text,
                          "voice_id": run.params["voice_id"],
                          "model": "eleven_v3",
                          "language": run.params["language"],
                          "settings": {}}
        if run.params.get('workflow'):
            # Future effects carry audit identity too. Recover the original
            # batch tag; it is not necessarily the current batch's tag after
            # one line is repaired. Never drop it from the receipt hash.
            command = self.s.commands.get(jid)['command']['input']
            plan = self.s.effect_work.get(command['plan_id'])
            operation = next((op for op in plan['operations']
                              if op['key'] == command['operation']), None)
            tag = (operation or {}).get('request', {}).get('workflow_effect', '')
            if (plan['kind'] != 'tts' or plan['provider'] != 'elevenlabs'
                    or plan['account'] != self.s.providers['elevenlabs'].account
                    or not re.fullmatch(r'tts(?:_\d+)?', tag)):
                return False
            request.update(workflow_version=2, autorun_id=run.id, workflow_effect=tag)
            if operation['request'] != request:
                return False
        want = wire_hash(request)
        rows = self.s.db.conn.execute(
            "SELECT request_hash FROM attempts WHERE job_id=?",
            (jid,)).fetchall()
        return any(r["request_hash"] == want for r in rows)

    def _repair_overlong(self, run, needed, over_budget, base):
        """Pre-spend repair: a line over its beat's word budget reverts
        to that segment's source-derived copy — on a new draft revision,
        before any synthesis is bought. Returns 'next' after a patch, a
        pause tuple when the fallback cannot help, or None to let the
        caller pause."""
        targets = []
        changed = base.get("changed") or {}
        for key, seg_id, text, budget in over_budget:
            fallback = (base.get(key) or {}).get(seg_id) \
                if key != "A" and changed.get(key) == seg_id \
                else (base.get("A") or {}).get(seg_id, "")
            if not fallback:
                return None
            if scripts._norm_words(fallback) == \
                    scripts._norm_words(text):
                return ("pause", "speech_fit_failed",
                        f"variant {key} segment {seg_id}: the source-"
                        "derived narration itself exceeds the beat's "
                        "word budget",
                        "Edit the draft copy or lengthen the beat, "
                        "then Resume")
            targets.append((key, seg_id, fallback))
        from .policies import run_policies
        maximum = run_policies(run.params)['speech_repairs']
        if maximum:
            counts = run.state.setdefault('speech_repair_attempts', {})
            for key, seg_id, _ in targets:
                if counts.get(f'{key}:{seg_id}', 0) >= maximum:
                    return ('pause', 'speech_repair_exhausted', f'{key}:{seg_id}: repair limit reached.',
                            'Edit this segment’s complete copy or beat duration, then Resume.')
            with self.s.db.uow():
                for key, seg_id, _ in targets:
                    identity = f'{key}:{seg_id}'
                    counts[identity] = counts.get(identity, 0) + 1
                self._put(run)
                return self._patch_speech(run, targets, base, measured_repair=True)
        return self._patch_speech(run, targets, base)

    def _patch_speech(self, run, targets, base, measured_repair=False):
        """Swap copy on targeted segments to their fallback text on a new
        revision bound to the LATEST draft, then rewind the TTS stage so
        only the changed lines resynthesize. A repair that would erase a
        declared variation pauses instead."""
        eid = run.state["experiment_id"]
        exp = self.s._current(eid)
        control = copy.deepcopy(exp.packaging["segments"])
        a_copy = {s["id"]: s.get("copy", "") for s in control}
        for key, seg_id, fallback in targets:
            if key != "A" and base['changed'].get(key) == seg_id and \
                    scripts._norm_words(fallback) == \
                    scripts._norm_words(a_copy.get(seg_id, "")):
                return ("pause", "variation_lost",
                        f"variant {key} segment {seg_id}: the only "
                        "fitting fallback is identical to the control — "
                        "the declared variation cannot be preserved",
                        "Edit the draft copy, then Resume")
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
        repairs = run.state.setdefault("tts_repairs", [])
        for key, seg_id, fallback in targets:
            if not measured_repair and f"{key}:{seg_id}" in repairs:
                return ("pause", "speech_fit_failed",
                        f"variant {key} segment {seg_id}: copy still "
                        "does not fit after one automatic repair",
                        "Edit the draft copy, then Resume")
            if key == "A":
                for seg in control:
                    if seg["id"] == seg_id:
                        seg["copy"] = fallback
                        seg.pop('speech', None)
                        seg['captions'] = []
                for br in branches:
                    if base["changed"].get(br["key"]) != seg_id:
                        for seg in br["segments"]:
                            if seg["id"] == seg_id:
                                seg["copy"] = fallback
                                seg.pop('speech', None)
                                seg['captions'] = []
            else:
                for br in branches:
                    if br["key"] == key:
                        for seg in br["segments"]:
                            if seg["id"] == seg_id:
                                seg["copy"] = fallback
                                seg.pop('speech', None)
                                seg['captions'] = []
            repairs.append(f"{key}:{seg_id}")
            if measured_repair:
                run.notes.append(f'{key}:{seg_id}: measured-duration rewrite applied; unchanged speech is reused.')
            else:
                run.notes.append(
                f"variant {key} segment {seg_id}: generated copy did "
                "not fit its beat; reverted to source-derived copy and "
                "resynthesized that line only")
        try:
            result = self.s.patch_experiment_draft(
                eid, {"segments": control, "variants": branches,
                      "reason": "autorun speech-fit repair"},
                exp.revision)
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

    def _repair_speech_fit(self, run, needed, fits):
        """Bounded, meaning-preserving repair when generated copy will not
        fit its beat at the documented rate limits: swap that one segment
        back to the source-derived copy, on a new draft revision, and let
        the TTS stage resynthesize only that line. Copy that already IS the
        source-derived text cannot be shortened without changing meaning —
        that stays an honest pause. One repair per segment, ever.
        Returns 'next' after a repair, a pause tuple, or None to fall
        through to the caller's pause."""
        from .policies import run_policies
        if run_policies(run.params)['speech_repairs']:
            from .speech_repair import repair
            return repair(self, run, fits)
        base = run.state.get("scripts_base")
        if not base:
            return None
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
            targets.append((key, seg_id, fallback))
        if not targets:
            return None
        return self._patch_speech(run, targets, base)

    def _stage_quote(self, run):
        eid = run.state["experiment_id"]
        rev = run.state["experiment_revision"]
        if run.params.get('flashcut_policy'):
            from .editorial import prepare
            result = prepare(self, run)
            if result is not None:
                return result
        if run.params.get('workflow', {}).get('reference_policy') == 'first_clip.v1':
            from ..creative.references import prepare
            result = prepare(self, run)
            if result is not None:
                return result
        if not run.state.get("quote_job"):
            jid = self.s.commands.enqueue(
                "quote", {"experiment_id": eid, "revision": rev,
                          **({'reference_bindings': run.state['reference_bindings']} if run.params.get('workflow', {}).get('reference_policy') == 'first_clip.v1' else {})},
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
        if not account:
            return ("pause", "account_required",
                    "generation account is not configured on the "
                    "selected provider route",
                    "Enter the provider account, then Resume")
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
        from .readiness import provider_ready
        for provider in sorted(providers):
            blocked = provider_ready(self.s, provider)
            if blocked:
                return blocked
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
        # Paid failures stay terminal until explicit evidence-backed recovery.
        # A missing remote id does not prove that a request was never sent.
        for k, n in nodes.items():
            if n["kind"] != "download":
                continue
            jid = f"{plan['id']}:{k}"
            j = self.s.db.uow().jobs.get(jid)
            if not (j and j["status"] == "failed" and
                    "incomplete_submission_set" in str(
                        j["blocked_reason"] or "")):
                continue
            with self.s.db.uow() as u:
                u.conn.execute(
                    "UPDATE jobs SET status='ready',blocked_reason=NULL,"
                    "lease_owner=NULL,lease_expires=NULL WHERE id=?",
                    (jid,))
                u.conn.execute(
                    "UPDATE jobs SET status='waiting_dependencies',"
                    "blocked_reason=NULL WHERE blocked_reason LIKE ? "
                    "AND status='blocked'",
                    (f"%{jid}%",))
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
                # A zero repair allowance disables regeneration, not QC.
                # Records without a policy keep the legacy review path.
                if run.params.get('policies'):
                    from .overlay import inspect
                    overlay = inspect(self, run, plan, pic, download, index, art)
                    if overlay:
                        return overlay
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

    def _finish_or_deliver(self, run):
        from .policies import run_policies
        if run_policies(run.params)['delivery'] != 'after_qc':
            self._finish(run)
            return 'next'
        if not run.params.get('visual_reviews', True):
            return ('pause', 'visual_qc_required', 'Automatic delivery requires final visual QC.',
                    'Enable final visual QC and Resume; delivery cannot bypass it.')
        if self.s.config.get('drive_folder_id') != run.params.get('delivery_folder_id'):
            return ('pause', 'destination_changed', 'The authorized Drive destination changed.',
                    'Restore the run’s authorized destination before resuming.')
        account = getattr(self.s.delivery.drive, 'expected_account', '') or ('fixture-drive' if self.s.config.get('mode','offline') == 'offline' else '')
        if run.params.get('workflow') and account != run.params.get('delivery_account'):
            return ('pause', 'delivery_account_changed', 'The authorized Drive account changed.',
                    'Reconnect the original authorized account; no replacement upload will be attempted.')
        run.state['completion_phases'] = {'generation': 'complete', 'qc': 'complete', 'delivery': 'running'}
        self._put(run)
        finals = self._finals(run)
        jobs = run.state.setdefault('delivery_jobs', {})
        recovery = run.state.pop('delivery_recovery_requested', False)
        for key, final in finals.items():
            if key in jobs:
                old_job = self.s.db.uow().jobs.get(jobs[key].get('job_id', ''))
                if not recovery or not old_job or old_job['status'] not in ('failed','blocked'):
                    continue
            checks = [r['id'] for r in self.s._final_checks(final)
                      if r.get('binding') == final.get('binding') and not r.get('invalidated_by')]
            result = self.s.deliver_variant(run.experiment_id + ':' + key.lower(), {
                'artifact_id': final['artifact_id'], 'target_hash': final['sha256'],
                'folder_id': run.params['delivery_folder_id'],
                'account': run.params['delivery_account'], 'reviewer': 'automatic-policy.v1',
                'valid_until': run.params['valid_until'], 'check_ids': checks,
            }, run.state['experiment_revision'])
            jobs[key] = result
            self._put(run)
        pending = [r['job_id'] for r in jobs.values() if r.get('job_id')]
        if pending:
            result = self._jobs(run, pending, 'delivery_failed')
            if result != 'next':
                return result
        for key, final in finals.items():
            rows = self.s.db.conn.execute("SELECT body FROM records WHERE kind='delivery' AND json_extract(body,'$.file_sha256')=? AND json_extract(body,'$.variant_plan_id')=?", (final['sha256'], run.experiment_id + ':' + key.lower())).fetchall()
            verified = []
            for row in rows:
                record = json.loads(row[0])
                try:
                    clean = json.loads(record.get('cleanup_receipt', '{}')).get('state') == 'verified'
                except (ValueError, TypeError):
                    clean = False
                if record['status'] == 'verified' and clean and record['parent_folder_id'] == run.params['delivery_folder_id']:
                    if run.params.get('workflow'):
                        self.s.delivery._account_binding(record)
                    verified.append(record)
            if len(verified) != 1:
                return ('pause', 'delivery_unverified', f'{key}: verified upload and cleanup receipt unavailable.',
                        'Reconcile the existing delivery; do not upload a duplicate.')
        run.state['completion_phases']['delivery'] = 'complete'
        run.notes.append('All four finals verified on Drive and video-owned resources cleaned up. Nothing published.')
        self._advance(run, 'done')
        return 'next'

    def _recompute_failed_region_checks(self, run, plan, finals):
        """Re-run automated changed-region checks that failed, so a
        QC-policy fix can take effect without regenerating paid footage."""
        control = finals.get("A")
        if not control:
            return
        try:
            apath = self.s.artifacts.verified_path(control["artifact_id"])
        except (ContractError, KeyError, TypeError):
            return
        a_mix_id = (control.get("mix") or {}).get("artifact_id")
        a_audio = self.s.artifacts.verified_path(a_mix_id) if a_mix_id else None
        fps = 30
        clock = (plan.get("output_clock") if isinstance(plan, dict) else None) \
            or {}
        if clock.get("num") and clock.get("den"):
            fps = clock["num"] / clock["den"]
        eid = run.state["experiment_id"]
        for key in "BCD":
            f = finals.get(key)
            if not f:
                continue
            check = next((c for c in f.get("check_ids") or []
                          if str(c).startswith("regions-")), None)
            if not check:
                continue
            rev = self.s.quality._get(check)
            if not rev or rev.get("verdict") == "pass" or \
                    rev.get("reviewer_type") != "automated":
                continue
            variant = self.s.experiments._variant(eid, key)
            regions, cursor = [], 0
            for region in sorted(variant.allowed_regions,
                                 key=lambda r: r.start):
                if region.start > cursor:
                    regions.append({"start_frame": cursor,
                                    "end_frame": region.start})
                cursor = max(cursor, region.end)
            if cursor < variant.target_frames:
                regions.append({"start_frame": cursor,
                                "end_frame": variant.target_frames})
            full_video = None
            if self.s._current(eid).packaging.get('run_policies', {}).get('variation') == 'full_video':
                from ..quality.variation import full_video_evidence
                full_video, regions = full_video_evidence(self.s, plan, variant)
            try:
                path = self.s.artifacts.verified_path(f["artifact_id"])
            except (ContractError, KeyError, TypeError):
                continue
            b_mix_id = (f.get("mix") or {}).get("artifact_id")
            b_audio = self.s.artifacts.verified_path(b_mix_id) \
                if b_mix_id else None
            self.s.quality.check_regions(
                check, apath, path, regions, fps,
                binding=f.get("binding"), a_audio=a_audio,
                b_audio=b_audio, full_video=full_video)

    def _mandatory_qc(self, run, plan, finals):
        """Every check recorded against a final must pass against the
        CURRENT bytes, composition and plan. Missing, stale, failed or
        unbound checks are actionable problems — a file existing is not
        validation. → list of (message, superseded) where superseded
        marks problems that disappear when the final is re-rendered
        under the current plan."""
        problems = []
        for key in "ABCD":
            f = finals.get(key)
            if not f:
                problems.append((f"{key}: no final export", False))
                continue
            problems += self.s.final_problems(key, f, plan["id"])
        return problems

    def _rewind_for_current_draft(self, run, plan, keys):
        """Discard plan-bound production state AND re-arm the compose
        nodes so the run re-renders the current revision. Without the
        job reset the completed DAG is reused verbatim — the recorded
        final would keep its unchecked bytes and the gate would rewind
        forever. Finals rendered under the old plan stay in the ledger;
        they simply stop being the run's answer."""
        for key in ("quote_job", "plan_id", "authorize_job", "run_job",
                    "production_jobs", "qc_submitted", "qc_resubmitted",
                    "qc_rechecks", "qc_flagged", "qc_human_accepted", "delivery_jobs", "completion_phases"):
            run.state.pop(key, None)
        for key in list(run.state):
            if key.startswith("qc_verdict_") or (
                    key.startswith("qc_") and key.endswith(
                        ("_jobs", "_plan", "_auth"))):
                run.state.pop(key, None)
        nodes = self.s.production._nodes(plan["id"])
        with self.s.db.uow() as u:
            for nkey, n in nodes.items():
                if n["kind"] != "compose":
                    continue
                if keys and n.get("consumers") and \
                        n["consumers"][0] not in keys:
                    continue
                u.conn.execute(
                    "UPDATE jobs SET status='ready',lease_owner=NULL,"
                    "lease_expires=NULL,next_attempt_at=NULL,"
                    "blocked_reason=NULL WHERE id=? AND "
                    "status='succeeded'",
                    (f"{plan['id']}:{nkey}",))
        run.state["final_qc_rewinds"] = \
            run.state.get("final_qc_rewinds", 0) + 1
        run.stage = "quote"
        run.notes.append(
            "finals invalidated — re-rendering the current revision "
            "from the pipeline's own build output (foreign or stale "
            "bytes can never carry the run's checks)")
        self._put(run)

    def _stage_final_qc(self, run):
        eid = run.state["experiment_id"]
        finals = self._finals(run)
        if len(finals) < 4:
            return "wait"
        try:
            plan = self.s.plan_for(eid)
        except ContractError as e:
            return ("pause", "final_qc_blocked",
                    f"no current production plan: {e.code}",
                    "Resume to re-quote the current draft")
        self._recompute_failed_region_checks(run, plan, finals)
        problems = self._mandatory_qc(run, plan, finals)
        if problems:
            current = [m for m, sup in problems if not sup]
            stale_keys = {m.split(":", 1)[0] for m, sup in problems
                          if sup}
            if not current and \
                    run.state.get("final_qc_rewinds", 0) < 3:
                # Every problem is staleness a fresh render resolves —
                # superseded plan or bytes that diverge from what the
                # checks bound. Bounded: a final that still cannot be
                # validated after re-rendering pauses for the operator.
                self._rewind_for_current_draft(run, plan, stale_keys)
                return "next"
            return ("pause", "final_qc_blocked",
                    "mandatory checks did not all pass on the current "
                    "finals: " + " | ".join(m for m, _ in problems[:8]),
                    "Inspect the failing checks in Compare, fix the "
                    "cause, then Resume — a final existing on disk is "
                    "not validation")
        if not run.params.get("visual_reviews", True):
            run.notes.append(
                "automated visual QC was disabled for this run — finals "
                "passed technical checks only (mandatory technical and "
                "unchanged-region checks, no creative review)")
            return self._finish_or_deliver(run)
        if run.state.get("qc_human_accepted"):
            return self._finish_or_deliver(run)
        adapter = self.s.providers.get("audiovisual_analysis")
        if adapter is None or not getattr(adapter, "account", ""):
            # Visual QC was requested — an unavailable route is a missing
            # capability, not a note to quietly absorb.
            return ("pause", "capability_unavailable",
                    "visual QC was requested but the audiovisual "
                    "analysis route is not configured",
                    ("Restore the configured visual-QC provider, then Resume. This run’s QC policy cannot be downgraded."
                     if run.params.get('workflow') else "Configure the provider, or Resume with set_params visual_reviews=false to finish on technical checks only"))
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
                          f"qc_{key}_auth", f"qc_verdict_{key}"):
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
                if run.params.get('workflow'):
                    self._begin_visual(run, key, f)
                out = self._run_effect(
                    run, "analysis", "audiovisual_analysis",
                    adapter.model, [{
                        "task": "review_final", "model": adapter.model,
                        "artifact_id": f["artifact_id"],
                        "artifact_sha256": f["sha256"],
                        "expected": {
                            **self._scene_qc_intent(run, variant),
                            **({'variation': run.params['policies']['variation']} if 'policies' in run.params else {}),
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
            if run.params.get('workflow'):
                binding, scope, request = self._visual_identity(run, key, f)
                if scope:
                    with self.s.db.uow():
                        result = self.s.quality.complete_visual(binding, scope, request, verdict,
                            notes=review.get('notes') or [], job_id=sub['job_id'],
                            review_evidence={k: review[k] for k in ('issues', 'review_media') if k in review})
                        verdict = result['verdict']
                        run.state[f'qc_verdict_{key}'] = verdict
                        self._put(run)
            elif recorded is None:
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
        return self._finish_or_deliver(run)

    def _stage_done(self, run):
        return "done"

    def _scene_qc_intent(self, run, variant):
        if not run.params.get('workflow'):
            return {}
        from ..creative.context import qc_intent
        experiment = self.s._current(run.experiment_id, run.state['experiment_revision'], True)
        context = experiment.packaging.get('creative_context')
        if not context:
            return {'policy': 'visual.v2', 'creative_context': {'evidence_quality': 'unavailable'}}
        clock = experiment.output_clock
        intent=qc_intent(context, variant.segments, clock['num'] / clock['den'])
        if experiment.packaging.get('flashcut_policy'):
            from ..analysis.editorial_events import EditorialService
            final=self._finals(run)[variant.variant_key]
            record=self.s.db.uow().records.get('editorialplan',final.get('editorial_plan_id',''))
            if not record:raise ContractError('editorial_intent_required','final_qc')
            saved=json.loads(record['body'])
            if (saved['experiment_revision']!=experiment.revision or saved['variant_key']!=variant.variant_key
                    or saved['manifest']!=final.get('editorial_manifest')):
                raise ContractError('stale_editorial_plan','final_qc')
            resolved=EditorialService(self.s.db,self.s.source_evidence.blobs.root).load(saved['id'])
            intent['editorial']={'policy':'semantic_edits.v1','manifest_sha256':saved['manifest']['sha256'],
                'final_artifact_id':final['artifact_id'],'final_sha256':final['sha256'],
                'events':[{**e,'start_s':e['start_frame']*clock['den']/clock['num'],
                           'end_s':e['end_frame']*clock['den']/clock['num']} for e in resolved['events']]}
        return intent

    def _visual_identity(self, run, key, final):
        path = self.s.artifacts.verified_path(final['artifact_id'])
        binding = self.s.quality.binding(path, final['composition_id'], final['artifact_id'])
        scope = self.s.quality.visual_scope(binding)
        request = content_hash({'run': run.id, 'variant': key, 'binding': binding,
                                'scope': scope, 'seq': run.state.get(f'qc_{key}_plan_seq', 0)})
        return binding, scope, request

    def _begin_visual(self, run, key, final):
        binding, scope, request = self._visual_identity(run, key, final)
        if scope:
            with self.s.db.uow():
                self.s.quality.begin_visual(binding, scope, request)
                self._put(run)

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
