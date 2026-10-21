"""Group chat floor control: does anyone speak again before the user does?

After the addressed companions answer, the room may keep going on its own — one
of them teases the other, or answers a question the other just asked her. That
decision is a cheap fast-tier JSON call, never the main model, and its answer is
advisory: the caller still enforces the hard caps (no speaker twice in a row, a
per-turn message ceiling), so a confused director cannot start a loop.

Any failure — timeout, bad JSON, an unknown slot — means "end": the user gets
the next word, which is always a safe outcome.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass

from maya.llm.service import LLMService
from maya.logging import get_logger

log = get_logger("maya.director")

END = "end"

# How much of the room the director reads. It only needs the last beat.
_WINDOW = 12
_LINE_CHARS = 400

DIRECTOR_PROMPT = """You are directing a group chat. {user_name} is talking with {companion_names}.

RECENT CONVERSATION (oldest first):
{transcript}

In {user_name}'s last message he spoke to: {addressed}.
{last_name} spoke last, so she cannot speak again right now.
Companions who may speak next: {candidates}.

Decide whether ONE of those companions would naturally send one more message right now, \
before {user_name} replies.
Pick a companion only if:
- someone in the room just asked her something or spoke to her directly, or
- she has a short, genuinely natural reaction to what was just said (a tease, a joke, \
agreeing or disagreeing with her friend) that keeps the scene alive.
Otherwise choose end — {user_name} should get the next word. When in doubt, choose end. \
If {user_name} spoke to only one companion, choose end unless someone spoke to another companion.

Return JSON only: {{"next": "<one of: {slots}, or end>", "reason": "<a few words>"}}"""


@dataclass(frozen=True)
class Candidate:
    slot: str
    name: str


class Director:
    def __init__(self, llm: LLMService | None = None, timeout_s: float = 6.0) -> None:
        self.llm = llm or LLMService()
        self.timeout_s = timeout_s

    async def next_speaker(
        self,
        *,
        transcript: Sequence[tuple[str, str]],
        members: Sequence[Candidate],
        last_slot: str | None,
        user_name: str,
        addressed_slots: Sequence[str],
    ) -> str | None:
        """The slot of whoever speaks next, or None for "the user's turn".

        `transcript` is (speaker name, text) pairs, oldest first.
        """
        candidates = [m for m in members if m.slot != last_slot]
        if not candidates:
            return None
        by_slot = {m.slot: m for m in members}
        lines = [
            f"[{name}]: {' '.join(text.split())[:_LINE_CHARS]}"
            for name, text in list(transcript)[-_WINDOW:]
        ]
        last = by_slot.get(last_slot or "")
        prompt = DIRECTOR_PROMPT.format(
            user_name=user_name,
            companion_names=" and ".join(m.name for m in members),
            transcript="\n".join(lines) or "(nothing yet)",
            addressed=", ".join(by_slot[s].name for s in addressed_slots if s in by_slot)
            or "everyone",
            last_name=last.name if last else "Nobody",
            candidates=", ".join(f"{m.name} ({m.slot})" for m in candidates),
            slots=", ".join(m.slot for m in candidates),
        )
        try:
            raw = await asyncio.wait_for(
                self.llm.chat_json(
                    messages=[{"role": "user", "content": prompt}],
                    model_tier="fast",
                    purpose="group_director",
                    max_tokens=120,
                    temperature=0.3,
                ),
                timeout=self.timeout_s,
            )
        except Exception as exc:  # noqa: BLE001 - "end" is always a safe answer
            log.warning("director_fallback", error=str(exc))
            return None

        choice = str((raw or {}).get("next", END)).strip().lower()
        if choice == END:
            return None
        if choice not in {m.slot for m in candidates}:
            log.warning("director_invalid_choice", choice=choice)
            return None
        return choice
