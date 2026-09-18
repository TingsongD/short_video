"""Analysis service (F12): verified source → probed clocks → bounded
worker call → timed blueprint draft with evidence-linked beats.

- The multimodal call rides the F07 Executor: intent+attempt persist
  before dispatch; a lost ack stays `unknown` until reconcile; partial
  outputs survive restarts.
- The source file is never modified — frames are extracted as new
  artifacts, analysis is read-only.
- Every beat maps source seconds → source frames (source clock) and
  target frames (output clock) exactly once; the last beat is snapped
  to target_frames so the partition tiles exactly.
"""
import hashlib
import json

from ..domain.clocks import FPS_30, FrameInterval, RationalRate
from ..domain.errors import ContractError
from ..domain.records import Beat, ReferenceBlueprint
from ..media.audio import audio_characteristics
from ..media.frames import extract_frame
from ..media.probe import probe
from ..media.scenes import detect_scenes
from ..store.uow import utcnow
from ..testing.fakes import ProviderError
from .analyzer import parse_analysis


def blueprint_id_for(seed_id):
    return f"bp-{seed_id}"


def load_blueprint(row):
    d = json.loads(row["body"])
    d["clock"] = RationalRate(**d["clock"]) if d.get("clock") else None
    beats = []
    for b in d.get("beats") or []:
        b = dict(b)
        b["source"] = FrameInterval.from_dict(b["source"]) \
            if b.get("source") else None
        b["target"] = FrameInterval.from_dict(b["target"]) \
            if b.get("target") else None
        beats.append(Beat(**b))
    d["beats"] = beats
    return ReferenceBlueprint(**d)


