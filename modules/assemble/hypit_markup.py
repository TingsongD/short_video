"""Serialize literal text for Hypit's structured markup bodies."""
from xml.sax.saxutils import escape


def escape_markup_text(text: str) -> str:
    """Escape caption or title copy before inserting it into structured SVML."""
    # Hypit 0.1.8 decodes the five named XML entities, not HTML's &#x27;.
    return escape(text, {"'": "&apos;", '"': "&quot;"})
