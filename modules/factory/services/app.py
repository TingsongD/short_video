"""Application service facade (F27): route handlers call these —
never generation CLIs, never another scheduler/ledger. Each method is
thin transport over the real domain services.
"""
import hashlib
import json
import mimetypes
from datetime import datetime, timezone
from pathlib import Path

from ..domain.errors import ContractError
from ..domain.records import Delivery, Review

MAX_UPLOAD_BYTES = 200 * 1024 * 1024
ALLOWED_UPLOAD_TYPES = {"mp4", "mov", "webm", "png", "jpg", "jpeg",
                        "mp3", "wav", "m4a"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _sha(b):
    return hashlib.sha256(b).hexdigest()


class FactoryServices:
    def __init__(self, db, seeds=None, experiments=None, scheduler=None,
                 artifacts=None, quality=None, delivery=None,
                 executor=None, providers=None, artifact_root=""):
        self.db = db
        self.seeds = seeds
        self.experiments = experiments
        self.scheduler = scheduler
        self.artifacts = artifacts
        self.quality = quality
        self.delivery = delivery
        self.executor = executor
        self.providers = providers or {}
        self.artifact_root = Path(artifact_root).resolve() \
            if artifact_root else None

    # --------------------------------------------------- read paths --

    def health(self):
        worker = {"paused": False, "draining": False}
        if self.scheduler:
            worker = {"paused": bool(self.scheduler.paused()),
                      "draining": bool(self.scheduler._flag("draining"))}
        return {"api": "ok", "storage": "ok", "worker": worker,
                "at": _now()}

    def providers_readiness(self):
        """Granular truth: installed/authed/catalog/tested/qualified —
        never one green flag."""
        out = {}
        for name, ad in self.providers.items():
            ready = {}
            try:
                ready = ad.readiness() if hasattr(ad, "readiness") else {}
            except Exception as e:
                ready = {"error": type(e).__name__}
            out[name] = {
                "installed": ready.get("installed", bool(ready)),
                "authenticated": ready.get("authenticated",
                                           ready.get("ok", False)),
                "catalog_visible": ready.get("catalog_visible",
                                             "models" in ready),
                "tested": ready.get("tested", False),
                "qualified": ready.get("qualified", False),
                "detail": {k: v for k, v in ready.items()
                           if k not in ("token", "key", "secret")},
            }
        return out

    def get_seed(self, seed_id):
        if not self.seeds:
            raise ContractError("not_found", "seed_id", seed_id)
        return self.seeds.get(seed_id).to_dict()

    # ------------------------------------------------- seed intake --

    def create_seed(self, url, via="api"):
        if not self.seeds:
            raise ContractError("unavailable", "seeds",
                                "seed registry not wired")
        seed, created = self.seeds.submit_url(url, via=via)
        return {"seed": seed.to_dict(), "created": created}

    def import_file(self, filename, data):
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename \
            else ""
        if ext not in ALLOWED_UPLOAD_TYPES:
            raise ContractError("bad_type", "filename",
                                f".{ext} not importable")
        if len(data) > MAX_UPLOAD_BYTES:
            raise ContractError("too_large", "size",
                                f"{len(data)} > {MAX_UPLOAD_BYTES}")
        if not self.artifacts:
            raise ContractError("unavailable", "artifacts",
                                "artifact registry not wired")
        return self.artifacts.intake_bytes(
            data, provenance="api_import",
            source_key=f"import:{_sha(data)[:16]}",
            source_detail=filename).to_dict()

    # ------------------------------------------------ experiments --

    def _record(self, kind, rid):
        """→ (logical_rev, body, row_version) or (None, None, None)."""
        row = self.db.uow().records.get(kind, rid)
        if row is None:
            return None, None, None
        body = json.loads(row["body"])
        return body.get("_rev", 0), body, row["version"]

    def _put_draft(self, kind, rid, body, expected_version=None):
        """Insert (expected_version=None) or CAS-update on row version.
        body['_rev'] is the user-facing logical revision."""
        with self.db.uow() as u:
            if expected_version is None:
                u.conn.execute(
                    "INSERT INTO records(kind,id,revision,schema_version,"
                    "status,body,created_at,updated_at,version)"
                    " VALUES(?,?,0,?,?,?,?,?,1)",
                    (kind, rid, f"{kind}.v1", body.get("status", "draft"),
                     json.dumps(body), _now(), _now()))
            else:
                cur = u.conn.execute(
                    "UPDATE records SET body=?,status=?,updated_at=?,"
                    "version=version+1 WHERE kind=? AND id=? AND "
                    "revision=0 AND version=?",
                    (json.dumps(body), body.get("status", "draft"),
                     _now(), kind, rid, expected_version))
                if cur.rowcount == 0:
                    raise ContractError("stale_revision", "revision",
                                        "draft changed concurrently")
        return body

    def create_experiment_draft(self, experiment_id, body):
        body = {**body, "status": "draft", "_rev": 0}
        self._put_draft("experiment_draft", experiment_id, body)
        return {"id": experiment_id, "revision": 0, "status": "draft"}

    def patch_experiment_draft(self, experiment_id, patch,
                               expected_revision):
        rev, body, ver = self._record("experiment_draft", experiment_id)
        if body is None:
            raise ContractError("not_found", "experiment_id",
                                experiment_id)
        if expected_revision is not None \
                and expected_revision != rev:
            raise ContractError("stale_revision", "revision",
                                f"expected {expected_revision}, "
                                f"current {rev}")
        locked = {"provider", "model", "fallback"}
        if body.get("status") != "draft" and locked & set(patch):
            raise ContractError("locked_field", "patch",
                                "submitted plans need a new revision")
        body.update(patch)
        body["_rev"] = rev + 1
        self._put_draft("experiment_draft", experiment_id, body,
                        expected_version=ver)
        return {"id": experiment_id, "revision": rev + 1}

    def quote_experiment(self, experiment_id):
        rev, body, ver = self._record("experiment_draft", experiment_id)
        if body is None:
            raise ContractError("not_found", "experiment_id",
                                experiment_id)
        items = body.get("unique_work", [])
        quote = {"experiment_id": experiment_id, "revision": rev,
                 "units": {"credits": sum(i.get("credits", 0)
                                          for i in items),
                           "usd_micros": sum(i.get("usd_micros", 0)
                                             for i in items)},
                 "unknown_charges": body.get("unknown_charges", []),
                 "line_items": items, "quoted_at": _now()}
        self._put_draft("experiment_draft", experiment_id,
                        {**body, "last_quote": quote},
                        expected_version=ver)
        return quote

    def authorize_experiment(self, experiment_id, expected_revision):
        rev, body, ver = self._record("experiment_draft",
                                      experiment_id)
        if body is None:
            raise ContractError("not_found", "experiment_id",
                                experiment_id)
        if expected_revision != rev:
            raise ContractError("stale_revision", "revision",
                                f"expected {expected_revision}, "
                                f"current {rev} — approvals bind the "
                                "exact reviewed revision")
        if "last_quote" not in body:
            raise ContractError("no_quote", "experiment_id",
                                "quote the exact revision first")
        body["status"] = "authorized"
        body["authorization"] = {"revision": rev, "at": _now()}
        self._put_draft("experiment_draft", experiment_id, body,
                        expected_version=ver)
        return {"id": experiment_id, "status": "authorized",
                "revision": rev}

    # -------------------------------------------------- run/pause --

    def run_experiment(self, experiment_id, expected_revision=None):
        rev, body, ver = self._record("experiment_draft",
                                      experiment_id)
        if body is None:
            raise ContractError("not_found", "experiment_id",
                                experiment_id)
        if body.get("status") != "authorized":
            raise ContractError("not_authorized", "experiment_id",
                                "authorize the quoted revision first")
        if expected_revision is not None \
                and expected_revision != rev:
            raise ContractError("stale_revision", "revision",
                                "plan changed since authorization — "
                                "re-quote and re-authorize")
        job_id = f"job-{experiment_id}"
        if self.scheduler:
            from ..domain.records import Job
            job = Job(schema_version="job.v1", id=job_id,
                      created_at=_now(),
                      logical_key=f"run:{experiment_id}",
                      phase="dispatch", experiment_id=experiment_id,
                      revision=rev, status="queued")
            self.scheduler.submit_plan([job])
        else:
            self._put_draft("job", job_id,
                            {"kind": "experiment_run", "_rev": 0,
                             "status": "queued",
                             "experiment_id": experiment_id})
        return {"job_id": job_id, "accepted": True}

    def pause_experiment(self, experiment_id):
        if self.scheduler:
            self.scheduler.pause()
        return {"id": experiment_id, "paused": True}

    def resume_experiment(self, experiment_id):
        if self.scheduler:
            self.scheduler.resume()
        return {"id": experiment_id, "resumed": True}

    def reconcile_job(self, job_id):
        if self.executor:
            return self.executor.reconcile(job_id)
        return {"job_id": job_id, "reconciled": "no_executor"}

    # --------------------------------------------------- variants --

    def record_review(self, variant_id, check_type, verdict,
                      target_hash, reviewer="operator", evidence_ids=(),
                      now=""):
        if not self.quality:
            raise ContractError("unavailable", "quality",
                                "quality service not wired")
        rev = Review(schema_version="review.v1",
                     id=f"rv-{variant_id}-{check_type}",
                     created_at=now or _now(), target_hash=target_hash,
                     check_type=check_type, reviewer_type="human",
                     verdict=verdict, evidence_ids=list(evidence_ids))
        rev.validate_or_raise()
        with self.db.uow() as u:
            u.records.put(rev)
        return {"id": rev.id, "verdict": verdict,
                "bound_hash": target_hash}

    def create_variant_revision(self, variant_id, reason, patch):
        rev, body, ver = self._record("variant", variant_id)
        if body is None:
            body = {"variant_id": variant_id, "status": "draft",
                    "_rev": -1}
            rev, ver = -1, None
        body.update(patch)
        body["revision_reason"] = reason
        body["_rev"] = rev + 1
        self._put_draft("variant", variant_id, body,
                        expected_version=ver)
        return {"id": variant_id, "revision": rev + 1}

    def deliver_variant(self, variant_id, final_path, name, folder_id,
                        now=""):
        if not self.delivery:
            raise ContractError("unavailable", "delivery",
                                "delivery service not wired")
        return self.delivery.deliver(f"dlv-{variant_id}", final_path,
                                     name, folder_id, now=now or _now())

    def record_publication(self, variant_id, platform, account_id):
        body = {"variant_id": variant_id, "platform": platform,
                "account_id": account_id,
                "status": "authorized_intent", "at": _now()}
        rid = f"pub-{variant_id}-{platform}"
        rev, _, _ = self._record("publication", rid)
        if rev is None:
            body["_rev"] = 0
            self._put_draft("publication", rid, body)
        return {"id": rid, "status": "authorized_intent"}

    def experiment_results(self, experiment_id):
        rev, body, _ = self._record("experiment_draft", experiment_id)
        if body is None:
            raise ContractError("not_found", "experiment_id",
                                experiment_id)
        return {"experiment_id": experiment_id, "revision": rev,
                "status": body.get("status"),
                "coverage": body.get("coverage", "unknown"),
                "results": body.get("results", [])}

    # ----------------------------------------------------- media ----

    def media_path(self, asset_id):
        """Resolve a registered artifact id to a contained local path;
        arbitrary paths/URLs are rejected by construction."""
        if not self.artifacts:
            raise ContractError("unavailable", "artifacts",
                                "artifact registry not wired")
        try:
            return Path(self.artifacts.path_for(asset_id))
        except ContractError as e:
            raise ContractError("not_found", "asset_id",
                                f"{asset_id}: {e.detail}")

    # ----------------------------------------------------- events ---

    def events_since(self, stream, seq=0, limit=500):
        return self.db.uow().events.since(stream, seq=seq)[:limit]
