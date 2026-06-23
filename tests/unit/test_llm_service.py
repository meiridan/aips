"""Spec §P1.3 [TEST]: fallback chain + cost logging. LiteLLM fully mocked."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from maya.llm.service import LLMService, LLMUnavailableError


def _fake_response(content: str, model: str) -> SimpleNamespace:
    """Mimic the shape of a litellm completion response."""
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        model=model,
    )


@pytest.fixture
def messages() -> list[dict]:
    return [{"role": "user", "content": "hello"}]


async def test_fallback_to_gpt_when_grok_fails(messages):
    """Grok raises -> service falls back to GPT and returns its content."""
    gpt_reply = _fake_response("hi from gpt", "openai/gpt-4o")

    async def side_effect(*, model, **kwargs):
        if model == "xai/grok-3":
            raise RuntimeError("grok down")
        if model == "openai/gpt-4o":
            return gpt_reply
        raise AssertionError(f"unexpected model {model}")

    with (
        patch("maya.llm.service.litellm.acompletion", new=AsyncMock(side_effect=side_effect)),
        patch("maya.llm.service.litellm.completion_cost", return_value=0.0012),
    ):
        out = await LLMService().chat(messages, model_tier="main")

    assert out == "hi from gpt"


async def test_all_models_fail_raises(messages):
    """Every model in the tier fails -> LLMUnavailableError."""
    with (
        patch(
            "maya.llm.service.litellm.acompletion",
            new=AsyncMock(side_effect=RuntimeError("provider down")),
        ),
        patch("maya.llm.service.litellm.completion_cost", return_value=0.0),
    ):
        with pytest.raises(LLMUnavailableError):
            await LLMService().chat(messages, model_tier="main")


async def test_cost_logged_once_per_successful_call(messages):
    """Exactly one cost log line ('llm_call') fires on a successful call."""
    reply = _fake_response("ok", "xai/grok-3")

    with (
        patch("maya.llm.service.litellm.acompletion", new=AsyncMock(return_value=reply)),
        patch("maya.llm.service.litellm.completion_cost", return_value=0.0034),
        patch("maya.llm.service.log") as mock_log,
    ):
        out = await LLMService().chat(messages, model_tier="main")

    assert out == "ok"
    info_events = [c.args[0] for c in mock_log.info.call_args_list]
    assert info_events.count("llm_call") == 1
    # Cost was actually recorded in that log call.
    _, kwargs = mock_log.info.call_args
    assert kwargs["cost_usd"] == 0.0034
    assert kwargs["model"] == "xai/grok-3"
