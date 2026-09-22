"""Associate independent measured events without fabricating semantic labels."""
from bisect import bisect_left
from fractions import Fraction
from ..domain.errors import ContractError


def visual_recurrences(frames, embeddings):
    """Compare change positions against prior shot/context anchors, not cast IDs."""
    import numpy as np
    anchors, vectors, repeated = [], [], []
    for frame, vector in zip(frames, embeddings):
        time = Fraction(frame['source_time'])
        changed = frame.get('change',0) >= .12 or frame.get('novelty',0) >= .18
        if changed and vectors:
            eligible = [i for i, a in enumerate(anchors) if time-Fraction(a['source_time']) >= 1]
            if eligible:
                scores = np.asarray([vectors[i] for i in eligible],dtype=np.float32) @ np.asarray(vector,dtype=np.float32)
                winner = int(np.argmax(scores))
                if float(scores[winner]) >= .985:
                    repeated.append({'frame_index':frame['index'], 'earlier_frame_index':anchors[eligible[winner]]['index'],
                                     'similarity':float(scores[winner]), 'claim':'visual_resemblance_only'})
        if not anchors or changed or time-Fraction(anchors[-1]['source_time']) >= 1:
            anchors.append(frame)
            vectors.append(vector)
    return repeated


def fuse_events(frames, audio_events, *, audio_origin='0', duration, recurrences=()):
    if not frames or [f['index'] for f in frames] != list(range(len(frames))):
        raise ContractError('coverage_incomplete', 'frames')
    times = [Fraction(f['source_time']) for f in frames]
    duration = Fraction(duration)
    if any(b < a for a, b in zip(times, times[1:])) or duration <= times[-1]:
        raise ContractError('invalid_frame_order', 'source_time')
    selected, candidates, optional_seconds = set(), [], set()
    def add(ident, kind, position, mandatory, support):
        position = Fraction(position)
        idx = min(len(times)-1, bisect_left(times, position))
        neighbours = sorted(set([max(0, idx-1), idx, min(len(times)-1, idx+1)]))
        if mandatory:
            selected.update(neighbours)
        elif int(position) not in optional_seconds:
            # Dense acoustic peaks are not visual boundaries. Retain EVERY
            # measured event and its audio-bearing context, but use one exact
            # representative still per second for optional acoustic cues.
            # Jev shadow advice cannot alter this deterministic baseline.
            selected.add(idx)
            optional_seconds.add(int(position))
        candidates.append({'id': ident, 'kind': kind, 'source_time': str(position),
                           'context_start': str(max(Fraction(0), position-Fraction(1, 2))),
                           'context_end': str(min(duration, position+Fraction(1, 2))),
                           'frame_indices': neighbours, 'mandatory': mandatory, 'support': support})
    add('coverage:first', 'context', times[0], True, ['opening'])
    add('coverage:last', 'context', times[-1], True, ['ending'])
    for second in range(2, int(duration)+1, 2):
        if second < duration:
            add(f'coverage:{second}', 'context', Fraction(second), True, ['baseline_coverage'])
    for frame in frames:
        if frame.get('change', 0) >= .12 or frame.get('novelty', 0) >= .18:
            add(f'visual:{frame["index"]}', 'visual_change_candidate', frame['source_time'], True,
                ['pixel_change' if frame.get('change', 0) >= .12 else 'embedding_novelty'])
    for repeat in recurrences:
        index = repeat['frame_index']
        add(f'recurrence:{index}', 'recurrence_candidate', frames[index]['source_time'], True,
            [f"resembles_frame:{repeat['earlier_frame_index']}", 'not_character_verification'])
    for event in audio_events:
        position = Fraction(audio_origin) + Fraction(event['sample'], event['sample_rate'])
        if 0 <= position < duration and event['kind'] != 'low_energy':
            add('audio:'+event['id'], event['kind'], position, False, event.get('support', []))
    return {'version': 'av_fusion.v1', 'optional_still_policy':'one_per_second.v1',
            'candidates': sorted(candidates, key=lambda c: (Fraction(c['source_time']), c['id'])),
            'selected_frame_indices': sorted(selected), 'duration': str(duration), 'recurrences': list(recurrences)}
