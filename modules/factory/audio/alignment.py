"""Word alignment + captions (F19 checklist 3,5): align the approved
text to the exact returned waveform; derive captions through the fit
transform so cues land on the right frames.
"""
import json
from fractions import Fraction

from ..domain.errors import ContractError
from ..domain.records import CaptionSet, WordAlignment, content_hash
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
        if seg.get("raw_alignment"):
            from ...batch.audio import word_times
            # The provider aligned the text it was actually GIVEN —
            # source_text — which may differ in surface form from the
            # normalized seg["text"] (contractions, numerals).
            spoken = seg.get("source_text") or seg["text"]
            if "".join(seg["raw_alignment"]["characters"]) != spoken:
                raise ContractError("alignment_text_mismatch", "segment_id")
            aligned = word_times(seg["raw_alignment"], 0, 1, 0, seg.get("raw_duration_s",seg["duration_s"]))
            words = [{"w": w["text"], "start_s": w["start"], "end_s": w["end"], "confidence": 1.0} for w in aligned]
            aligner_id = "elevenlabs-v3-character-alignment"
        elif self.aligner is not None:
            words = self.aligner.align(seg["text"], seg.get("raw_audio_sha256",seg["audio_sha256"]), seg.get("raw_duration_s",seg["duration_s"]))
        else:
            raise ContractError("alignment_required", "segment_id")
        conf = ([w.get("confidence", 0.0) for w in words] or [0.0])
        al = WordAlignment(
            schema_version="word_alignment.v1",
            id=f"align:{segment_id}", created_at=now,
            segment_id=segment_id, audio_sha256=seg.get("raw_audio_sha256",seg["audio_sha256"]),
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
                 speech_hash="", now="", preset="words.v1", *, exact=False):
        """Map aligned words through the fit into frame cues. One cue
        per word for now — grouping is a presentation decision above."""
        al = self.get(segment_id)
        if al is None:
            raise ContractError("missing_alignment", "segment_id",
                                segment_id)
        seg = speech_get(segment_id)
        if seg.get("status") not in ("fitted","approved") or fit != seg.get("fit"):
            raise ContractError("fitted_waveform_required", "segment_id")
        if speech_hash != seg.get("speech_hash") or al["audio_sha256"] != seg.get("raw_audio_sha256",seg["audio_sha256"]):
            raise ContractError("stale_alignment", "segment_id")
        mapped = apply_fit(al["words"], fit)
        tgt = seg.get("target") or {}
        start = tgt.get("start_frame", tgt.get("start", 0))
        fps = clock.num / clock.den
        cues = [{"start_frame": start + int(round(w["start_s"] * fps)),
                 "end_frame": start + int(round(w["end_s"] * fps)),
                 "text": w["w"], "word_refs": [i]}
                for i, w in enumerate(mapped)]
        if exact:
            final=self.final_alignment(segment_id,speech_get,clock,speech_hash)
            cues=[{**w,'word_refs':[i]} for i,w in enumerate(final['words'])]
        end=tgt.get("end_frame",tgt.get("end"))
        if not cues or any(not start <= c["start_frame"] < c["end_frame"] <= end for c in cues):
            raise ContractError("caption_coverage_invalid", "cues")
        if preset == 'phrases.v1':
            from .phrase_captions import phrase_cues
            # Provider character timestamps cover its exact submitted text;
            # an injected aligner covers the normalized text it was given.
            # Neither path uses the seed video's transcript.
            spoken = (seg.get('source_text') or seg['text']) if seg.get('raw_alignment') else seg['text']
            cues = phrase_cues(cues, spoken, start, end)
        elif preset != 'words.v1':
            raise ContractError('unsupported_caption_preset', 'preset')
        cs = CaptionSet(schema_version="caption_set.v1",
                        id=f"caps:{segment_id}", created_at=now,
                        segment_id=segment_id, speech_hash=speech_hash,
                        cues=cues,
                        transform={"rate": fit["rate"],
                                   "trim_s": fit.get("trim_s", 0.0),
                                   "pad_s": fit.get("pad_s", 0.0)})
        if preset != 'words.v1':
            cs.transform['caption_preset'] = preset
        cs.validate_or_raise()
        with self.db.uow() as u:
            u.records.put(cs)
        return cs

    def final_alignment(self,segment_id,speech_get,clock,speech_hash):
        """Export existing measurements once onto the final rational clock.

        Pure read/validation: never aligns again, estimates missing times, clamps
        words or applies the fit twice. Legacy caption behavior is unchanged.
        """
        al=self.get(segment_id);seg=speech_get(segment_id)
        if not al or not seg or seg.get('status') not in ('fitted','approved') or not seg.get('fit',{}).get('fits'):
            raise ContractError('fitted_waveform_required','segment_id')
        if speech_hash!=seg['speech_hash'] or al['audio_sha256']!=seg.get('raw_audio_sha256',seg['audio_sha256']):
            raise ContractError('stale_alignment','segment_id')
        spoken=(seg.get('source_text') or seg['text']) if seg.get('raw_alignment') else seg['text']
        if ' '.join(w['w'] for w in al['words']).split()!=spoken.split():
            raise ContractError('semantic_text_mismatch','segment_id')
        target=seg['target'];start=target.get('start_frame',target.get('start',0));end=target.get('end_frame',target.get('end'))
        rate=Fraction(str(seg['fit']['rate']));trim=Fraction(str(seg['fit'].get('trim_s',0)))
        fps=Fraction(clock.num,clock.den);previous=Fraction(0);last=start;words=[]
        for w in al['words']:
            low=(Fraction(str(w['start_s']))-trim)/rate
            high=(Fraction(str(w['end_s']))-trim)/rate
            if not previous<=low<high<=Fraction(end-start,1)/fps:
                raise ContractError('semantic_word_timing_invalid','segment_id','Final speech timings are outside the fitted waveform.')
            first,final=start+round(low*fps),start+round(high*fps)
            if not last<=first<final<=end:
                raise ContractError('semantic_word_timing_invalid','segment_id','A word is ambiguous on the final frame clock.')
            words.append({'text':w['w'],'start_frame':first,'end_frame':final})
            previous=high;last=final
        if not words:
            raise ContractError('missing_alignment','segment_id')
        binding={'raw_alignment_hash':content_hash(al),'fit':seg['fit'],'clock':{'num':clock.num,'den':clock.den},
                 'speech_hash':speech_hash,'audio_sha256':seg['audio_sha256'],'target':target,'policy':'final_alignment.v1'}
        return {'artifact_id':seg['artifact_id'],'sha256':seg['audio_sha256'],'speech_hash':speech_hash,
                'alignment_hash':content_hash(binding),'text':spoken,'words':words,'in_frame':start,'out_frame':end}
