"""Keep acoustic speaker turns intact through scene planning and synthesis."""
import copy
import math
import re

from ..domain.errors import ContractError
from ..domain.records import content_hash
from .source_timing import bounds, tokens


def validate_voice_map(value):
    if not isinstance(value, dict) or len(value) > 32 or any(
            not re.fullmatch(r'SPEAKER_\d{2}', str(k)) or not isinstance(v, str)
            or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', v) for k, v in value.items()):
        raise ContractError('invalid_speaker_voices', 'speaker_voices')
    if len(set(value.values())) != len(value):
        raise ContractError('distinct_speaker_voices_required', 'speaker_voices')
    return dict(value)


def cast_voices(speakers, primary, supplied, catalog=None):
    mapping = validate_voice_map(supplied)
    if set(mapping) - set(speakers):
        raise ContractError('unknown_speaker', 'speaker_voices')
    if not speakers:
        return {}
    if speakers[0] not in mapping and primary not in mapping.values():
        mapping[speakers[0]] = primary
    pool = sorted({v['voice_id'] for v in (catalog or [])
                   if isinstance(v, dict) and re.fullmatch(r'[A-Za-z0-9_-]{1,64}', str(v.get('voice_id', '')))})
    for speaker in speakers:
        if speaker not in mapping:
            choice = next((voice for voice in pool if voice not in mapping.values()), None)
            if not choice:
                raise ContractError('speaker_voices_required', 'speaker_voices',
                    'Assign a distinct available voice to every detected speaker.')
            mapping[speaker] = choice
    return mapping


def prepare_analysis(payload, transcript, fps=30):
    """Subdivide visual beats only at speaker changes, preserving scene evidence.

    A scene may contain multiple turns. Each resulting speech/visual segment
    has one speaker; copy adaptation cannot flatten a conversation into one
    narrator. Turns and words remain source evidence in this run-owned view.
    """
    words = []
    for passage in transcript:
        speaker = passage.get('speaker')
        if not isinstance(speaker, str) or not re.fullmatch(r'SPEAKER_\d{2}', speaker):
            raise ContractError('speaker_review_required', 'transcript')
        if tokens(' '.join(w.get('text', w.get('word', '')) for w in passage.get('words', []))) != tokens(passage['text']):
            raise ContractError('speaker_review_required', 'word_coverage')
        for raw in passage.get('words', []):
            start, end = bounds(raw)
            if (raw.get('speaker') != speaker or raw.get('speaker_status') != 'assigned'
                    or type(start) not in (int, float) or type(end) not in (int, float)
                    or not math.isfinite(start) or not math.isfinite(end) or not 0 <= start < end):
                raise ContractError('speaker_review_required', 'word')
            if words and start < words[-1]['end_s'] - 1e-6:
                raise ContractError('speaker_overlap_review_required', 'words')
            words.append({'text': raw.get('text', raw.get('word', '')), 'start_s': start,
                          'end_s': end, 'speaker': speaker, 'speaker_status': 'assigned'})
    cuts = []
    scene_edges = sorted({b['start_s'] for b in payload['beats']} | {b['end_s'] for b in payload['beats']})
    for left, right in zip(words, words[1:]):
        if left['speaker'] != right['speaker']:
            existing = [x for x in scene_edges if left['end_s'] <= x <= right['start_s']]
            cut = (existing[0] if existing else
                   round((left['end_s'] + right['start_s']) * fps / 2) / fps)
            if not left['end_s'] - 1/fps <= cut <= right['start_s'] + 1/fps:
                raise ContractError('speaker_boundary_unreliable', 'turn')
            cuts.append(cut)
    result = copy.deepcopy(payload)
    beats, origins, assigned, owner = [], {}, [], {}
    for beat in payload['beats']:
        edges = [beat['start_s']] + [x for x in cuts if beat['start_s'] < x < beat['end_s']] + [beat['end_s']]
        for i, (start, end) in enumerate(zip(edges, edges[1:])):
            if round(end*fps) <= round(start*fps):
                raise ContractError('speaker_boundary_unreliable', 'beat')
            bid = beat['id'] if len(edges) == 2 else f"{beat['id']}-speaker-{i}"
            beats.append({**beat, 'id': bid, 'start_s': start, 'end_s': end})
            origins[bid] = beat['id']
            selected = [w for w in words if start <= (w['start_s']+w['end_s'])/2 < end]
            labels = {w['speaker'] for w in selected}
            if len(labels) > 1:
                raise ContractError('speaker_boundary_unreliable', bid)
            if selected:
                owner[bid] = selected[0]['speaker']
                assigned.append({'id': 'dialogue-'+bid, 'start_s': selected[0]['start_s'],
                    'end_s': selected[-1]['end_s'], 'speaker': selected[0]['speaker'],
                    'text': ' '.join(w['text'] for w in selected), 'words': selected})
    if sum(len(p['words']) for p in assigned) != len(words):
        raise ContractError('speaker_words_unplaced', 'beats')
    result.update(beats=beats, transcript=assigned)
    if result.get('creative_context'):
        context = result['creative_context']
        scenes = {s['beat_id']: s for s in context['scenes']}
        context['scenes'] = [{**copy.deepcopy(scenes[origins[b['id']]]), 'beat_id': b['id']} for b in beats]
        context.pop('content_hash', None)
    return result, owner


def segment_voice(segment, fallback):
    return segment.get('voice_id') or fallback


def synthesis_key(speech, segment, run):
    text = speech.normalize(segment['copy'])
    if not run.params.get('speaker_policy'):
        return text
    return content_hash({'text': text, 'voice_id': segment_voice(segment, run.params['voice_id']),
                         'model': 'eleven_v3', 'language': run.params['language'], 'settings': {}})
