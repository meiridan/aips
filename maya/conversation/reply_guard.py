"""Stops one companion's streamed reply from speaking for anyone else.

In a group prompt the model sees "[לילה]: …" lines, and a model left to its own
devices will happily continue the script: Maya's reply, a newline, then
"לילה: …" in Lila's voice. The prompt forbids it; this enforces it on the wire.

Streaming makes it fiddly — the marker can arrive split across chunks — so the
guard holds back only the text that could still turn out to be a marker (the
start of the reply, and whatever follows the last newline) and releases the
rest immediately.
"""

from __future__ import annotations

import re
from collections.abc import Iterable


class ReplyGuard:
    def __init__(self, own_name: str, other_names: Iterable[str]) -> None:
        self._own = [f"[{own_name}]:", f"{own_name}:"]
        self._others = [m for n in other_names if n for m in (f"[{n}]:", f"{n}:")]
        names = "|".join(re.escape(n) for n in [own_name, *other_names] if n)
        # A speaker marker at the start of a later line ends her message.
        self._cut = re.compile(rf"\n[ \t]*\[?(?:{names})\]?:") if names else None
        self._markers = self._own + self._others
        self._longest = max((len(m) for m in self._markers), default=0)
        self._buf = ""
        self._started = False
        self.stopped = False

    def feed(self, piece: str) -> str:
        """Add a chunk; return the text that is now safe to show."""
        if self.stopped:
            return ""
        self._buf += piece
        if not self._started and not self._resolve_start():
            return ""
        return self._release(final=False)

    def finish(self) -> str:
        """End of stream: whatever is still held back is safe now."""
        if self.stopped:
            return ""
        if not self._started:
            self._resolve_start(final=True)
            if self.stopped:
                return ""
        return self._release(final=True)

    # ── internals ────────────────────────────────────────────────────────

    def _resolve_start(self, final: bool = False) -> bool:
        """Decide what the reply opens with. False = not enough text yet."""
        head = self._buf.lstrip()
        if not final and self._could_become_marker(head):
            return False
        for marker in self._others:
            if head.startswith(marker):
                # She opened by writing someone else's line: nothing of hers to show.
                self.stopped = True
                self._buf = ""
                return False
        for marker in self._own:
            if head.startswith(marker):
                head = head[len(marker) :].lstrip()
                break
        self._buf = head
        self._started = True
        return True

    def _could_become_marker(self, text: str) -> bool:
        if len(text) >= self._longest:
            return False
        return any(m.startswith(text) for m in self._markers)

    def _release(self, final: bool) -> str:
        if self._cut is not None:
            match = self._cut.search(self._buf)
            if match:
                out = self._buf[: match.start()]
                self._buf = ""
                self.stopped = True
                return out
        if final:
            out, self._buf = self._buf, ""
            return out
        newline = self._buf.rfind("\n")
        if newline == -1:
            out, self._buf = self._buf, ""
            return out
        tail = self._buf[newline + 1 :].lstrip(" \t")
        if tail and not self._could_become_marker(tail):
            out, self._buf = self._buf, ""
            return out
        out, self._buf = self._buf[:newline], self._buf[newline:]
        return out
