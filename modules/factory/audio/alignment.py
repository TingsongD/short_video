"""Word alignment + captions (F19 checklist 3,5): align the approved
text to the exact returned waveform; derive captions through the fit
transform so cues land on the right frames.
"""
import json

from ..domain.errors import ContractError
from ..domain.records import CaptionSet, WordAlignment
from .fit import apply_fit


class AlignmentService:
    """`aligner` is injected: align(text, audio_sha256, duration_s) →
    [{"w","start_s","end_s","confidence"}]. An alignment service has
    its own budget/retry — this service only stores results."""

    def __init__(self, db, aligner):
        self.db = db
        self.aligner = aligner

    def align(self, segment_id, speech_get, aligner_id="fake-align.v1",
              now=""):
        seg = speech_get(segment_id)
        if not seg.get("audio_sha256") or seg.get("duration_s") is None:
            raise ContractError("no_waveform", "segment_id",
                                "voice the segment first")
        words = self.aligner.align(seg["text"], seg["audio_sha256"],
                                   seg["duration_s"])
        conf = ([w.get("confidence", 0.0) for w in words] or [0.0])
        al = WordAlignment(
            schema_version="word_alignment.v1",
            id=f"align:{segment_id}", created_at=now,
            segment_id=segment_id, audio_sha256=seg["audio_sha256"],
            spoken_text=seg["text"], words=words,
            aligner={"kind": "injected", "version": aligner_id},
            confidence=sum(conf) / len(conf))
        al.validate_or_raise()
        with self.db.uow() as u:
            u.records.put(al)
        return al

    def get(self, segment_id):
        row = self.db.uow().records.get("wordalignment",
                                        f"align:{segment_id}")
        return json.loads(row["body"]) if row else None

    def captions(self, segment_id, speech_get, fit, clock,
                 speech_hash="", now=""):
        """Map aligned words through the fit into frame cues. One cue
        per word for now — grouping is a presentation decision above."""
        al = self.get(segment_id)
        if al is None:
            raise ContractError("missing_alignment", "segment_id",
                                segment_id)
        mapped = apply_fit(al["words"], fit)
        seg = speech_get(segment_id)
        tgt = seg.get("target") or {}
        start = tgt.get("start_frame", tgt.get("start", 0))
        fps = clock.num / clock.den
        cues = [{"start_frame": start + int(round(w["start_s"] * fps)),
                 "end_frame": start + int(round(w["end_s"] * fps)),
                 "text": w["w"], "word_refs": [i]}
                for i, w in enumerate(mapped)]
        cs = CaptionSet(schema_version="caption_set.v1",
                        id=f"caps:{segment_id}", created_at=now,
                        segment_id=segment_id, speech_hash=speech_hash,
                        cues=cues,
                        transform={"rate": fit["rate"],
                                   "trim_s": fit.get("trim_s", 0.0),
                                   "pad_s": fit.get("pad_s", 0.0)})
        cs.validate_or_raise()
        with self.db.uow() as u:
            u.records.put(cs)
        return cs
