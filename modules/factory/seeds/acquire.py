"""Source acquisition (F09 checklist 2–6): resolution, metadata and
media are separate scheduled jobs with individual costs and cache
policies. Every external call rides the F07 executor (intent persisted
before the effect) and F05 reservations when a cost is configured.

Failure semantics:
- image/corrupt downloads → seed needs_source_media + job fails with a
  clear reason; metadata stays useful; analysis deps stay blocked until
  a manual import verifies real video bytes
- interrupted transfer → retryable; resume retries the SAME attempt's
  download, never resubmits
- expired media URL → approved refresh path via the adapter, then a
  single pre-acceptance resubmit
- private/unsafe fetch targets are refused before any remote call
"""
import hashlib
import json

from ..domain.errors import ContractError
from ..domain.records import Job, MetricObservation
from ..store.uow import utcnow
from ..testing.fakes import ProviderError
from .registry import MEDIA_JOB_KEY, META_JOB_KEY
from .ssrf import SSRFError, assert_fetchable


class AcquisitionService:
    def __init__(self, db, scheduler, executor, registry, artifacts,
                 adapter, adapter_name, budget=None, costs=None,
                 metadata_ttl_s=3600, staging_dir=None, resolver=None, effects=None):
        self.db = db
        self.effects = effects
        self.scheduler = scheduler
        self.executor = executor
        self.registry = registry
        self.artifacts = artifacts
        self.adapter = adapter
        self.adapter_name = adapter_name
        self.budget = budget
        self.costs = costs or {}
        self.metadata_ttl_s = metadata_ttl_s
        self.staging_dir = staging_dir
        self.resolver = resolver

    # ----------------------------------------------------------- plan

    def plan(self, seed_id, experiment_id="", suffix=""):
        """Two jobs: metadata → media. Idempotent per suffix; a non-empty
        suffix creates a re-resolution pass (e.g. scheduled refresh, which
        may still hit the metadata cache). Downstream analysis jobs attach
        depends_on=[media_job_id] themselves."""
        seed = self.registry.get(seed_id)
        meta_key = META_JOB_KEY.format(seed.id) + suffix
        media_key = MEDIA_JOB_KEY.format(seed.id) + suffix
        with self.db.uow() as u:
            existing_meta = u.jobs.by_logical_key(meta_key)
            existing_media = u.jobs.by_logical_key(media_key)
        if existing_meta and existing_media:
            return existing_meta["id"], existing_media["id"]
        meta = Job(schema_version="job.v1",
                   id=f"job-seedmeta-{seed.id}{suffix}",
                   created_at=utcnow(),
                   logical_key=meta_key, phase="seed",
                   experiment_id=experiment_id)
        media = Job(schema_version="job.v1",
                    id=f"job-seedmedia-{seed.id}{suffix}",
                    created_at=utcnow(),
                    logical_key=media_key,
                    phase="seed", experiment_id=experiment_id,
                    depends_on=[meta.id])
        self.scheduler.submit_plan([meta, media])
        return meta.id, media.id

    # ------------------------------------------------------------ run

    def run_next(self):
        """Claim one eligible dispatch job and execute it. Returns the
        job id worked, or None."""
        job = self.scheduler.claim("dispatch")
        if job is None:
            return None
        key = job["logical_key"]
        try:
            if key.startswith("seed_metadata:"):
                self._do_metadata(job)
            elif key.startswith("seed_media:"):
                self._do_media(job)
            else:
                self.scheduler.fail(job["id"], job["fencing_token"],
                                    f"unhandled acquisition job {key}")
                return job["id"]
        except ProviderError as e:
            transient = getattr(e, "transient", False)
            self.scheduler.fail(job["id"], job["fencing_token"],
                                f"{e.code}", retryable=transient)
            if not transient:
                raise
            return job["id"]
        except (ContractError, SSRFError) as e:
            self.scheduler.fail(job["id"], job["fencing_token"],
                                f"{e.code}", retryable=False)
            raise
        self.scheduler.complete(job["id"], job["fencing_token"])
        return job["id"]

    # ------------------------------------------------------ metadata

    def _do_metadata(self, job):
        seed_id = job["logical_key"].split(":")[1]
        seed = self.registry.get(seed_id)
        if self._fresh(seed):
            with self.db.uow() as u:
                u.events.append(f"job:{job['id']}", "cache_hit",
                                {"field": "metadata"})
            return
        request = {"kind": "metadata", "post_id": seed.native_id,
                   "platform": seed.platform, "seed_id": seed.id}
        aid, phase = self._resume_or_prepare(job, request, "seed_metadata")
        if phase == "submit":
            res = self._reserve("metadata", request)
            try:
                op = self.executor.submit(
                    aid, call=lambda: self.adapter.submit(request))
            except Exception:
                self._release(res, "metadata_submit_failed")
                raise
            if op.get("status") == "accepted":
                op = self.executor.poll(aid)
            result = op.get("result") or {}
            self._settle(res, "metadata")
        else:
            op = self.executor.poll(aid)
            result = op.get("result") or {}
        fetched = utcnow()
        self.registry.apply_metadata(seed_id, result, fetched_at=fetched)
        stats = result.get("stats") or {}
        if stats:
            self._observe(seed_id, stats, fetched)
        return result

    def _fresh(self, seed):
        if not seed.metadata_fetched_at or not self.metadata_ttl_s:
            return False
        from datetime import datetime
        fetched = datetime.fromisoformat(
            seed.metadata_fetched_at.replace("Z", "+00:00"))
        age = (datetime.now(fetched.tzinfo) - fetched).total_seconds()
        return age < self.metadata_ttl_s

    def _observe(self, seed_id, stats, observed_at):
        obs = MetricObservation(
            schema_version="metric_observation.v1",
            id=f"obs-{seed_id}-{hashlib.sha256((seed_id + observed_at).encode()).hexdigest()[:10]}",
            created_at=observed_at, seed_id=seed_id,
            observed_at=observed_at,
            views=stats.get("views"), likes=stats.get("likes"),
            followers=stats.get("followers"),
            unknown_reason="" if stats.get("views") is not None
            else "provider_omitted",
            baseline_method="none",
            provider_score=stats.get("outlier_score"))
        with self.db.uow() as u:
            if u.records.get("metricobservation", obs.id) is None:
                u.records.put(obs)
                u.events.append(f"seed:{seed_id}", "metrics_observed",
                                {"observation_id": obs.id})

    # ---------------------------------------------------------- media

    def _do_media(self, job):
        seed_id = job["logical_key"].split(":")[1]
        seed = self.registry.get(seed_id)
        media_url = (seed.metadata or {}).get("media_url")
        if not media_url:
            self.registry.mark_needs_media(seed_id, "no_media_url")
            raise ContractError("no_media_url", "seed_id", seed_id)
        # SSRF guard: refuse unsafe fetch targets before any remote call.
        assert_fetchable(media_url, resolver=self.resolver)
        request = {"kind": "media", "post_id": seed.native_id,
                   "url": media_url, "seed_id": seed.id}
        aid, phase = self._resume_or_prepare(job, request, "seed_media")
        if phase == "submit":
            res = self._reserve("media", request)
            try:
                op, aid = self._submit_media(request, seed, aid)
            except Exception:
                self._release(res, "media_submit_failed")
                raise
            if op.get("status") == "accepted":
                op = self.executor.poll(aid)
            self._settle(res, "media")
        else:
            op = self.executor.poll(aid)
        if op.get("status") != "succeeded":
            raise ProviderError("media_not_ready", transient=True)
        dest = self._stage(aid)
        self.executor.download(aid, dest)   # transient → retryable path
        try:
            artifact = self.artifacts.intake_file(
                dest, provenance="seed_source",
                source_key=seed.canonical_url,
                source_detail=f"adapter:{self.adapter_name}",
                requested_kind="video")
        except ContractError as e:
            self.registry.mark_needs_media(
                seed_id, f"acquisition_not_video:{e.code}")
            raise
        self.registry.attach_media(seed_id, artifact.id,
                                   via="seed_source")

    def _submit_media(self, request, seed, attempt_id):
        try:
            return self.executor.submit(
                attempt_id, call=lambda: self.adapter.submit(request)), attempt_id
        except ProviderError as e:
            if e.code != "expired_source":
                raise
            # Approved refresh path through the original adapter, then a
            # single resubmit — the failure was pre-acceptance.
            fresh = self.adapter.refresh_url(seed.native_id)
            self.registry.apply_metadata(
                seed.id, {**seed.metadata, "media_url": fresh},
                fetched_at=utcnow())
            assert_fetchable(fresh, resolver=self.resolver)
            if self.costs.get("media"):
                raise ContractError("renewed_source_requires_authorization", "seed_id", seed.id)
            original = self.executor._attempt(attempt_id)
            req = {**request, "url": fresh}
            aid = self.executor.prepare(original["job_id"], original["attempt_seq"] + 1, req, kind="seed_media", route=self.adapter_name)
            return self.executor.submit(aid, call=lambda: self.adapter.submit(req)), aid

    def _stage(self, attempt_id):
        import os
        d = self.staging_dir
        os.makedirs(d, exist_ok=True) if d else None
        import tempfile
        fd, path = tempfile.mkstemp(dir=d, suffix=".part")
        os.close(fd)
        return path

    def _resume_or_prepare(self, job, request, kind):
        """Reuse an unfinished attempt (resume download/poll) instead of
        preparing a new remote effect."""
        rows = self.db.conn.execute(
            "SELECT id, status, attempt_seq FROM attempts WHERE job_id=? "
            "ORDER BY attempt_seq", (job["id"],)).fetchall()
        for r in rows:
            if r["status"] in ("unknown", "dispatching", "cancel_requested"):
                op = self.executor.reconcile(r["id"])
                if not op:
                    raise ContractError("attempt_unresolved", "attempt_id", r["id"])
                return r["id"], "resume"
            if r["status"] in ("accepted", "running", "succeeded"):
                return r["id"], "resume"
        seq = (rows[-1]["attempt_seq"] + 1) if rows else 1
        if self.costs.get("metadata" if kind == "seed_metadata" else "media"):
            if self.effects is None:
                raise ContractError("authority_required", "acquisition")
            aid = self.effects(request, job["id"], "research", self.adapter_name, kind)
            self.executor.require_request(aid, request)
        else:
            aid = self.executor.prepare(job["id"], seq, request, kind=kind, route=self.adapter_name)
        return aid, "submit"

    # ---------------------------------------------------------- money

    def _reserve(self, kind, request):
        """cfg: {"lines": [(budget_id, amount)]}. Returns reservation id
        or None. Idempotent on the request hash."""
        cfg = self.costs.get(kind)
        if not (self.budget and cfg):
            return None
        wire = json.dumps(request, sort_keys=True, default=str)
        rh = hashlib.sha256(wire.encode()).hexdigest()
        row = self.db.conn.execute("SELECT body FROM intents WHERE request_hash=? ORDER BY created_at DESC LIMIT 1", (rh,)).fetchone()
        rid = json.loads(row["body"]).get("reservation_id") if row else None
        if not rid:
            raise ContractError("reservation_required", "acquisition")
        return rid

    def _settle(self, res, kind):
        if res and self.budget:
            reserved = self.db.conn.execute("SELECT budget_id,amount FROM reservation_lines WHERE reservation_id=?", (res,)).fetchall()
            self.budget.settle(res, "native_quote", dict(reserved), evidence=f"{kind} acquisition receipt")

    def _release(self, res, evidence):
        if res and self.budget:
            proven = self.db.conn.execute("""SELECT 1 FROM attempts a JOIN events e ON e.stream='attempt:'||a.id
                WHERE json_extract(a.body,'$.reservation_id')=? AND a.status='failed'
                AND e.type='submit_failed' AND json_extract(e.body,'$.class')='pre_acceptance'""", (res,)).fetchone()
            if proven:
                self.budget.release(res, evidence=evidence)
            else:
                with self.db.uow() as u:
                    u.conn.execute("UPDATE reservations SET status='ambiguous' WHERE id=? AND status='held'", (res,))