class AnalysisService:
    def __init__(self, db, registry, artifacts, executor, analyzer,
                 provider_name="analyzer", model="fake-av-1",
                 route="video+audio", effects=None):
        self.db = db
        self.effects = effects
        self.registry = registry
        self.artifacts = artifacts
        self.executor = executor
        self.analyzer = analyzer
        self.provider_name = provider_name
        self.model = model
        self.route = route

    # --------------------------------------------------------- run

    def import_observations(self, seed_id, observations, reviewer, target_rate=FPS_30, provenance=None):
        """Operator observations use the same parser and real media evidence."""
        if not reviewer.strip():
            raise ContractError("reviewer_required", "reviewer")
        seed = self.registry.get(seed_id)
        if seed.evidence_status != "media_ready":
            raise ContractError("source_not_ready", "seed_id")
        src = self.artifacts.verified_path(seed.source_asset_id)
        info = probe(src)
        analysis = parse_analysis(observations)
        if any(b["end_s"] > info.duration_s + .05 for b in analysis["beats"]):
            raise ContractError("beat_outside_source", "beats")
        sha = self.db.uow().artifacts.get(seed.source_asset_id)["sha256"]
        bp = self._build(seed, seed.source_asset_id, sha, info,
                         audio_characteristics(src), detect_scenes(src), analysis,
                         target_rate, utcnow(), src)
        bp.provenance.update(analyzer="manual_observations", model="", reviewer=reviewer)
        bp.provenance.update(provenance or {})
        bp.content_hash = self._hash(bp)
        bp.validate_or_raise()
        self._persist(bp, "manual_observations")
        return bp

    def analyze(self, seed_id, target_rate=FPS_30, job_id=None,
                observed_at=None):
        """→ draft ReferenceBlueprint. Source must be verified video."""
        seed = self.registry.get(seed_id)
        if seed.evidence_status != "media_ready" or not \
                seed.source_asset_id:
            raise ContractError("source_not_ready", "seed_id", seed_id)
        artifact_id = seed.source_asset_id
        src = self.artifacts.path_for(artifact_id)
        info = probe(src)
        if info.kind() != "video":
            raise ContractError("source_not_video", "artifact",
                                f"probed {info.kind()}")
        src_sha = self.db.uow().artifacts.get(artifact_id)["sha256"]

        audio = audio_characteristics(src)
        scenes = detect_scenes(src)
        request = {"artifact_id": artifact_id, "artifact_sha256": src_sha,
                   "duration_s": info.duration_s,
                   "scenes": scenes, "audio_present": audio["present"],
                   "input_mode": self.route, "seed_id": seed.id}
        job_id = job_id or f"job:analysis:{seed_id}"
        if self.effects is None:
            raise ContractError("authority_required", "analysis")
        attempt = self.effects(request, job_id, "analysis", self.provider_name, self.model)
        self.executor.require_request(attempt, request)
        self.executor.submit(attempt)
        op = self.executor.poll(attempt)
        return self._finish(attempt, op, target_rate,
                            observed_at or utcnow())

    def resume(self, attempt_id, target_rate=FPS_30):
        """Finish a prepared/reconciled analysis attempt — the recovery
        path after a lost ack or process interruption. Polls the SAME
        remote operation; never resubmits."""
        op = self.executor.poll(attempt_id)
        if op.get("status") != "succeeded":
            raise ContractError("analysis_not_finished", "attempt_id",
                                f"remote status {op.get('status')}")
        return self._finish(attempt_id, op, target_rate, utcnow())

    def _finish(self, attempt_id, op, rate, now):
        row = self.db.conn.execute(
            "SELECT body FROM intents WHERE intent_key LIKE ?",
            (f"%{attempt_id}",)).fetchone()
        request = (json.loads(row[0]) or {}).get("request") or {}
        seed = self.registry.get(request["seed_id"])
        src_sha = request["artifact_sha256"]
        artifact_id = seed.source_asset_id
        src = self.artifacts.path_for(artifact_id)
        info = probe(src)
        audio = audio_characteristics(src)
        scenes = request.get("scenes") or detect_scenes(src)
        analysis = parse_analysis(
            (op.get("result") or {}).get("analysis"))
        bp = self._build(seed, artifact_id, src_sha, info, audio,
                         scenes, analysis, rate, now, src)
        self._persist(bp, attempt_id)
        return bp

    def _build(self, seed, artifact_id, src_sha, info, audio, scenes,
               analysis, rate, now, src_path):
        v = info.video
        src_fps = v.avg_frame_rate or v.r_frame_rate or rate.fps
        src_clock = RationalRate(src_fps.numerator, src_fps.denominator)
        target_frames = rate.seconds_to_frames(info.duration_s)
        evidence = []
        # one representative frame per beat, taken at beat midpoint —
        # the source itself is never written to
        beats = []
        n = len(analysis["beats"])
        for i, b in enumerate(analysis["beats"]):
            mid = (b["start_s"] + b["end_s"]) / 2
            frame = extract_frame(src_path, mid,
                                  self.artifacts.root / "staging"
                                  / f"evidence-{i}.png")
            art = self.artifacts.intake_bytes(
                frame.read_bytes(), provenance="derived:analysis",
                source_key=f"{src_sha}@{mid:.3f}",
                source_detail=f"seed:{seed.id} beat:{b['id']}",
                requested_kind="image")
            frame.unlink(missing_ok=True)
            evidence.append(art.id)
            end_s = (b["end_s"] if i < n - 1 else info.duration_s)
            beats.append(Beat(
                id=b["id"], role=b["role"],
                source=FrameInterval(
                    src_clock.seconds_to_frames(b["start_s"]),
                    src_clock.seconds_to_frames(end_s)),
                target=FrameInterval(
                    rate.seconds_to_frames(b["start_s"]),
                    rate.seconds_to_frames(end_s)
                    if i < n - 1 else target_frames),
                speech_segment_id=self._segment_for(
                    analysis["transcript"], b["start_s"], end_s),
                visual_event=b["visual_event"],
                evidence_ids=[art.id] + [
                    f"scene:{j}" for j, s in enumerate(scenes)
                    if b["start_s"] <= s["t"] < end_s],
                confidence=b["confidence"]))
        bp = ReferenceBlueprint(
            schema_version="blueprint.v1", id=blueprint_id_for(seed.id),
            created_at=now, seed_id=seed.id, revision=1, status="draft",
            clock=rate, target_frames=target_frames, beats=beats,
            speech={"transcript": analysis["transcript"],
                    "observed_source_text": True,
                    "pace_wps": self._pace(analysis["transcript"]),
                    "style": "attributes_only"},
            visual_systems={"scene_candidates": scenes,
                            "scene_count": len(scenes)},
            audio={**audio, "music_role": analysis["music"]["role"]},
            adaptation={"requires_new_copy": True,
                        "presenter": "fictional_or_authorized",
                        "voice": "new_selected"},
            provenance={"artifact_sha256": src_sha,
                        "analyzer": self.provider_name,
                        "model": self.model, "input_mode": self.route,
                        "uncertainty": analysis["uncertainty"]})
        bp.content_hash = self._hash(bp)
        return bp

    def _persist(self, bp, attempt_id):
        prior = self.db.uow().records.get("referenceblueprint", bp.id)
        if prior:
            bp.revision = prior["revision"] + 1
        with self.db.uow() as u:
            u.records.put(bp)
            u.events.append(f"blueprint:{bp.id}", "draft",
                            {"revision": bp.revision,
                             "attempt": attempt_id,
                             "beats": len(bp.beats)})

    def get(self, blueprint_id, revision=None):
        row = self.db.uow().records.get("referenceblueprint",
                                        blueprint_id, revision=revision)
        if row is None:
            raise ContractError("unknown_blueprint", "id", blueprint_id)
        return load_blueprint(row)

    # ------------------------------------------------------- helpers

    @staticmethod
    def _segment_for(transcript, start_s, end_s):
        for t in transcript:
            if t["start_s"] < end_s and t["end_s"] > start_s:
                return t["id"]
        return ""

    @staticmethod
    def _pace(transcript):
        words = sum(len(t["text"].split()) for t in transcript)
        secs = sum(t["end_s"] - t["start_s"] for t in transcript)
        return round(words / secs, 2) if secs > 0 else None

    @staticmethod
    def _hash(bp):
        d = bp.to_dict()
        for k in ("created_at", "revision", "content_hash", "status",
                  "analysis"):
            d.pop(k, None)
        return hashlib.sha256(json.dumps(
            d, sort_keys=True, default=str).encode()).hexdigest()
