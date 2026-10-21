"""The group-chat director only ever advises; every doubtful answer means "end"."""

from __future__ import annotations

import asyncio

import pytest

from maya.conversation.director import Candidate, Director

MEMBERS = [Candidate("primary", "מאיה"), Candidate("lila", "לילה")]


class _LLM:
    def __init__(self, answer=None, error: Exception | None = None, delay: float = 0.0):
        self.answer, self.error, self.delay = answer, error, delay
        self.prompts: list[str] = []
        self.kwargs: list[dict] = []

    async def chat_json(self, messages, **kwargs):
        self.prompts.append(messages[0]["content"])
        self.kwargs.append(kwargs)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return self.answer


async def _ask(llm, last_slot="primary", timeout_s=6.0):
    return await Director(llm, timeout_s=timeout_s).next_speaker(
        transcript=[("עידן", "היי"), ("מאיה", "לילה, מה את אומרת?")],
        members=MEMBERS,
        last_slot=last_slot,
        user_name="עידן",
        addressed_slots=["primary"],
    )


async def test_a_valid_choice_is_returned():
    llm = _LLM({"next": "lila", "reason": "asked directly"})
    assert await _ask(llm) == "lila"
    assert llm.kwargs[0]["model_tier"] == "fast"
    assert llm.kwargs[0]["purpose"] == "group_director"
    assert "[מאיה]: לילה, מה את אומרת?" in llm.prompts[0]


@pytest.mark.parametrize(
    "answer",
    [{"next": "end"}, {"next": "primary"}, {"next": "somebody"}, {}, None],
)
async def test_end_the_last_speaker_and_nonsense_all_mean_end(answer):
    assert await _ask(_LLM(answer)) is None


async def test_a_failing_call_means_end():
    assert await _ask(_LLM(error=ValueError("bad json"))) is None


async def test_a_slow_call_means_end():
    assert await _ask(_LLM({"next": "lila"}, delay=0.2), timeout_s=0.01) is None


async def test_no_candidates_skips_the_call():
    llm = _LLM({"next": "lila"})
    result = await Director(llm).next_speaker(
        transcript=[],
        members=[Candidate("lila", "לילה")],
        last_slot="lila",
        user_name="עידן",
        addressed_slots=[],
    )
    assert result is None
    assert llm.prompts == []
