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
    def __init__(self, db, drive, artifacts=None):
        self.db = db
        self.drive = drive
        self.artifacts = artifacts

    # ------------------------------------------------------ deliver --

    def deliver(self, delivery_id, final_path, name, folder_id,
                now="", variant_plan_id="", experiment_revision=0):
        """Persist intent → reuse a verified identical remote file →
        upload → verify. Any ambiguity reconciles remote state first."""
        now = now or _now()
        sha = _sha256(final_path)
        md5 = _md5(final_path)
        size = Path(final_path).stat().st_size
        d = Delivery(schema_version="delivery.v1", id=delivery_id,
                     created_at=now, file_sha256=sha,
                     parent_folder_id=folder_id, status="pending",
                     variant_plan_id=variant_plan_id,
                     experiment_revision=experiment_revision)
        d.validate_or_raise()
        self._put(d)
        self._set(delivery_id, remote_md5=md5, drive_link="",
                  delivery_name=name)
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
        try:
            up = self.drive.upload(folder_id, final_path, name)
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

    def _find(self, folder_id, name):
        for f in self.drive.list_files(folder_id):
            if f.get("name") == name:
                st = self.drive.stat(f["id"]) or f
                return {**f, **(st or {})}
        return None

    def _verify(self, delivery_id, file_id, name, folder_id, size,
                md5, now, reused=False):
        st = self.drive.stat(file_id)
        problems = []
        if st is None:
            problems.append("stat_unavailable")
        else:
            if st.get("parent") and st["parent"] != folder_id:
                problems.append(f"wrong_parent:{st['parent']}")
            if st.get("name") and st["name"] != name:
                problems.append(f"wrong_name:{st['name']}")
            if st.get("size") and int(st["size"]) != size:
                problems.append(f"size_mismatch:{st['size']}!={size}")
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
        self._set(delivery_id, status="verified",
                  drive_file_id=file_id,
                  drive_link=self.drive.link(file_id),
                  remote_md5=md5, verified_at=now,
                  cleanup_receipt="reused" if reused else "")
        self._event(delivery_id, "upload_verified",
                    {"file_id": file_id, "reused": reused})
        return {"status": "verified", "file_id": file_id,
                "link": self.drive.link(file_id), "reused": reused}

    # ------------------------------------------------------ recover --

    def reconcile(self, delivery_id, now=""):
        """After restart/lost ack: remote state decides, never blind
        re-upload. A same-name different-content file is a conflict."""
        now = now or _now()
        d = self._get(delivery_id)
        name = self._name_of(delivery_id)
        remote = self._find(d["parent_folder_id"], name)
        if remote is None:
            self._set(delivery_id, status="pending")
            return {"status": "pending", "action": "retry_transfer"}
        if remote.get("md5") == d["remote_md5"]:
            return self._verify(delivery_id, remote["id"], name,
                                d["parent_folder_id"],
                                remote.get("size", 0),
                                d["remote_md5"], now, reused=True)
        self._set(delivery_id, status="conflict",
                  drive_file_id=remote["id"])
        return {"status": "conflict",
                "detail": "remote name exists with different content"}

    def retry(self, delivery_id, final_path, now=""):
        """Transfer-only retry: re-uploads the SAME local final; never
        regenerates or renders anything."""
        d = self._get(delivery_id)
        if d["file_sha256"] != _sha256(final_path):
            raise ContractError("final_changed", "file_sha256",
                                "retry requires the identical final")
        name = self._name_of(delivery_id)
        try:
            up = self.drive.upload(d["parent_folder_id"], final_path,
                                   name)
        except Exception:
            return self.reconcile(delivery_id, now=now)
        return self._verify(delivery_id, up["id"], name,
                            d["parent_folder_id"],
                            Path(final_path).stat().st_size,
                            _md5(final_path), now or _now())

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
                "UPDATE records SET body=? WHERE kind='delivery' AND "
                "id=? AND revision=?",
                (json.dumps(body), delivery_id, row["revision"]))

    def _event(self, delivery_id, kind, body):
        with self.db.uow() as u:
            u.events.append(f"delivery:{delivery_id}", kind, body)
