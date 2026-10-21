"""Who a group-chat message is for.

The rule the product asks for: a message that opens with a companion's name is
for her alone; one that opens with several names is for those; anything else is
for everyone in the room. An explicit target from the UI (the "to whom" chips)
always wins over the text, because it is the one signal that cannot be misread.

Pure and synchronous on purpose — this sits on the critical path and is the
piece most worth pinning down with plain unit tests.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

#: Explicit target meaning "everyone in the room".
TARGET_ALL = "all"

# Hebrew names that are also everyday words. "לילה טוב" is "good night", not
# "Lila, good"; "אור" is "light", "טל" is "dew". Such a name only counts as a
# vocative when something marks it as one: punctuation right after it, an `@`,
# another name joined to it, or the name being the whole message.
COMMON_WORD_NAMES = frozenset({"לילה", "אור", "טל", "שחר", "גל", "ים", "חן", "שקד"})

# A leading greeting is skipped, so "היי מאיה" still addresses Maya.
_GREETINGS = frozenset({"היי", "הי", "אהלן", "שלום", "יו", "hey", "hi", "hello", "yo"})
_JOINER_WORDS = frozenset({"and", "&", "+"})
_TRAILING_PUNCT = ",:!?.;،-–—"
_NIKUD = re.compile("[֑-ׇ]")


@dataclass(frozen=True)
class Addressable:
    """A room member as the router sees her: an id, a slot and her names."""

    companion_id: uuid.UUID
    slot: str
    names: tuple[str, ...]


def normalize(word: str) -> str:
    """Casefold and drop Hebrew vowel marks, so "מָאיָה" and "Maya" compare cleanly."""
    return _NIKUD.sub("", word).casefold().strip()


def resolve_addressees(
    text: str,
    members: Sequence[Addressable],
    target: str | None = None,
) -> list[uuid.UUID]:
    """The companion ids this message is for, in the order they were named.

    `target` is the UI's explicit choice: a member slot, or `TARGET_ALL`. An
    unknown slot is ignored rather than trusted, and the text decides instead.
    """
    everyone = [m.companion_id for m in members]
    if target:
        if target == TARGET_ALL:
            return everyone
        for member in members:
            if member.slot == target:
                return [member.companion_id]
    return _leading_names(text, members) or everyone


def _split_punct(token: str) -> tuple[str, str]:
    core = token.rstrip(_TRAILING_PUNCT)
    return core, token[len(core) :]


def _match(word: str, members: Sequence[Addressable]) -> Addressable | None:
    key = normalize(word)
    if not key:
        return None
    for member in members:
        if any(normalize(name) == key for name in member.names):
            return member
    return None


def _name_in(token: str, members: Sequence[Addressable]) -> tuple[Addressable | None, bool]:
    """(member, joined) for one token. `joined` marks the Hebrew "ו" prefix — "ולילה"."""
    core = _split_punct(token)[0].lstrip("@")
    member = _match(core, members)
    if member is None and len(core) > 1 and core[0] == "ו":
        member = _match(core[1:], members)
        return member, member is not None
    return member, False


def _leading_names(text: str, members: Sequence[Addressable]) -> list[uuid.UUID]:
    tokens = text.split()
    i = 0
    if len(tokens) > 1 and normalize(_split_punct(tokens[0])[0]) in _GREETINGS:
        i = 1

    found: list[uuid.UUID] = []
    while i < len(tokens):
        token = tokens[i]
        core, punct = _split_punct(token)
        if found and normalize(core) in _JOINER_WORDS:
            i += 1
            continue

        member, joined = _name_in(token, members)
        if member is None:
            break

        bare = core.lstrip("@")
        if joined:
            bare = bare[1:]
        if normalize(bare) in COMMON_WORD_NAMES:
            is_last = i == len(tokens) - 1
            next_is_name = not is_last and (
                _name_in(tokens[i + 1], members)[0] is not None
                or normalize(_split_punct(tokens[i + 1])[0]) in _JOINER_WORDS
            )
            marked = core.startswith("@") or bool(punct) or joined or is_last or next_is_name
            if not marked:
                break

        if member.companion_id not in found:
            found.append(member.companion_id)
        i += 1
    return found
