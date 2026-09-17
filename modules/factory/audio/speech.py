"""Speech service (F19): normalization, identity-bound segments,
TTS dispatch through F07 intents, waveform measurement, and the
approved-speech hash that lip-sync work binds to.
"""
import hashlib
import json
import re

from ...script.voicetext import clean
from ..domain.errors import ContractError
from ..domain.records import SpeechSegment, content_hash

NORMALIZATION_VERSION = "voicetext.v1"

_MARKUP = re.compile(r"[*_`#\[\]~|]|<[^>]+>|\{[^}]*\}")


class SpeechService:
    def __init__(self, db, artifacts, tts=None, executor=None,
                 budget=None, clock=None):
        self.db = db
        self.artifacts = artifacts
        self.tts = tts                  # adapter with submit/observe/
                                        # download/reconcile
        self.executor = executor
        self.budget = budget
        self.clock = clock

    # -------------------------------------------------- normalization

    def normalize(self, text):
        """voicetext.clean + a markup check: surviving markup means the
        source carried something the cleaner doesn't know — refuse it
        rather than speak it."""
        cleaned = clean(text or "")
        if not cleaned:
            raise ContractError("empty_speech_text", "text")
        if _MARKUP.search(cleaned):
            raise ContractError("markup_in_speech", "text",
                                "normalization left markup-like syntax")
        return cleaned

    def cache_key(self, voice, text):
        """voice+model+language+settings+normalization+normalized text
        — two variants asking for the same thing get the same segment."""
        return content_hash({
            "voice_id": voice.get("voice_id"),
            "model": voice.get("model"),
            "language": voice.get("language", "en"),
            "settings": voice.get("settings") or {},
            "normalization": NORMALIZATION_VERSION, "text": text})

    # ------------------------------------------------------ segments

    def plan_segment(self, segment_id, variant_id, source_text, voice,
                     target, now=""):
        text = self.normalize(source_text)
        seg = SpeechSegment(
            schema_version="speech_segment.v1", id=segment_id,
            created_at=now, segment_id=segment_id,
            variant_id=variant_id,
            cache_key=self.cache_key(voice, text),
            voice=dict(voice), normalization=NORMALIZATION_VERSION,
            source_text=source_text, text=text, target=target)
        seg.validate_or_raise()
        with self.db.uow() as u:
            u.records.put(seg)
        return seg

    def get(self, segment_id):
        row = self.db.uow().records.get("speechsegment", segment_id)
        return json.loads(row["body"]) if row else None

    def cache_lookup(self, cache_key, statuses=("fitted", "approved")):
        """Reuse voiced/fitted segments across variants by identity."""
        for row in self.db.conn.execute(
                "SELECT body FROM records WHERE kind='speechsegment'"
                ).fetchall():
            body = json.loads(row["body"])
            if body.get("cache_key") == cache_key and \
                    body.get("status") in statuses:
                return body
        return None

    def reuse_from_cache(self, segment_id):
        """Attach this planned segment to the cached waveform of an
        identical earlier segment — same bytes, same voice, zero new
        synthesis. Returns the reused source or None."""
        seg = self._require(segment_id)
        hit = self.cache_lookup(seg["cache_key"])
        if hit is None or hit["id"] == segment_id:
            return None
        self._set(segment_id, status=hit["status"],
                  artifact_id=hit["artifact_id"],
                  audio_sha256=hit["audio_sha256"],
                  duration_s=hit["duration_s"],
                  speech_hash=hit.get("speech_hash", ""))
        with self.db.uow() as u:
            u.events.append(f"speech:{segment_id}", "cache_reuse",
                            {"reused_from": hit["id"],
                             "cache_key": seg["cache_key"]})
        return hit

    # --------------------------------------------------- synthesize

    def synthesize(self, segment_id, job_id, lines=None, attempt_seq=1, attempt_id=None):
        """Reserve (optional) → persist intent → submit through the TTS
        adapter. A lost acknowledgement leaves the attempt unknown —
        never resynthesized blindly."""
        seg = self._require(segment_id)
        req = {"text": seg["text"], "voice_id": seg["voice"]["voice_id"],
               "model": seg["voice"]["model"],
               "language": seg["voice"].get("language", "en"),
               "settings": seg["voice"].get("settings") or {}}
        wire = json.dumps(req, sort_keys=True, default=str)
        rh = hashlib.sha256(wire.encode()).hexdigest()
        prepared = self.executor.require_request(attempt_id, req)
        if prepared["job_id"] != job_id:
            raise ContractError("operation_identity_conflict", "job_id", job_id)
        res = prepared["reservation_id"]
        op = self.executor.submit(
            attempt_id, lambda: self.tts.submit(req))
        self._set(segment_id, status="submitted")
        return {"attempt_id": attempt_id, "reservation_id": res,
                "request_hash": rh, "operation": op}

    def collect(self, segment_id, operation_id):
        """Observe → download → intake → measured duration. Download
        failures retry the transfer, not the synthesis."""
        obs = self.tts.observe(operation_id)
        if obs["status"] != "succeeded":
            return {"status": obs["status"]}
        dl = self.tts.download(operation_id)
        payload = dl["bytes"]
        if isinstance(payload, str):
            payload = payload.encode()
        art = self.artifacts.intake_bytes(
            payload, provenance="elevenlabs",
            source_key=f"tts:{operation_id}",
            source_detail=f"segment:{segment_id}",
            requested_kind="audio")
        duration = (art.probe or {}).get("duration_s")
        self._set(segment_id, status="voiced", artifact_id=art.id,
                  audio_sha256=art.sha256, duration_s=duration)
        return {"status": "voiced", "artifact_id": art.id,
                "audio_sha256": art.sha256, "duration_s": duration}

    def recover(self, segment_id, operation_id=None, request_hash=None):
        rec = self.tts.reconcile(operation_id=operation_id,
                                 request_hash=request_hash)
        if rec is None:
            return {"status": "no_remote_trace",
                    "action": "reconcile_or_review_evidence"}
        if rec.get("status") == "succeeded":
            return self.collect(segment_id, rec["operation_id"])
        return {"status": rec.get("status", "unknown")}

    # ------------------------------------------------------- approval

    def approve(self, segment_id, speech_hash, reviewer=""):
        """Pin the speech version lip-sync picture requests must name."""
        seg = self._require(segment_id)
        if seg.get("speech_hash") and seg["speech_hash"] != speech_hash:
            raise ContractError("revision_mismatch", "speech_hash")
        if seg["status"] != "fitted":
            raise ContractError("not_fitted", "status", seg["status"])
        self._set(segment_id, status="approved",
                  speech_hash=speech_hash)
        with self.db.uow() as u:
            u.events.append(f"speech:{segment_id}", "approved",
                            {"speech_hash": speech_hash,
                             "reviewer": reviewer})
        return self.get(segment_id)

    # --------------------------------------------------------- helpers

    def _require(self, segment_id):
        seg = self.get(segment_id)
        if seg is None:
            raise ContractError("unknown_segment", "segment_id",
                                segment_id)
        return seg

    def _set(self, segment_id, **fields):
        row = self.db.uow().records.get("speechsegment", segment_id)
        body = json.loads(row["body"])
        body.update(fields)
        with self.db.uow() as u:
            u.conn.execute(
                "UPDATE records SET body=? WHERE kind='speechsegment'"
                " AND id=? AND revision=?",
                (json.dumps(body), segment_id, row["revision"]))
