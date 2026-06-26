"""Phase 2 test execution engine. Runs scenarios against the live stack."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from sqlalchemy import delete as sa_delete
from sqlalchemy import text

from maya.conversation.orchestrator import Orchestrator
from maya.db.models import Companion, User
from maya.db.session import get_sessionmaker
from maya.logging import configure_logging
from maya.memory.service import MemoryService

from .scenarios import Scenario, Variant

configure_logging("ERROR")

EventCb = Callable[[dict[str, Any]], Awaitable[None]] | None


async def _noop(_: dict) -> None:
    pass


@dataclass
class AssertionResult:
    description: str
    require_keywords: list[str]
    forbid_keywords: list[str]
    actual_response: str
    passed: bool


@dataclass
class ScenarioResult:
    scenario_id: str
    scenario_name: str
    variant_id: str
    variant_name: str
    status: Literal["pass", "fail", "partial", "error", "skipped"]
    assertions: list[AssertionResult] = field(default_factory=list)
    conversation: list[dict] = field(default_factory=list)
    memories_snapshot: list[dict] = field(default_factory=list)
    duration_ms: int = 0
    error: str | None = None


def _check(response: str, require: list[str], forbid: list[str]) -> bool:
    lc = response.lower()
    ok_req = (not require) or any(k.lower() in lc for k in require)
    ok_forbid = (not forbid) or not any(k.lower() in lc for k in forbid)
    return ok_req and ok_forbid


async def _create_entities() -> tuple[uuid.UUID, uuid.UUID]:
    sm = get_sessionmaker()
    async with sm() as session:
        user = User(name="TestRunner", description="Phase 2 automated test")
        session.add(user)
        await session.flush()
        companion = Companion(user_id=user.id, name="Maya", template_id="test")
        session.add(companion)
        await session.flush()
        await session.commit()
        return user.id, companion.id


async def _cleanup(uid: uuid.UUID, _cid: uuid.UUID) -> None:
    sm = get_sessionmaker()
    try:
        async with sm() as session:
            # Cascade deletes companion + messages
            await session.execute(sa_delete(User).where(User.id == uid))
            # Direct pgvector cleanup
            await session.execute(
                text("DELETE FROM maya_memories WHERE payload->>'user_id' = :uid"),
                {"uid": str(uid)},
            )
            await session.commit()
    except Exception:
        pass


async def run_scenario(
    scenario: Scenario,
    variant: Variant,
    model_tier: str = "cheap",
    auto_cleanup: bool = True,
    event_cb: EventCb = None,
) -> ScenarioResult:
    if event_cb is None:
        event_cb = _noop

    result = ScenarioResult(
        scenario_id=scenario.id,
        scenario_name=scenario.name,
        variant_id=variant.id,
        variant_name=variant.name,
        status="error",
    )

    uid, cid = await _create_entities()
    t0 = time.monotonic()

    try:
        orch = Orchestrator(default_tier=model_tier)

        for i, turn in enumerate(variant.turns):
            # S5: restart session before the turn AFTER session_restart_after index
            if variant.session_restart_after >= 0 and i == variant.session_restart_after + 1:
                await event_cb({
                    "type": "session_restart",
                    "msg": "Waiting for memory extraction, then restarting session...",
                })
                await asyncio.sleep(6)
                orch = Orchestrator(default_tier=model_tier)
                await event_cb({"type": "session_restart", "msg": "New session created."})

            await event_cb({"type": "turn_sent", "msg": turn.msg})
            response = await orch.handle_message(uid, cid, turn.msg)
            result.conversation.append({"role": "user", "content": turn.msg})
            result.conversation.append({"role": "assistant", "content": response})
            await event_cb({"type": "turn_received", "response": response})

            if turn.wait_after_s > 0:
                await event_cb({"type": "info", "msg": f"Waiting {turn.wait_after_s:.0f}s for extraction…"})
                await asyncio.sleep(turn.wait_after_s)

            if turn.label:
                passed = _check(response, turn.require, turn.forbid)
                ar = AssertionResult(
                    description=turn.label,
                    require_keywords=turn.require,
                    forbid_keywords=turn.forbid,
                    actual_response=response,
                    passed=passed,
                )
                result.assertions.append(ar)
                await event_cb({"type": "assertion", **asdict(ar)})

        # Wait for async extraction tasks launched by the orchestrator
        await event_cb({"type": "info", "msg": "Waiting for memory extraction..."})
        await asyncio.sleep(5)

        # Memory count checks (S3a dedup)
        memories = await MemoryService().get_all(uid, cid)
        result.memories_snapshot = memories

        for mc in variant.mem_checks:
            count = sum(1 for m in memories if mc.topic.lower() in m["text"].lower())
            passed = count <= mc.max_count
            ar = AssertionResult(
                description=mc.description,
                require_keywords=[f"<= {mc.max_count} memories about '{mc.topic}'"],
                forbid_keywords=[],
                actual_response=f"Found {count} memory/memories containing '{mc.topic}'",
                passed=passed,
            )
            result.assertions.append(ar)
            await event_cb({"type": "assertion", **asdict(ar)})

        await event_cb({"type": "memories", "items": memories})

        if not result.assertions:
            result.status = "pass"
        elif all(a.passed for a in result.assertions):
            result.status = "pass"
        elif any(a.passed for a in result.assertions):
            result.status = "partial"
        else:
            result.status = "fail"

    except Exception as exc:
        result.status = "error"
        result.error = str(exc)
        await event_cb({"type": "error", "message": str(exc)})
    finally:
        result.duration_ms = int((time.monotonic() - t0) * 1000)
        if auto_cleanup:
            await _cleanup(uid, cid)

    return result
