"""Group room settings: reply length and talk mode, picked in the room's UI.

Stored on `conversations.settings`. The /ws/group socket holds one instance and
hands the same object to every turn it runs, so a toggle that arrives while the
companions are talking is seen at the orchestrator's next speaker check — which
is why this is mutable.

- `response_length` 1–3: short / medium / long, as a sentence count rather than
  the 1:1 chat's word target (`response_length.group_length_for`).
- `talk_mode`: "moderated" — they go back and forth a few lines, then wait for
  the user; "free" — they keep talking to each other until the user writes.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from maya.conversation import response_length

MODE_MODERATED = "moderated"
MODE_FREE = "free"
TALK_MODES = frozenset({MODE_MODERATED, MODE_FREE})

# A group moves fast: short unless the user asks for more.
DEFAULT_LENGTH = 1


@dataclass
class GroupSettings:
    response_length: int = DEFAULT_LENGTH
    talk_mode: str = MODE_MODERATED

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> GroupSettings:
        settings = cls()
        settings.apply(raw or {})
        return settings

    def apply(self, patch: dict[str, Any]) -> bool:
        """Take the valid keys of a client patch, ignore the rest.

        Returns whether anything changed."""
        before = self.as_dict()
        length = patch.get("response_length")
        if isinstance(length, int | str) and not isinstance(length, bool):
            parsed = response_length.parse(str(length))
            if parsed is not None:
                self.response_length = parsed
        mode = patch.get("talk_mode")
        if isinstance(mode, str) and mode in TALK_MODES:
            self.talk_mode = mode
        return self.as_dict() != before

    @property
    def free(self) -> bool:
        return self.talk_mode == MODE_FREE

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
