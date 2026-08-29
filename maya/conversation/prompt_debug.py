"""Read-only introspection of the assembled Phase-3 prompt.

`build_phase3` composes the system block from six independent sources
(companion row, emotional state, relationship state, memory search, commitments,
moment analysis) plus two conditional directives. When the model behaves against
its instructions the cause is usually two of those sources disagreeing, which is
invisible from any single file — so dump the assembled prompt before theorising.

This module gathers exactly the context the orchestrator's `_prepare` gathers,
but writes nothing: no user message is saved, no emotional or relationship state
is advanced. Rendering lives in the CLI; everything here is data.
"""

from __future__ import annotations

import asyncio
import string
import uuid
from dataclasses import dataclass, field
from typing import Any

from maya.companions.templates import get_template
from maya.conversation import response_length
from maya.conversation.moment_analyzer import (
    MOMENT_GUIDANCE,
    MomentAnalysis,
    default_moment,
)
from maya.conversation.orchestrator import MEMORY_LIMIT, RECENT_LIMIT, Orchestrator
from maya.conversation.prompt_builder import (
    PHASE3_SYSTEM_TEMPLATE,
    TOKEN_BUDGET,
    build_phase3,
    count_tokens,
    language_directive,
)

# Sentinel moment selectors accepted by `--moment`.
MOMENT_LIVE = "default"
MOMENT_AUTO = "auto"


@dataclass
class Source:
    """Where one template field's value actually came from."""

    field: str
    origin: str
    value: Any
    note: str = ""

    def __post_init__(self) -> None:
        self.value = str(self.value)


@dataclass
class PromptDump:
    system: str
    messages: list[dict[str, str]]
    sources: list[Source]
    tokens: int
    budget: int
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def over_budget(self) -> bool:
        return self.tokens > self.budget


def template_fields() -> set[str]:
    """Every `{name}` placeholder in PHASE3_SYSTEM_TEMPLATE."""
    return {name for _, name, _, _ in string.Formatter().parse(PHASE3_SYSTEM_TEMPLATE) if name}


def _trunc(value: Any, limit: int = 90) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def resolve_moment(selector: str) -> tuple[MomentAnalysis | None, str]:
    """Map a `--moment` selector to a moment, or None when it must be analyzed.

    Returns (moment, description). `auto` yields None — the caller runs the real
    analyzer, which costs a fast-tier LLM call.
    """
    sel = (selector or MOMENT_LIVE).strip().lower()
    if sel == MOMENT_LIVE:
        return default_moment(), "default_moment() — what the live main call actually gets"
    if sel == MOMENT_AUTO:
        return None, "MomentAnalyzer.analyze() — real classification (paid fast-tier call)"
    if sel not in MOMENT_GUIDANCE:
        raise ValueError(
            f"unknown moment {sel!r}; use 'default', 'auto', or one of: "
            + ", ".join(sorted(MOMENT_GUIDANCE))
        )
    return MomentAnalysis(moment_type=sel), f"forced --moment {sel}"


