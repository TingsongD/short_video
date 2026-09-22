"""Verified Drive delivery (F25): intent persisted before transfer;
remote verification (parent, name, size, MD5) is the only completion;
lost acks reconcile by content; failures retry transfer only.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from ..domain.errors import ContractError
from ..domain.records import Delivery


def delivery_name(experiment_label, variant, treatment, revision,
                  duration_s):
    """Descriptive delivery name: subject + variant + treatment +
    revision + duration."""
    dur = f"{duration_s:g}s" if duration_s else "final"
    return f"{experiment_label}-{variant}-{treatment}-r{revision}-" \
           f"{dur}.mp4"


def _md5(path):
    return hashlib.md5(Path(path).read_bytes()).hexdigest()


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _now():
    return datetime.now(timezone.utc).isoformat()


class DeliveryService:
    def __init__(self, db, drive, artifacts=None, effects=None, executor=None):
        from ..execution import Executor
        self.db = db
        self.effects = effects
        self.executor = executor or Executor(db)
        self.drive = drive
        self.artifacts = artifacts

    # ------------------------------------------------------ deliver --

    def deliver(self, delivery_id, final_path, name, folder_id,
                now="", variant_plan_id="", experiment_revision=0, queue_job_id=""):
        """Persist intent → reuse a verified identical remote file →
        upload → verify. Any ambiguity reconciles remote state first."""
        now = now or _now()
        sha = _sha256(final_path)
        md5 = _md5(final_path)
        size = Path(final_path).stat().st_size
        existing = self._get(delivery_id)
        if existing:
            self._account_binding(existing)
            if 'expected_account' in existing and existing.get('queue_job_id', '') != queue_job_id:
                raise ContractError('delivery_identity_conflict', 'queue_job_id', delivery_id)
            if existing.get('external_file_id'):
                raise ContractError('external_verification_only', 'delivery_id')
            if existing["file_sha256"] != sha or existing["parent_folder_id"] != folder_id or existing.get("delivery_name") != name:
                raise ContractError("delivery_identity_conflict", "delivery_id", delivery_id)
            if (existing.get('variant_plan_id', '') != variant_plan_id or
                    existing.get('experiment_revision', 0) != experiment_revision):
                raise ContractError('delivery_identity_conflict', 'revision/variant', delivery_id)
            rec = self.reconcile(delivery_id, now=now)
            # A pre-upload failure leaves no attempt: the listing proved
            # nothing remote exists, so the same final transfers again.
            if rec["status"] == "pending" and not existing.get("attempt_id"):
                return self.retry(delivery_id, final_path, now=now)
            return rec
        d = Delivery(schema_version="delivery.v1", id=delivery_id,
                     created_at=now, file_sha256=sha,
                     parent_folder_id=folder_id, status="pending",
                     variant_plan_id=variant_plan_id,
                     experiment_revision=experiment_revision)
        d.validate_or_raise()
        with self.db.uow():
            self._put(d)
            self._set(delivery_id, remote_md5=md5, drive_link="",
                      delivery_name=name, expected_size=size, source_path=str(Path(final_path).resolve()),
                      queue_job_id=queue_job_id, expected_account=getattr(self.drive, 'expected_account', ''))
        try:
            remote = self._find(folder_id, name)
        except Exception:
            self._set(delivery_id, status="failed")
            raise
        if remote and remote.get("md5") == md5:
            return self._verify(delivery_id, remote["id"], name,
                                folder_id, size, md5, now,
                                reused=True)
        if remote and remote.get("md5") not in (None, md5):
            self._set(delivery_id, status="conflict",
                      drive_file_id=remote["id"])
            return {"status": "conflict",
                    "detail": "same name, different content — "
                              "not proof of success, not overwritten"}
        if remote:
            # A match lacking a checksum is uncertain, not absent. Verify it
            # and retain the unresolved receipt rather than creating a copy.
            return self._verify(delivery_id, remote['id'], name, folder_id,
                                size, md5, now, reused=True)
        try:
            up = self._upload(delivery_id, final_path, folder_id, name)
            self._set(delivery_id, status="uploaded",
                      drive_file_id=up["id"])
        except Exception:
            # ambiguous: remote may hold the file — reconcile by content
            rec = self._find(folder_id, name)
            if rec is None:
                self._set(delivery_id, status="failed")
                raise
            return self.reconcile(delivery_id, now=now)
        return self._verify(delivery_id, up["id"], name, folder_id,
                            size, md5, now)

    def _upload(self, delivery_id, final_path, folder_id, name):
        if self.effects is None:
            raise ContractError("authority_required", "delivery")
        d = self._get(delivery_id)
        request = {"artifact_sha256": d["file_sha256"], "folder_id": folder_id,
                   "name": name, "size": d["expected_size"], "md5": d["remote_md5"]}
        aid = self.effects(request, f"delivery:{delivery_id}", "delivery", "drive", "files")
        self.executor.require_request(aid, request)
        self._set(delivery_id, attempt_id=aid)
        def upload():
            out = self.drive.upload(folder_id, final_path, name)
            return dict(out, operation_id=out["id"])
        op = self.executor.submit(aid, upload)
        return {"id": op["operation_id"]}

    def _find(self, folder_id, name):
        matches = [f for f in self.drive.list_files(folder_id) if f.get('name') == name]
        if len(matches) > 1:
            raise ContractError('ambiguous_remote_match', 'delivery',
                                'Multiple remote files match; select or resolve the duplicate before retrying')
        if matches:
            f = matches[0]
            st = self.drive.stat(f['id']) or f
            return {**f, **st}
        return None

    def _verify(self, delivery_id, file_id, name, folder_id, size,
                md5, now, reused=False):
        self._account_binding(self._get(delivery_id))
        st = self.drive.stat(file_id)
        problems = []
        if st is None:
            problems.append("stat_unavailable")
        else:
            if st.get("parent") != folder_id:
                problems.append(f"wrong_parent:{st.get('parent')}")
            if st.get("name") != name:
                problems.append(f"wrong_name:{st.get('name')}")
            if st.get("size") is None or int(st["size"]) != size:
                problems.append(f"size_mismatch:{st.get('size')}!={size}")
            remote_md5 = st.get("md5")
            if remote_md5 is None:
                problems.append("checksum_unavailable")
            elif remote_md5 != md5:
                problems.append(f"md5_mismatch:{remote_md5[:8]}"
                                f"!={md5[:8]}")
        if problems:
            self._set(delivery_id, status="uploaded",
                      cleanup_receipt=json.dumps(problems))
            return {"status": "unverified", "problems": problems}
        with self.db.uow() as u:
            d = self._get(delivery_id)
            self._account_binding(d)
            if d.get('queue_job_id'):
                # The draft may change while remote stat is in flight. Check
                # current identity again under the same write transaction as
                # the verified receipt and delivery-only queue transition.
                row = u.records.get('variantplan', d['variant_plan_id'])
                variant = json.loads(row['body']) if row else {}
                exp = u.records.get('experimentrevision', 'exp:'+variant.get('experiment_id',''))
                final = u.conn.execute('SELECT value FROM meta WHERE key=?',
                    ('final:'+d['variant_plan_id'],)).fetchone()
                final = json.loads(final[0]) if final else {}
                job = u.jobs.get(d['queue_job_id'])
                if (not exp or exp['revision'] != d['experiment_revision']
                    or variant.get('experiment_revision') != d['experiment_revision']
                    or final.get('sha256') != d['file_sha256'] or not job
                    or job['experiment_id'] != variant.get('experiment_id')
                    or job['revision'] != d['experiment_revision'] or job['phase'] != 'deliver'):
                    raise ContractError('stale_revision', 'delivery', 'The current final changed during remote verification; no delivery completion was recorded.')
            provenance = {'provenance':'external_verified'} if d.get('external_file_id') else {}
            self._set(delivery_id, status="verified",
                      drive_file_id=file_id, drive_link=self.drive.link(file_id),
                      remote_md5=md5, verified_at=now, **provenance)
            if d.get('queue_job_id'):
                u.conn.execute("UPDATE jobs SET status='succeeded',blocked_reason=NULL,updated_at=? "
                    "WHERE id=? AND phase='deliver' AND status='awaiting_review'",
                    (now, d['queue_job_id']))
            self._event(delivery_id, 'upload_verified', {'file_id':file_id, 'reused':reused})
        attempt_id = self._get(delivery_id).get("attempt_id")
        if attempt_id:
            self.executor._attach_remote(attempt_id, file_id, "succeeded", "delivery_verified")
        return {"status": "verified", "file_id": file_id,
                "link": self.drive.link(file_id), "reused": reused}

    # ------------------------------------------------------ recover --

    def reconcile_external(self, delivery_id, final_path, name, folder_id, file_id,
                           *, variant_plan_id, experiment_revision, queue_job_id=''):
        """Read-only remote verification; this path can never transfer bytes."""
        sha, md5, size = _sha256(final_path), _md5(final_path), Path(final_path).stat().st_size
        prior = self._get(delivery_id)
        if prior:
            self._account_binding(prior)
            if 'expected_account' in prior and prior.get('queue_job_id', '') != queue_job_id:
                raise ContractError('delivery_identity_conflict', 'queue_job_id', delivery_id)
            if prior.get('attempt_id'):
                raise ContractError('delivery_attempt_requires_reconciliation', 'delivery_id')
            expected = (sha, folder_id, name, file_id, variant_plan_id, experiment_revision)
            actual = tuple(prior.get(k) for k in ('file_sha256','parent_folder_id','delivery_name',
                'external_file_id','variant_plan_id','experiment_revision'))
            if actual != expected: raise ContractError('delivery_identity_conflict', 'delivery_id')
        else:
            with self.db.uow():
                self._put(Delivery(schema_version='delivery.v1', id=delivery_id, created_at=_now(),
                    file_sha256=sha, parent_folder_id=folder_id, status='pending',
                    variant_plan_id=variant_plan_id, experiment_revision=experiment_revision))
                self._set(delivery_id, delivery_name=name, external_file_id=file_id,
                    expected_size=size, remote_md5=md5, queue_job_id=queue_job_id,
                    expected_account=getattr(self.drive, 'expected_account', ''),
                    provenance='external_verification_pending', source_path=str(Path(final_path).resolve()))
        matches = [f for f in self.drive.list_files(folder_id) if f.get('name') == name]
        if len(matches) != 1 or matches[0]['id'] != file_id:
            self._set(delivery_id, status='conflict')
            return {'status':'conflict', 'detail':'Remote identity is absent or ambiguous; no upload was attempted.'}
        result = self._verify(delivery_id, file_id, name, folder_id, size, md5, _now(), reused=True)
        return {**result, 'delivery_id':delivery_id}

    def reconcile(self, delivery_id, now=""):
        """After restart/lost ack: remote state decides, never blind
        re-upload. A same-name different-content file is a conflict."""
        now = now or _now()
        d = self._get(delivery_id)
        self._account_binding(d)
        if d.get('external_file_id'):
            return self.reconcile_external(delivery_id, d['source_path'], d['delivery_name'],
                d['parent_folder_id'], d['external_file_id'], variant_plan_id=d['variant_plan_id'],
                experiment_revision=d['experiment_revision'], queue_job_id=d.get('queue_job_id',''))
        name = self._name_of(delivery_id)
        remote = self._find(d["parent_folder_id"], name)
        if remote is None:
            self._set(delivery_id, status="pending")
            return {"status": "pending", "action": "retry_transfer"}
        if remote.get("md5") == d["remote_md5"]:
            return self._verify(delivery_id, remote["id"], name,
                                d["parent_folder_id"],
                                d.get("expected_size", -1),
                                d["remote_md5"], now, reused=True)
        self._set(delivery_id, status="conflict",
                  drive_file_id=remote["id"])
        return {"status": "conflict",
                "detail": "remote name exists with different content"}

    def retry(self, delivery_id, final_path, now=""):
        """Transfer-only retry: re-uploads the SAME local final; never
        regenerates or renders anything."""
        d = self._get(delivery_id)
        if d.get('external_file_id'):
            raise ContractError('external_verification_only', 'delivery_id')
        if d["file_sha256"] != _sha256(final_path):
            raise ContractError("final_changed", "file_sha256",
                                "retry requires the identical final")
        reconciled = self.reconcile(delivery_id, now=now)
        if reconciled["status"] != "pending":
            return reconciled
        # No attempt means the first read/auth check failed before any upload.
        # An absent listing cannot prove an ambiguous upload was not accepted.
        if d.get("attempt_id"):
            return {"status": "unknown", "action": "reconcile_or_review_evidence"}
        self._set(delivery_id, retry_count=(d.get("retry_count") or 0) + 1)
        name = self._name_of(delivery_id)
        up = self._upload(delivery_id, final_path, d["parent_folder_id"], name)
        return self._verify(delivery_id, up["id"], name, d["parent_folder_id"],
                            d["expected_size"], d["remote_md5"], now or _now())

    def _account_binding(self, delivery):
        # Absence is legacy metadata, not permission to rewrite historical rows.
        if 'expected_account' in delivery and delivery['expected_account'] != getattr(self.drive, 'expected_account', ''):
            raise ContractError('delivery_account_changed', 'account', 'Reconnect the original authorized destination account before reconciling this receipt.')

    def _name_of(self, delivery_id):
        # the descriptive name travels with the intent record
        row = self.db.uow().records.get("delivery", delivery_id)
        body = json.loads(row["body"])
        return body.get("delivery_name") or body.get("name") or \
            delivery_id + ".mp4"

    def _get(self, delivery_id):
        row = self.db.uow().records.get("delivery", delivery_id)
        return json.loads(row["body"]) if row else None

    def _put(self, d):
        with self.db.uow() as u:
            u.records.put(d)

    def _set(self, delivery_id, **fields):
        row = self.db.uow().records.get("delivery", delivery_id)
        body = json.loads(row["body"])
        body.update(fields)
        with self.db.uow() as u:
            u.conn.execute(
                "UPDATE records SET body=?,status=?,updated_at=?,version=version+1 WHERE kind='delivery' AND "
                "id=? AND revision=?",
                (json.dumps(body), body.get('status',''), _now(), delivery_id, row["revision"]))

    def _event(self, delivery_id, kind, body):
        with self.db.uow() as u:
            u.events.append(f"delivery:{delivery_id}", kind, body)
