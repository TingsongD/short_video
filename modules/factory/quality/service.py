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

    def inspect(self, check_id, final_path, expected, now="", binding=None):
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
                     check_type="technical", binding=binding or {}, evidence_data={"report":rep,"expected":expected},
                     reviewer_type="automated", verdict=verdict,
                     evidence_ids=[],
                     limitations=[f["code"] + "@" + f["at"]
                                  for f in rep["findings"]])
        rev.validate_or_raise()
        self._put(rev)
        return {"verdict": verdict, "report": rep,
                "target_hash": final_hash}

    def record_verdict(self, check_id, target_hash, check_type,
                       verdict, evidence=(), limitations=(), now="", binding=None, reviewer=""):
        now = now or datetime.now(timezone.utc).isoformat()
        rev = Review(schema_version="review.v1", id=check_id,
                     created_at=now, target_hash=target_hash,
                     check_type=check_type, reviewer_type="human", binding=binding or {}, reviewer=reviewer,
                     verdict=verdict, evidence_ids=list(evidence),
                     limitations=list(limitations))
        rev.validate_or_raise()
        self._put(rev)
        return rev.to_dict()

    # ---------------------------------------------- changed regions --

    def check_regions(self, check_id, a_path, b_path, unchanged_regions,
                      fps, now="", binding=None, audio_rate=48000):
        now = now or datetime.now(timezone.utc).isoformat()
        out = self.gate.compare_finals(a_path, b_path,
                                       unchanged_regions, fps)
        from ..audio import pcm
        try:
            a_audio=pcm.decode(a_path,audio_rate); b_audio=pcm.decode(b_path,audio_rate)
            audio_checks=[self.gate.compare_audio_region(a_audio,b_audio,
                          {"start_s":r["start_frame"]/fps,"end_s":r["end_frame"]/fps},audio_rate)
                          for r in unchanged_regions]
        except (OSError,ValueError):
            audio_checks=[{"ok":False,"code":"missing_audio_evidence"}]
        out["audio"]=audio_checks
        out["ok"]=out["ok"] and bool(audio_checks) and all(c["ok"] for c in audio_checks)
        verdict = "pass" if out["ok"] else "fail"
        rev = Review(schema_version="review.v1", id=check_id,
                     created_at=now,
                     target_hash=_sha(b_path),
                     check_type="changed_region", binding=binding or {}, evidence_data={"report":out,"unchanged_regions":unchanged_regions,"control_sha256":_sha(a_path)},
                     reviewer_type="automated", verdict=verdict,
                     evidence_ids=[],
                     limitations=[f"ssim {r['ssim']} @{r['region']}"
                                  for r in out.get("diffs", [])])
        rev.validate_or_raise()
        self._put(rev)
        return {"verdict": verdict, **out}

    # ------------------------------------------------- acceptance ---

    def accept(self, final_path, check_ids, binding=None):
        """Acceptance requires every bound review to pass against the
        CURRENT bytes — a review on old bytes is stale."""
        current = _sha(final_path)
        problems = [] if check_ids else ["missing_required_reviews"]
        kinds=set()
        if not binding:
            problems.append("missing_plan_composition_binding")
        else:
            try:
                actual=self.binding(final_path,binding["composition_id"],binding["artifact_id"])
                if actual != binding:
                    problems.append("stale_composition_binding")
            except (ContractError,KeyError):
                problems.append("stale_composition_binding")
        for cid in check_ids:
            rev = self._get(cid)
            if rev is None:
                problems.append(f"missing_review:{cid}")
                continue
            kinds.add(rev["check_type"])
            if rev["check_type"] in ("technical","changed_region") and (rev["reviewer_type"]!="automated" or not rev.get("evidence_data",{}).get("report",{}).get("ok")):
                problems.append(f"automated_evidence_required:{cid}")
            if rev.get("binding") != binding:
                problems.append(f"unbound_review:{cid}")
            if rev["check_type"]=="creative" and (not rev.get("reviewer") or rev["reviewer_type"]!="human"):
                problems.append("explicit_creative_review_required")
            if rev["target_hash"] != current or rev["invalidated_by"]:
                problems.append(f"stale_review:{cid}")
            elif rev["verdict"] != "pass":
                problems.append(f"{rev['check_type']}:{rev['verdict']}")
        required={"technical","creative"}
        if binding and binding.get("variant_key") not in (None,"A"):
            required.add("changed_region")
        problems += [f"missing_required_review:{kind}" for kind in required-kinds]
        if problems:
            raise ContractError("acceptance_blocked", "reviews",
                                ";".join(problems))
        return {"accepted": True, "target_hash": current, "binding":binding,"check_ids":list(check_ids)}

    def binding(self, final_path, composition_id, artifact_id):
        row=self.db.uow().records.get("composition",composition_id)
        art=self.db.uow().artifacts.get(artifact_id)
        if row is None or art is None or art["sha256"] != _sha(final_path):
            raise ContractError("unregistered_final", "artifact")
        comp=json.loads(row["body"])
        latest=self.db.conn.execute("SELECT body FROM records WHERE kind='composition' AND json_extract(body,'$.experiment_id')=? AND json_extract(body,'$.variant_key')=? AND json_extract(body,'$.status')!='failed' ORDER BY revision DESC LIMIT 1",
                                    (comp["experiment_id"],comp["variant_key"])).fetchone()
        if not latest or json.loads(latest["body"])["content_hash"]!=comp["content_hash"]:
            raise ContractError("stale_composition", "composition")
        plan_hash=comp.get("source_revisions",{}).get("plan_hash")
        if not comp.get("content_hash") or not plan_hash or comp["status"]=="failed":
            raise ContractError("unbound_composition", "composition")
        plan=self.db.uow().records.get("productionplan",comp["plan_id"])
        if plan is None or json.loads(plan["body"])["plan_hash"] != plan_hash:
            raise ContractError("stale_plan", "plan_hash")
        plan_body=json.loads(plan["body"])
        current_exp=self.db.uow().records.get("experimentrevision",f"exp:{comp['experiment_id']}")
        if plan_body.get("stale_reason") or current_exp and current_exp["revision"]!=plan_body["experiment_revision"]:
            raise ContractError("stale_experiment", "plan")
        return {"composition_id":composition_id,"composition_revision":comp["revision"],
                "composition_hash":comp["content_hash"],"plan_hash":plan_hash,
                "artifact_id":artifact_id,"artifact_sha256":art["sha256"],"variant_key":comp["variant_key"]}

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
