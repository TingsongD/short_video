"""Quality service (F24): technical + creative + changed-region
verdicts bound to exact final/composition hashes. Stale acceptance is
rejected; repairs are bounded jobs, never unlimited regeneration.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from ..domain.errors import ContractError
from ..domain.records import Review


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class QualityService:
    def __init__(self, db, technical=None, region_gate=None,
                 max_repairs=1):
        self.db = db
        self.technical = technical
        self.gate = region_gate
        self.max_repairs = max_repairs

    # -------------------------------------------------- inspection --

    def inspect(self, check_id, final_path, expected, now=""):
        """Run technical QC; persist a Review bound to the final's
        exact bytes."""
        now = now or datetime.now(timezone.utc).isoformat()
        final_hash = _sha(final_path)
        rep = self.technical.inspect(final_path, expected)
        verdict = "pass" if rep["ok"] else \
            ("uncertain" if all(f["code"] in ("silent_audio",)
                                for f in rep["findings"]) else "fail")
        rev = Review(schema_version="review.v1", id=check_id,
                     created_at=now, target_hash=final_hash,
                     check_type="technical",
                     reviewer_type="automated", verdict=verdict,
                     evidence_ids=[],
                     limitations=[f["code"] + "@" + f["at"]
                                  for f in rep["findings"]])
        rev.validate_or_raise()
        self._put(rev)
        return {"verdict": verdict, "report": rep,
                "target_hash": final_hash}

    def record_verdict(self, check_id, target_hash, check_type,
                       verdict, evidence=(), limitations=(), now=""):
        now = now or datetime.now(timezone.utc).isoformat()
        rev = Review(schema_version="review.v1", id=check_id,
                     created_at=now, target_hash=target_hash,
                     check_type=check_type, reviewer_type="human",
                     verdict=verdict, evidence_ids=list(evidence),
                     limitations=list(limitations))
        rev.validate_or_raise()
        self._put(rev)
        return rev.to_dict()

    # ---------------------------------------------- changed regions --

    def check_regions(self, check_id, a_path, b_path, unchanged_regions,
                      fps, now=""):
        now = now or datetime.now(timezone.utc).isoformat()
        out = self.gate.compare_finals(a_path, b_path,
                                       unchanged_regions, fps)
        verdict = "pass" if out["ok"] else "fail"
        rev = Review(schema_version="review.v1", id=check_id,
                     created_at=now,
                     target_hash=_sha(b_path),
                     check_type="changed_region",
                     reviewer_type="automated", verdict=verdict,
                     evidence_ids=[],
                     limitations=[f"ssim {r['ssim']} @{r['region']}"
                                  for r in out.get("diffs", [])])
        rev.validate_or_raise()
        self._put(rev)
        return {"verdict": verdict, **out}

    # ------------------------------------------------- acceptance ---

    def accept(self, final_path, check_ids):
        """Acceptance requires every bound review to pass against the
        CURRENT bytes — a review on old bytes is stale."""
        current = _sha(final_path)
        problems = []
        for cid in check_ids:
            rev = self._get(cid)
            if rev is None:
                problems.append(f"missing_review:{cid}")
                continue
            if rev["target_hash"] != current or rev["invalidated_by"]:
                problems.append(f"stale_review:{cid}")
            elif rev["verdict"] != "pass":
                problems.append(f"{rev['check_type']}:{rev['verdict']}")
        if problems:
            raise ContractError("acceptance_blocked", "reviews",
                                ";".join(problems))
        return {"accepted": True, "target_hash": current}

    def invalidate_stale(self, final_path, check_ids):
        """After bytes change: mark reviews on the old hash stale."""
        current = _sha(final_path)
        marked = []
        for cid in check_ids:
            rev = self._get(cid)
            if rev and rev["target_hash"] != current \
                    and not rev["invalidated_by"]:
                self._update(cid, invalidated_by=current)
                marked.append(cid)
        return marked

    # ------------------------------------------------------------ --

    def request_repair(self, plan_id, reason):
        """A failed check opens at most max_repairs bounded jobs —
        QC failure cannot trigger unlimited regeneration."""
        key = f"repairs:{plan_id}"
        used = int(self._meta(key) or 0)
        if used >= self.max_repairs:
            raise ContractError("repair_budget_exceeded", "plan_id",
                                f"{used}/{self.max_repairs} used")
        self._meta(key, used + 1)
        return {"repair_seq": used + 1, "bounded": True,
                "reason": reason}

    def _meta(self, key, val=None):
        if val is None:
            r = self.db.conn.execute(
                "SELECT value FROM scheduler_flags WHERE key=?",
                (key,)).fetchone()
            return r["value"] if r else None
        with self.db.uow() as u:
            u.conn.execute(
                "INSERT OR REPLACE INTO scheduler_flags(key,value) "
                "VALUES(?,?)", (key, str(val)))

    def _get(self, cid):
        row = self.db.uow().records.get("review", cid)
        return json.loads(row["body"]) if row else None

    def _put(self, rev):
        with self.db.uow() as u:
            u.records.put(rev)

    def _update(self, cid, **fields):
        row = self.db.uow().records.get("review", cid)
        body = json.loads(row["body"])
        body.update(fields)
        with self.db.uow() as u:
            u.conn.execute(
                "UPDATE records SET body=? WHERE kind='review' AND "
                "id=? AND revision=?",
                (json.dumps(body), cid, row["revision"]))