def _sources(
    *,
    companion: Any,
    user_name: str,
    emotional: Any,
    relationship: Any,
    memories: list[dict[str, Any]],
    commitments: list[Any],
    moment: MomentAnalysis,
    hours_since: float,
    length_level: int,
) -> list[Source]:
    """One row per PHASE3_SYSTEM_TEMPLATE placeholder, naming its real origin.

    Kept exhaustive on purpose — `test_prompt_debug` fails if the template grows
    a field this map does not cover.
    """
    locale = getattr(companion, "locale", None)
    mtype = moment.moment_type
    comp_origin = "companions row → orchestrator._load_companion"
    comp_note = "cached per-process in runtime_cache; a DB edit needs a server restart"
    rel_origin = "relationship row → RelationshipService.get"
    rel_note = "transitions.py advances these on its own as intimacy/interactions grow"
    emo_origin = "emotional_state row + template baseline → EmotionalService.get"
    moment_origin = "MomentAnalysis → moment_analyzer.MOMENT_GUIDANCE"

    return [
        Source("companion_name", comp_origin, getattr(companion, "name", "Maya"), comp_note),
        Source(
            "personality_description",
            "companions.personality['description'] (wizard → persona_spec)",
            _trunc(
                getattr(companion, "personality", {})
                and (companion.personality or {}).get("description")
                or "A warm, real person."
            ),
            "catalog.py holds the prompt fragment each wizard option contributes",
        ),
        Source(
            "backstory",
            "companions.backstory (written once by companions/genesis.py)",
            _trunc(getattr(companion, "backstory", "") or "(empty)"),
            "generated against the persona at genesis time — stale if the persona changed",
        ),
        Source(
            "user_name",
            "users.name → orchestrator._user_name",
            user_name,
            "cached per-process in runtime_cache",
        ),
        Source("user_name_upper", "derived from user_name", user_name.upper()),
        Source(
            "formatted_feelings",
            emo_origin,
            _trunc(getattr(emotional, "feelings", {}) or "(neutral)"),
        ),
        Source("valence", emo_origin, f"{float(getattr(emotional, 'valence', 0.0)):.2f}"),
        Source("arousal", emo_origin, f"{float(getattr(emotional, 'arousal', 0.5)):.2f}"),
        Source("days_known", rel_origin, getattr(relationship, "days_known", 0), rel_note),
        Source("stage", rel_origin, getattr(relationship, "stage", "strangers"), rel_note),
        Source("intimacy", rel_origin, getattr(relationship, "intimacy_level", 1), rel_note),
        Source("trust", rel_origin, getattr(relationship, "trust_level", 1), rel_note),
        Source(
            "hours_since_last", "derived from relationship.last_interaction_at", int(hours_since)
        ),
        Source(
            "moment_type",
            moment_origin,
            mtype,
            "the live critical path builds with default_moment(); the real "
            "classification lands in post-processing, NOT in this prompt",
        ),
        Source("character_priority", moment_origin, moment.character_priority),
        Source("moment_specific_guidance", moment_origin, _trunc(moment.guidance())),
        Source(
            "formatted_memories",
            f"mem0 + pgvector → MemoryService.search_relevant (limit {MEMORY_LIMIT})",
            f"{len(memories)} memories",
        ),
        Source(
            "formatted_commitments",
            "commitments row → CommitmentService.get_recent(limit=20)",
            f"{len(commitments)} commitments",
        ),
        Source(
            "max_words",
            "companions.response_length → response_length.words_for",
            f"{response_length.words_for(length_level)} "
            f"(level {length_level} / {response_length.label(length_level)})",
        ),
        Source(
            "language_directive",
            "companions.locale → prompt_builder.LANGUAGE_DIRECTIVES",
            _trunc(language_directive(locale).strip("\n- ") or f"none (locale={locale!r})"),
        ),
    ]


async def build_dump(
    user_id: uuid.UUID,
    companion_id: uuid.UUID,
    message: str,
    *,
    moment_selector: str = MOMENT_LIVE,
    turns: int = RECENT_LIMIT,
    with_memory: bool = True,
    orchestrator: Orchestrator | None = None,
) -> PromptDump:
    """Assemble the prompt for `message` without mutating any state."""
    orch = orchestrator or Orchestrator()
    moment, moment_desc = resolve_moment(moment_selector)

    companion = await orch._load_companion(companion_id)
    if companion is None:
        raise LookupError(f"companion {companion_id} not found")
    baseline = get_template(companion.template_id).baseline_emotional

    memories_coro = (
        orch.memory.search_relevant(message, user_id, companion_id, MEMORY_LIMIT)
        if with_memory
        else _none_list()
    )
    memories, emotional, relationship, commitments, recent, user_name = await asyncio.gather(
        memories_coro,
        orch.emotional.get(companion_id, baseline=baseline),
        orch.relationship.get(companion_id, user_id),
        orch.commitments.get_recent(companion_id, limit=20),
        orch._recent_messages_own(companion_id, turns),
        orch._user_name(user_id),
    )
    hours_since = orch._hours_since(getattr(relationship, "last_interaction_at", None))

    if moment is None:
        moment = await orch.moment_analyzer.analyze(message, emotional, relationship, recent)
        moment_desc = f"{moment_desc} → {moment.moment_type}"

    length_level = response_length.normalize(
        getattr(companion, "response_length", response_length.DEFAULT)
    )
    messages = build_phase3(
        companion=companion,
        memories=memories,
        emotional=emotional,
        relationship=relationship,
        commitments=commitments,
        moment=moment,
        recent_msgs=recent,
        user_name=user_name,
        hours_since_last=hours_since,
        response_length=length_level,
        enforce_budget=False,  # over-budget is exactly when you need to look
    )
    # _prepare appends the turn when the concurrent save has not landed in
    # `recent` yet; here nothing was saved, so it always needs appending.
    if not (messages[-1]["role"] == "user" and messages[-1]["content"] == message):
        messages.append({"role": "user", "content": message})

    system = messages[0]["content"]
    return PromptDump(
        system=system,
        messages=messages,
        sources=_sources(
            companion=companion,
            user_name=user_name,
            emotional=emotional,
            relationship=relationship,
            memories=memories,
            commitments=commitments,
            moment=moment,
            hours_since=hours_since,
            length_level=length_level,
        ),
        tokens=count_tokens(system),
        budget=TOKEN_BUDGET,
        meta={
            "companion_name": companion.name,
            "user_name": user_name,
            "locale": getattr(companion, "locale", None),
            "template_id": companion.template_id,
            "moment_source": moment_desc,
            "memory_searched": with_memory,
            "recent_turns": len(recent),
        },
    )


async def _none_list() -> list[dict[str, Any]]:
    return []
