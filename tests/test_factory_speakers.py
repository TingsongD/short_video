"""No models, network, credentials or paid providers in speaker regressions."""
import copy
from types import SimpleNamespace

import pytest

from modules.factory.analysis.speakers import label_words, require_diarization
from modules.factory.autorun.dialogue import prepare_analysis, cast_voices, synthesis_key
from modules.factory.domain.errors import ContractError


def sample():
    return {'language': 'en', 'segments': [{'text': 'Hello. Hello. Goodbye.', 'start': 0, 'end': 3,
        'words': [{'word': 'Hello.', 'start': .1, 'end': .6},
                  {'word': 'Hello.', 'start': 1.1, 'end': 1.6},
                  {'word': 'Goodbye.', 'start': 2.1, 'end': 2.6}]}]}


def diarized():
    return label_words(sample(), [
        {'start': 0., 'end': .9, 'speaker': 'raw-B'},
        {'start': 1., 'end': 1.9, 'speaker': 'raw-A'},
        {'start': 2., 'end': 3., 'speaker': 'raw-B'}])


def test_word_speaker_changes_split_a_single_whisper_segment_and_returning_character():
    result = diarized()
    assert require_diarization(result)['speakers'] == ['SPEAKER_00', 'SPEAKER_01']
    assert [s['speaker'] for s in result['segments']] == ['SPEAKER_00', 'SPEAKER_01', 'SPEAKER_00']
    assert [s['text'] for s in result['segments']] == ['Hello.', 'Hello.', 'Goodbye.']


@pytest.mark.parametrize('intervals', [[], [{'start': 10., 'end': 11., 'speaker': 'wrong'}],
    [{'start': 0., 'end': 3., 'speaker': 'a'}, {'start': 0., 'end': 3., 'speaker': 'b'}]])
def test_missing_distant_or_overlapping_speech_cannot_be_assigned_by_nearest(intervals):
    result = label_words(sample(), intervals)
    assert result['diarization']['status'] == 'needs_review'
    with pytest.raises(ContractError, match='speaker_review_required'): require_diarization(result)


def test_no_silent_fallback_from_plain_stt():
    with pytest.raises(ContractError, match='speaker_review_required'): require_diarization(sample())


def test_missing_word_or_acoustic_time_requires_review():
    raw = sample(); raw['segments'][0]['words'].pop()
    assert label_words(raw, [])['diarization']['status'] == 'needs_review'
    raw = sample(); del raw['segments'][0]['words'][0]['start']
    with pytest.raises(ContractError): require_diarization(label_words(raw, []))


def test_source_scene_with_three_turns_preserves_speakers_scene_context_and_all_words():
    source = {'beats': [{'id': 'scene', 'role': 'hook', 'start_s': 0., 'end_s': 3.,
                         'visual_event': 'two people talking', 'confidence': 'clear'}],
              'creative_context': {'scenes': [{'beat_id': 'scene', 'cast': ['person-a', 'person-b']}], 'roles': []}}
    before = copy.deepcopy(source)
    payload, owners = prepare_analysis(source, diarized()['segments'])
    assert source == before
    assert list(owners.values()) == ['SPEAKER_00', 'SPEAKER_01', 'SPEAKER_00']
    assert len(payload['beats']) == 3
    assert payload['beats'][0]['start_s'] == 0 and payload['beats'][-1]['end_s'] == 3
    assert all(a['end_s'] == b['start_s'] for a, b in zip(payload['beats'], payload['beats'][1:]))
    assert sum(len(p['words']) for p in payload['transcript']) == 3
    assert [s['beat_id'] for s in payload['creative_context']['scenes']] == [b['id'] for b in payload['beats']]


def test_mixed_speaker_passage_cannot_use_majority_speaker():
    passages = diarized()['segments']; passages[0]['words'][0]['speaker'] = 'SPEAKER_01'
    with pytest.raises(ContractError, match='speaker_review_required'):
        prepare_analysis({'beats': []}, passages)


def test_distinct_cast_is_stable_and_explicit_mapping_wins():
    speakers = ['SPEAKER_00', 'SPEAKER_01']
    catalog = [{'voice_id': 'voice-c'}, {'voice_id': 'voice-b'}, {'voice_id': 'voice-a'}]
    assert cast_voices(speakers, 'voice-a', {}, catalog) == {'SPEAKER_00': 'voice-a', 'SPEAKER_01': 'voice-b'}
    assert cast_voices(speakers, 'voice-a', {'SPEAKER_01': 'voice-c'}, catalog)['SPEAKER_01'] == 'voice-c'
    with pytest.raises(ContractError, match='distinct_speaker_voices_required'):
        cast_voices(speakers, 'voice-a', dict.fromkeys(speakers, 'voice-a'))
    with pytest.raises(ContractError, match='speaker_voices_required'): cast_voices(speakers, 'voice-a', {})


def test_identical_words_different_characters_never_share_synthesis_cache():
    run = SimpleNamespace(params={'speaker_policy': 'whisperx-pyannote.v1', 'voice_id': 'a', 'language': 'en'})
    speech = SimpleNamespace(normalize=lambda s: s.strip())
    first = {'copy': 'Hello', 'voice_id': 'a'}; other = {'copy': 'Hello', 'voice_id': 'b'}
    assert synthesis_key(speech, first, run) != synthesis_key(speech, other, run)
    assert synthesis_key(speech, first, run) == synthesis_key(speech, copy.deepcopy(first), run)


def test_analysis_parser_keeps_speaker_evidence():
    from modules.factory.analysis.analyzer import parse_analysis
    payload, _ = prepare_analysis({'beats': [{'id':'b', 'role':'hook', 'confidence':'uncertain',
        'start_s':0., 'end_s':3., 'visual_event':'dialogue'}]}, diarized()['segments'])
    result = parse_analysis(payload)
    assert [p['speaker'] for p in result['transcript']] == ['SPEAKER_00', 'SPEAKER_01', 'SPEAKER_00']
    assert all(w['speaker_status'] == 'assigned' for p in result['transcript'] for w in p['words'])
