"""Response-length setting: a 1–3 knob controlling how long Maya's replies are.

Single source of truth for the level → word-target and level → max_tokens
mappings, plus parsing of user input (Telegram `/length …`, web control). Level
is stored per-companion (Companion.response_length) and applied every turn: the
word target shapes the system prompt, the max_tokens is a hard safety cap with
headroom above the target so replies aren't truncated mid-sentence.
"""

from __future__ import annotations

DEFAULT = 2

# level → approximate target words shown to the model
_WORDS = {1: 100, 2: 300, 3: 1000}
# level → hard max_tokens cap (headroom above the word target)
_MAX_TOKENS = {1: 250, 2: 700, 3: 1600}
_LABELS = {1: "short", 2: "medium", 3: "long"}
_ALIASES = {"short": 1, "medium": 2, "long": 3, "1": 1, "2": 2, "3": 3}


def normalize(level: object) -> int:
    """Coerce anything to a valid level 1–3, falling back to DEFAULT.

    Accepts ints, numeric strings, and aliases ('short'/'medium'/'long')."""
    if isinstance(level, str):
        parsed = parse(level)
        if parsed is not None:
            return parsed
        return DEFAULT
    try:
        n = int(level)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT
    return n if n in _WORDS else DEFAULT


def words_for(level: object) -> int:
    return _WORDS[normalize(level)]


def max_tokens_for(level: object) -> int:
    return _MAX_TOKENS[normalize(level)]


def label(level: object) -> str:
    return _LABELS[normalize(level)]


def parse(text: str) -> int | None:
    """Parse a user-supplied level from '1'/'2'/'3' or 'short'/'medium'/'long'.

    Returns the level, or None if the input isn't a recognized value.
    """
    if not isinstance(text, str):
        return None
    return _ALIASES.get(text.strip().lower())
