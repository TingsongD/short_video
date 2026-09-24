"""Acoustic speaker evidence. Labels identify voices, never visual identities."""
import copy
import math

from ..domain.errors import ContractError
from ..autorun.source_timing import bounds, tokens

POLICY = 'whisperx-pyannote.v1'
MODEL = 'pyannote/speaker-diarization-community-1'


def label_words(transcription, intervals):
    """Split aligned text into turns; preserve uncertainty instead of nearest fill.

    A word needs >=80% support from one speaker. Simultaneous speech is
    explicitly flagged even when one of the voices dominates the interval.
    """
    spans = sorted(intervals, key=lambda x: (x['start'], x['end'], x['speaker']))
    labels = {}
    for span in spans:
        if (not isinstance(span.get('speaker'), str) or not span['speaker']
                or any(type(span.get(k)) not in (float, int) or not math.isfinite(span[k]) for k in ('start', 'end'))
                or not 0 <= span['start'] < span['end']):
            raise ContractError('diarization_invalid', 'intervals')
        labels.setdefault(span['speaker'], f'SPEAKER_{len(labels):02d}')
    turns, issues = [], []
    for segment in transcription.get('segments', []):
        words = segment.get('words') or []
        if tokens(' '.join(w.get('text', w.get('word', '')) for w in words)) != tokens(segment.get('text', '')):
            issues.append('Transcript words do not cover the full spoken text.')
        current = None
        for raw in words:
            word = copy.deepcopy(raw)
            start, end = bounds(word)
            speaker = None
            quality = 'unassigned'
            if (type(start) in (int, float) and type(end) in (int, float)
                    and math.isfinite(start) and math.isfinite(end) and 0 <= start < end):
                hits = [x for x in spans if x['start'] < end and x['end'] > start]
                weights = {}
                for x in hits:
                    weights[x['speaker']] = weights.get(x['speaker'], 0) + min(end, x['end']) - max(start, x['start'])
                overlap = any(a['speaker'] != b['speaker'] and
                    min(end, a['end'], b['end']) - max(start, a['start'], b['start']) > .02
                    for i, a in enumerate(hits) for b in hits[i+1:])
                best = sorted(weights, key=lambda k: (-weights[k], k))
                if overlap:
                    quality = 'overlap'
                elif best and weights[best[0]] / (end-start) >= .8 and (len(best) == 1 or weights[best[0]] > weights[best[1]]):
                    speaker, quality = labels[best[0]], 'assigned'
            word.update(speaker=speaker, speaker_status=quality)
            if quality != 'assigned':
                issues.append(f'Word speaker {quality}; review the acoustic evidence.')
            if current is None or current['speaker'] != speaker or quality != 'assigned':
                current = {'speaker': speaker, 'text': '', 'words': [], 'start': start, 'end': end}
                turns.append(current)
            current['words'].append(word)
            current['text'] = ' '.join(w.get('text', w.get('word', '')) for w in current['words'])
            current['end'] = end
    return {**transcription, 'stt_segments': copy.deepcopy(transcription.get('segments', [])),
        'segments': turns, 'diarization': {
        'policy': POLICY, 'model': MODEL, 'status': 'needs_review' if issues else 'complete',
        'speakers': list(labels.values()), 'issues': list(dict.fromkeys(issues)),
        'turns': [{**x, 'speaker': labels[x['speaker']]} for x in spans]}}


def require_diarization(document):
    evidence = document.get('diarization') or {}
    if evidence.get('policy') != POLICY or evidence.get('status') != 'complete':
        raise ContractError('speaker_review_required', 'diarization',
            'Run WhisperX with pyannote speaker diarization; resolve missing or overlapping speaker labels before generating voices.')
    allowed = evidence.get('speakers') or []
    for passage in document.get('passages', document.get('segments', [])):
        if passage.get('text', '').strip() and (passage.get('speaker') not in allowed or
                any(w.get('speaker') != passage['speaker'] or w.get('speaker_status') != 'assigned'
                    for w in passage.get('words', [])) or not passage.get('words')):
            raise ContractError('speaker_review_required', 'words', 'Every spoken word needs a verified speaker label.')
    return evidence
