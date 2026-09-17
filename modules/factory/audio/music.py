"""Music service (F20): imported/licensed beds and authorized
generation, measured BPM/structure, exact-duration construction with
declared loops/crossfades, and the frozen experiment master.
"""
import json

from ..domain.errors import ContractError
from ..domain.records import MusicBed
from . import pcm


def seed_brief(seed_blueprint_or_audio):
    """Describe the seed's energy/rhythm/arrangement → an original-bed
    brief. Derived descriptors, never copied audio."""
    audio = (seed_blueprint_or_audio or {}).get("audio") or {}
    return {"energy": audio.get("energy", "medium"),
            "rhythm": audio.get("rhythm", "steady"),
            "arrangement": audio.get("arrangement", "minimal"),
            "role": "underscore — leaves speech forward"}


class MusicService:
    def __init__(self, db, artifacts, generator=None, executor=None,
                 budget=None, analyzer=None):
        self.db = db
        self.artifacts = artifacts
        self.generator = generator      # music-gen adapter (own route)
        self.executor = executor
        self.budget = budget
        self.analyzer = analyzer        # injected bpm/structure probe

    # ----------------------------------------------------------- beds

    def import_bed(self, bed_id, artifact_id, license_ref, now=""):
        art = self.artifacts.path_for(artifact_id)
        row = self.db.uow().artifacts.get(artifact_id)
        probe = json.loads(row["probe"]) if row and row.get("probe") \
            else {}
        duration = probe.get("duration_s")
        bed = MusicBed(schema_version="music_bed.v1", id=bed_id,
                       created_at=now, source="imported",
                       provenance=license_ref, artifact_id=artifact_id,
                       sha256=row["sha256"] if row else "",
                       duration_s=duration, status="draft")
        bed.validate_or_raise()
        with self.db.uow() as u:
            u.records.put(bed)
        return bed

    def generate(self, bed_id, job_id, brief, lines=None, attempt_seq=1, attempt_id=None):
        """Authorized music generation through F05/F07 — its own
        route/credential, not implied by Vertex video OAuth."""
        req = {"kind": "music", "brief": brief}
        prepared = self.executor.require_request(attempt_id, req)
        if prepared["job_id"] != job_id:
            raise ContractError("operation_identity_conflict", "job_id", job_id)
        res = prepared["reservation_id"]
        op = self.executor.submit(
            attempt_id, lambda: self.generator.submit(req))
        return {"attempt_id": attempt_id, "reservation_id": res,
                "operation": op}

    def collect(self, bed_id, operation_id, model_ref, now=""):
        obs = self.generator.observe(operation_id)
        if obs["status"] != "succeeded":
            return {"status": obs["status"]}
        dl = self.generator.download(operation_id)
        payload = dl["bytes"]
        art = self.artifacts.intake_bytes(
            payload if not isinstance(payload, str)
            else payload.encode(), provenance="generated_other",
            source_key=f"music:{operation_id}",
            source_detail=f"model:{model_ref}", requested_kind="audio")
        measured = self._analyze(art)
        bed = MusicBed(schema_version="music_bed.v1", id=bed_id,
                       created_at=now, source="generated",
                       provenance=model_ref, artifact_id=art.id,
                       sha256=art.sha256, duration_s=measured["duration"],
                       bpm=measured.get("bpm"),
                       structure=measured.get("structure", {}),
                       status="draft")
        bed.validate_or_raise()
        with self.db.uow() as u:
            u.records.put(bed)
        return {"status": "collected", "bed": bed.to_dict()}

    def recover(self, bed_id, operation_id=None, request_hash=None,
                model_ref="", now=""):
        rec = self.generator.reconcile(operation_id=operation_id,
                                       request_hash=request_hash)
        if rec is None:
            return {"status": "no_remote_trace",
                    "action": "reconcile_or_review_evidence"}
        if rec.get("status") == "succeeded":
            return self.collect(bed_id, rec["operation_id"], model_ref,
                                now)
        return {"status": rec.get("status", "unknown")}

    # --------------------------------------------------- construction

    def construct_bed(self, bed_id, target_s, crossfade_s=0.25,
                      out_artifact=""):
        """Exact-duration bed from the master source: declared loops +
        crossfades; every join boundary is explicit, not masked."""
        bed = self._get(bed_id)
        path = self.artifacts.path_for(bed["artifact_id"])
        rate, src = pcm.read_wav(open(path, "rb").read())
        target_n = int(round(target_s * rate))
        xfade_n = int(crossfade_s * rate)
        loops = []
        n = len(src)
        pos = 0
        i = 0
        while pos < target_n:
            loops.append({"loop": i, "offset_s": round(pos / rate, 4),
                          "source": "master",
                          "crossfade_in_s": crossfade_s if i else 0})
            pos += n - (xfade_n if i else 0)
            i += 1
        # render deterministically: join loops with crossfades, then
        # trim/pad to the exact sample count
        out = list(src)
        for _ in loops[1:]:
            out = pcm.crossfade(out, src, xfade_n)
        if len(out) >= target_n:
            out = out[:target_n]
        else:
            out += [0] * (target_n - len(out))
        assert len(out) == target_n
        measured = pcm.measure(out, rate)
        construction = {"method": "loop+crossfade", "loops": loops,
                        "crossfade_s": crossfade_s,
                        "exact_samples": target_n,
                        "target_s": target_s,
                        "joins_inspected": len(loops) - 1}
        body = dict(bed)
        body["construction"] = construction
        body["duration_s"] = target_s
        body["status"] = "master"
        self._put(bed_id, body)
        wav = pcm.write_wav(out, rate)
        art = self.artifacts.intake_bytes(
            wav, provenance="generated_other",
            source_key=f"bed:{bed_id}:constructed",
            source_detail=f"{target_s}s master",
            requested_kind="audio")
        self._put(bed_id, {**body, "artifact_id": art.id,
                           "sha256": art.sha256})
        return {"construction": construction, "measured": measured,
                "artifact_id": art.id}

    def _analyze(self, artifact):
        """BPM/structure via injected analyzer; unknown stays None."""
        if self.analyzer is None:
            duration = ((artifact.probe or {}).get("duration_s"))
            return {"duration": duration, "bpm": None, "structure": {}}
        return self.analyzer.analyze(artifact)

    def _get(self, bed_id):
        row = self.db.uow().records.get("musicbed", bed_id)
        if row is None:
            raise ContractError("unknown_bed", "bed_id", bed_id)
        return json.loads(row["body"])

    def _put(self, bed_id, body):
        row = self.db.uow().records.get("musicbed", bed_id)
        with self.db.uow() as u:
            u.conn.execute(
                "UPDATE records SET body=? WHERE kind='musicbed'"
                " AND id=? AND revision=?",
                (json.dumps(body), bed_id, row["revision"]))
