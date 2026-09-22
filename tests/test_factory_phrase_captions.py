import pytest

from modules.factory.audio.phrase_captions import phrase_cues
from modules.factory.domain.errors import ContractError


def words(text):
    return [{'start_frame': i * 10, 'end_frame': i * 10 + 9,
             'text': w, 'word_refs': [i]} for i, w in enumerate(text.split())]


def test_phrases_preserve_every_word_timing_and_punctuation():
    text = 'Look at this horse! He has stolen the entire basket.'
    cues = words(text)
    result = phrase_cues(cues, text, 0, 120)
    assert result[0]['text'] == 'Look at this horse!'
    assert result[0]['start_frame'] == 0 and result[0]['end_frame'] == 39
    assert ' '.join(c['text'].replace('\n', ' ') for c in result) == text
    assert [i for c in result for i in c['word_refs']] == list(range(len(cues)))
    assert all(len(c['text'].splitlines()) <= 2 for c in result)
    assert all(len(line) <= 22 for c in result for line in c['text'].splitlines())


@pytest.mark.parametrize('failure', ['overlap', 'reversed', 'outside', 'missing', 'long'])
def test_unreliable_alignment_fails_closed(failure):
    text = 'The horse runs.'
    cues = words(text)
    if failure == 'overlap': cues[1]['start_frame'] = 0
    if failure == 'reversed': cues[0]['end_frame'] = -1
    if failure == 'outside': cues[-1]['end_frame'] = 1000
    if failure == 'missing': cues.pop()
    if failure == 'long':
        text = 'x' * 30
        cues = words(text)
    with pytest.raises(ContractError):
        phrase_cues(cues, text, 0, 30)


def test_phrase_ass_is_large_outlined_and_escapes_only_trusted_linebreaks():
    from modules.factory.rendering.ffmpeg_fast import captions_ass
    cue = {'start_frame': 0, 'end_frame': 30, 'text': 'Look at this\nhorse!'}
    rendered = captions_ass([cue], preset='phrases.v1')
    assert 'Arial,72,' in rendered
    assert r'Look at this\Nhorse!' in rendered
    assert ',1,3,2,8,86,86,0,1' in rendered
    with pytest.raises(ValueError):
        captions_ass([cue])  # Legacy ASS input restrictions remain unchanged.
    for text in (r'{\pos(0,0)}bad', 'a\nb\nc', 'x' * 23):
        with pytest.raises(ValueError):
            captions_ass([{**cue, 'text': text}], preset='phrases.v1')


def test_wide_glyphs_split_phrases_at_readable_size_without_overflow():
    from modules.factory.audio.phrase_captions import caption_font
    text = 'WOWWW WWWWW WWWWW WWWWW WOWWW.'
    result = phrase_cues(words(text), text, 0, 60)
    font = caption_font()
    assert all(font.getlength(line) <= 600 for cue in result for line in cue['text'].splitlines())
    assert ' '.join(c['text'].replace('\n', ' ') for c in result) == text


def test_provider_character_timing_uses_the_text_actually_synthesized(tmp_path):
    from modules.factory.audio.alignment import AlignmentService
    from modules.factory.domain.clocks import RationalRate
    from modules.factory.store import Database
    text = 'The 3 dogs!'
    raw = {'characters': list(text),
           'character_start_times_seconds': [i * .1 for i in range(len(text))],
           'character_end_times_seconds': [(i + 1) * .1 for i in range(len(text))]}
    speech = {'text': 'The three dogs!', 'source_text': text,
              'audio_sha256': 'a' * 64, 'duration_s': 3,
              'raw_duration_s': 1.1, 'raw_audio_sha256': 'b' * 64,
              'raw_alignment': raw, 'status': 'fitted', 'speech_hash': 'c' * 64,
              'target': {'start_frame': 0, 'end_frame': 90},
              'fit': {'fits': True, 'rate': 1, 'pad_s': 1.9, 'trim_s': 0}}
    db = Database(tmp_path / 'alignment.db')
    align = AlignmentService(db, None)
    align.align('spoken', lambda _: speech, now='2026-09-20T00:00:00Z')
    caps = align.captions('spoken', lambda _: speech, speech['fit'], RationalRate(30, 1),
                          speech['speech_hash'], preset='phrases.v1', now='2026-09-20T00:00:00Z')
    assert ' '.join(c['text'] for c in caps.cues) == text
    db.close()
