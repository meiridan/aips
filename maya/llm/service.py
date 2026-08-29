"""LiteLLM wrapper with a tiered fallback chain (spec §P1.3)."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any

import litellm

from maya.logging import get_logger

log = get_logger("maya.llm")

# Disable SSL verification for litellm (workaround for cert issues)
litellm.ssl_verify = False

# Default sampling/reasoning knobs for the primary chat path.
DEFAULT_TEMPERATURE = 0.4
DEFAULT_REASONING_EFFORT = "low"

# Models that accept a `reasoning_effort` param. Sending it to a non-reasoning
# model (gpt-4o etc.) is a 400, which would burn a fallback slot for no reason.
REASONING_MODELS: frozenset[str] = frozenset({"xai/grok-4.5", "xai/grok-4.6"})

TIER_MODELS: dict[str, list[str]] = {
    "main": [
        # Chat path only. Claude is deliberately absent: it refuses the explicit
        # roleplay this app exists for, so falling over to it reads to the user
        # as the companion suddenly refusing.
        "xai/grok-4.5",  # primary
        "openai/gpt-4o",  # fallback 1
    ],
    "cheap": [
        "openai/gpt-4o-mini",
        "anthropic/claude-haiku-4-5-20251001",
    ],
    "fast": [
        # Non-reasoning on purpose: this tier backs moment analysis on the
        # critical path, where reasoning tokens cost ~3x the latency.
        "xai/grok-4.20-0309-non-reasoning",
        "openai/gpt-4o-mini",
    ],
}


class LLMUnavailableError(RuntimeError):
    """Raised when every model in a tier's fallback chain fails."""


class LLMService:
    """Single entry point for all LLM calls. Tries primary then fallbacks."""

    def __init__(self, tier_models: dict[str, list[str]] | None = None) -> None:
        self._tiers = tier_models or TIER_MODELS

    async def chat(
        self,
        messages: list[dict],
        model_tier: str = "main",
        json_mode: bool = False,
        max_tokens: int = 800,
        temperature: float = DEFAULT_TEMPERATURE,
        purpose: str = "main_response",
    ) -> str:
        """Try primary -> fallback 1 -> fallback 2. Raise LLMUnavailableError on all fail.

        Logs every successful call with model, token counts, cost, and latency.
        """
        models = self._tiers.get(model_tier)
        if not models:
            raise ValueError(f"Unknown model tier: {model_tier!r}")

        last_error: Exception | None = None
        for model in models:
            kwargs: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "timeout": 30,  # bound tail latency; a hung provider falls over to the next
            }
            if model in REASONING_MODELS:
                kwargs["reasoning_effort"] = DEFAULT_REASONING_EFFORT
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}

            started = time.perf_counter()
            try:
                response = await litellm.acompletion(**kwargs)
            except Exception as exc:  # noqa: BLE001 - any provider error -> next model
                last_error = exc
                log.warning(
                    "llm_call_failed",
                    model=model,
                    tier=model_tier,
                    purpose=purpose,
                    error=str(exc),
                )
                continue

            latency_ms = int((time.perf_counter() - started) * 1000)
            self._log_cost(response, model, model_tier, purpose, latency_ms)
            return response.choices[0].message.content or ""

        raise LLMUnavailableError(
            f"All models failed for tier {model_tier!r}: {last_error}"
        )

    async def chat_stream(
        self,
        messages: list[dict],
        model_tier: str = "main",
        max_tokens: int = 800,
        temperature: float = DEFAULT_TEMPERATURE,
        purpose: str = "main_response",
    ) -> AsyncIterator[str]:
        """Stream the reply token-by-token, trying primary then fallbacks.

        Fail-over only happens BEFORE the first token is emitted — once we've
        streamed any content to the caller we can't silently switch models, so a
        mid-stream failure raises LLMUnavailableError. Cost is logged after the
        stream completes by rebuilding the full response from the chunks.
        """
        models = self._tiers.get(model_tier)
        if not models:
            raise ValueError(f"Unknown model tier: {model_tier!r}")

        last_error: Exception | None = None
        for model in models:
            started = time.perf_counter()
            chunks: list[Any] = []
            yielded = False
            extra: dict[str, Any] = {}
            if model in REASONING_MODELS:
                extra["reasoning_effort"] = DEFAULT_REASONING_EFFORT
            try:
                stream = await litellm.acompletion(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    stream=True,
                    stream_options={"include_usage": True},
                    timeout=45,  # bound tail latency (fail-over only before first token)
                    **extra,
                )
                async for chunk in stream:
                    chunks.append(chunk)
                    try:
                        delta = chunk.choices[0].delta.content
                    except (IndexError, AttributeError):
                        delta = None
                    if delta:
                        yielded = True
                        yield delta

                latency_ms = int((time.perf_counter() - started) * 1000)
                try:
                    rebuilt = litellm.stream_chunk_builder(chunks, messages=messages)
                    self._log_cost(rebuilt, model, model_tier, purpose, latency_ms)
                except Exception:  # noqa: BLE001 - cost logging is best-effort
                    pass
                return
            except Exception as exc:  # noqa: BLE001 - provider error
                last_error = exc
                log.warning(
                    "llm_stream_failed",
                    model=model,
                    tier=model_tier,
                    purpose=purpose,
                    error=str(exc),
                )
                if yielded:
                    raise LLMUnavailableError(
                        f"Stream interrupted on {model}: {exc}"
                    ) from exc
                continue

        raise LLMUnavailableError(
            f"All models failed for tier {model_tier!r}: {last_error}"
        )

    async def chat_json(
        self,
        messages: list[dict],
        schema: dict | None = None,
        **kwargs: Any,
    ) -> dict:
        """Force JSON output, parse it, validate against schema if given."""
        raw = await self.chat(messages, json_mode=True, **kwargs)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"LLM did not return valid JSON: {raw!r}") from exc

        if schema is not None:
            self._validate_schema(data, schema)
        return data

    @staticmethod
    def _validate_schema(data: dict, schema: dict) -> None:
        """Lightweight required-keys check (avoids a jsonschema dependency)."""
        required = schema.get("required", [])
        missing = [k for k in required if k not in data]
        if missing:
            raise ValueError(f"JSON missing required keys: {missing}")

    def _log_cost(
        self,
        response: Any,
        model: str,
        tier: str,
        purpose: str,
        latency_ms: int,
    ) -> None:
        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "prompt_tokens", None) if usage else None
        output_tokens = getattr(usage, "completion_tokens", None) if usage else None
        try:
            cost = litellm.completion_cost(completion_response=response)
        except Exception:  # noqa: BLE001 - cost calc is best-effort
            cost = None

        log.info(
            "llm_call",
            model=model,
            tier=tier,
            purpose=purpose,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=round(cost, 6) if cost is not None else None,
            latency_ms=latency_ms,
            success=True,
        )

        # Persist to llm_calls table (best-effort, don't break chat on DB errors).
        try:
            import asyncio as _asyncio

            from maya.db.models import LLMCall
            from maya.db.session import get_sessionmaker

            async def _persist() -> None:
                sm = get_sessionmaker()
                async with sm() as session:
                    session.add(
                        LLMCall(
                            model=model,
                            tier=tier,
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            cost_usd=round(cost, 6) if cost is not None else None,
                            latency_ms=latency_ms,
                            success=True,
                            purpose=purpose,
                        )
                    )
                    await session.commit()

            _asyncio.create_task(_persist())
        except Exception as exc:  # noqa: BLE001
            log.warning("llm_call_persist_failed", error=str(exc))
