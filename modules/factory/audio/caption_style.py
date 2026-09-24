"""Shared phone-readable caption geometry, in a 720px-wide design space."""
from functools import lru_cache
from pathlib import Path

from ..domain.errors import ContractError

BASE_WIDTH = 720
FONT_SIZE = 48
LINE_HEIGHT = 1.2
BOX_WIDTH = .8
BOTTOM = .78
PAD_X = 16
PAD_Y = 10
RADIUS = 10
FILL = '#FFFFFF'
BACKGROUND = '#000000CC'
# Leave a small shaping allowance inside the padded box. Measure the bold
# face used in the export, not the narrower regular face.
MAX_LINE_WIDTH = BASE_WIDTH * BOX_WIDTH - 2 * PAD_X - 6
STYLE_VERSION = 'readable-captions.v2'


def font_path(preferred=None):
    if preferred and Path(preferred).is_file():
        return Path(preferred)
    for name in ('/System/Library/Fonts/Supplemental/Arial Bold.ttf',
                 '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'):
        path = Path(name)
        if path.is_file():
            return path
    raise ContractError('caption_font_required', 'font_path')


@lru_cache(maxsize=8)
def caption_font(preferred=None):
    from PIL import ImageFont
    return ImageFont.truetype(str(font_path(preferred)), FONT_SIZE)


def line_width(text, preferred=None):
    # Fine Caption lays out individual words; summing their advances avoids
    # accepting a line that only fits with cross-word kerning.
    font = caption_font(preferred)
    return sum(font.getlength(word) for word in text.split(' ')) + text.count(' ') * font.getlength(' ')
