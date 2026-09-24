"""Presentation grouping for validated replacement-narration word cues.

Never estimates word timing, drops words, or changes the spoken text. The
renderer must use the shared bold, padded caption layout.
"""
import re

from ..domain.errors import ContractError
from .caption_style import caption_font, line_width, MAX_LINE_WIDTH


def fits_line(text, max_chars=22, *, font_path=None):
    return len(text) <= max_chars and line_width(text, font_path) <= MAX_LINE_WIDTH


def phrase_cues(cues, spoken_text, start_frame, end_frame, *, max_chars=22,
                max_words=6):
    if not cues or max_chars < 1 or max_words < 1:
        raise ContractError('caption_coverage_invalid', 'cues')
    words = []
    previous_end = start_frame
    for cue in cues:
        start, end, word = cue.get('start_frame'), cue.get('end_frame'), cue.get('text')
        if (type(start) is not int or type(end) is not int
                or not previous_end <= start < end <= end_frame
                or not isinstance(word, str) or not word.strip()
                or len(word.split()) != 1):
            raise ContractError('caption_alignment_invalid', 'cues',
                                'Require ordered, nonoverlapping final narration words')
        if not fits_line(word, max_chars):
            raise ContractError('caption_word_too_wide', 'text',
                                'Revise the long word; do not shrink readable captions')
        words.append(word)
        previous_end = end
    if ' '.join(words).split() != spoken_text.split():
        raise ContractError('caption_text_mismatch', 'text',
                            'Caption words must cover the final spoken text exactly')

    output, group, lines = [], [], []

    def flush():
        if group:
            output.append({'start_frame': group[0]['start_frame'],
                           'end_frame': group[-1]['end_frame'],
                           'text': '\n'.join(lines),
                           'word_refs': [i for c in group for i in c.get('word_refs', [])]})
        group.clear()
        lines.clear()

    for cue in cues:
        word = cue['text']
        if group and (len(group) >= max_words or
                      (len(lines) == 2 and not fits_line(lines[-1] + ' ' + word, max_chars))):
            flush()
        if not lines:
            lines.append(word)
        elif fits_line(lines[-1] + ' ' + word, max_chars):
            lines[-1] += ' ' + word
        else:
            lines.append(word)
        group.append(cue)
        if re.search(r'[.!?][\"\u201d\u2019\']?$', word):
            flush()
    flush()
    return output
