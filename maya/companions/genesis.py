"""Companion birth — one-shot genesis LLM call (§P3.3, Appendix E).

`run_genesis` brings a freshly-seeded companion to life: backstory, initial
feelings, seed commitments, and a real first message.

Deliberate deviation from the spec's step 5 (seed Mem0 with the backstory):
we do NOT push Maya's self-biography into the user-fact memory store. Phase 2
fixed a leak where Maya's role-played biography was attributed to the user as
their own facts. Companion self-consistency lives in the commitments store
(3b) and `companions.backstory`, not in user memory.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field

from maya.companions.commitments import CommitmentService
from maya.companions.templates import get_template
from maya.db.models import Companion, Message, User
from maya.db.session import get_sessionmaker
from maya.emotional.service import EmotionalService
from maya.llm.service import LLMService
from maya.logging import get_logger
from maya.relationship.service import RelationshipService

log = get_logger("maya.genesis")

GENESIS_PROMPT = """You are about to come to life as {companion_name}, an AI companion.

YOUR TEMPLATE:
- Archetype: {template_description}
- Key traits: {template_traits}

YOUR CREATOR:
- His name: {user_name}
- What he wrote about himself: {user_intent}

GENERATE YOUR INITIAL BEING. Return JSON:

{{
  "backstory": "<200 words. First person. Where you grew up, your job, your passions, a quirk, a small flaw. Specific. A real person, not an archetype.>",
  "initial_feelings": {{
    "valence": <-1 to 1>,
    "arousal": <0 to 1>,
    "feelings": {{"feeling_name": intensity}}
  }},
  "seed_commitments": [
    {{"content": "I [verb]...", "commitment_type": "identity", "importance": 0.8}}
  ],
  "first_message": "<the message you'd send him FIRST. Short. In character. Curious. Inviting without being needy. Like a stranger texting, not a chatbot.>"
}}

CONSTRAINTS:
- Don't make her a fantasy. Make her a person.
- The flaw matters. No flaw = no person.
- The first message must NOT feel like a system greeting.
"""

_REQUIRED = {"backstory", "initial_feelings", "seed_commitments", "first_message"}


class GenesisResult(BaseModel):
    backstory: str
    initial_feelings: dict[str, Any] = Field(default_factory=dict)
    seed_commitments: list[dict[str, Any]] = Field(default_factory=list)
    first_message: str


async def generate_genesis(
    companion: Companion, user: User, llm: LLMService | None = None
) -> GenesisResult:
    """One-shot LLM call (main tier — personality matters) → GenesisResult."""
    llm = llm or LLMService()
    template = get_template(companion.template_id)
    prompt = GENESIS_PROMPT.format(
        companion_name=companion.name,
        template_description=template.description,
        template_traits=", ".join(template.traits),
        user_name=user.name,
        user_intent=user.description or "open to whatever connection forms",
    )
    result = await llm.chat_json(
        messages=[{"role": "user", "content": prompt}],
        schema={"required": list(_REQUIRED)},
        model_tier="main",
        purpose="genesis",
        max_tokens=1200,
    )
    return GenesisResult(**result)


async def run_genesis(
    companion_id: uuid.UUID,
    *,
    sessionmaker: Any = None,
    llm: LLMService | None = None,
) -> GenesisResult:
    """Apply genesis to a freshly-created companion. Idempotent-ish: overwrites
    backstory/feelings, appends seed commitments + first message."""
    sm = sessionmaker or get_sessionmaker()
    llm = llm or LLMService()

    async with sm() as session:
        companion = await session.get(Companion, companion_id)
        if companion is None:
            raise ValueError(f"Companion {companion_id} not found")
        user = await session.get(User, companion.user_id)
        if user is None:
            raise ValueError(f"User {companion.user_id} not found")
        # Detach plain copies for the LLM call (avoid holding the session open).
        comp_name, comp_template, user_obj = companion.name, companion.template_id, user
        genesis = await generate_genesis(companion, user_obj, llm)

        # 1. Persist backstory + personality blob.
        template = get_template(comp_template)
        companion.backstory = genesis.backstory
        companion.personality = {
            "template_id": template.id,
            "name": template.name,
            "description": template.description,
            "traits": template.traits,
            "baseline_tone": template.baseline_tone,
        }
        # 6. Save first message as the opening assistant message.
        session.add(
            Message(
                companion_id=companion_id,
                user_id=user_obj.id,
                role="assistant",
                content=genesis.first_message,
            )
        )
        user_id = user_obj.id
        await session.commit()

    # 2. Initial emotional state (template baseline merged with genesis feelings).
    baseline = get_template(comp_template).baseline_emotional
    merged = {
        "valence": genesis.initial_feelings.get("valence", baseline.get("valence", 0.0)),
        "arousal": genesis.initial_feelings.get("arousal", baseline.get("arousal", 0.5)),
        "feelings": {**baseline.get("feelings", {}), **genesis.initial_feelings.get("feelings", {})},
    }
    await EmotionalService(sm).set_initial(companion_id, merged)

    # 3. Relationship at STRANGERS.
    await RelationshipService(sm).initialize(companion_id, user_id)

    # 4. Seed commitments.
    commits = CommitmentService(sm)
    for c in genesis.seed_commitments:
        await commits.add(
            companion_id=companion_id,
            content=str(c.get("content", "")).strip(),
            commitment_type=str(c.get("commitment_type", "identity")),
            importance=float(c.get("importance", 0.5)),
        )

    log.info(
        "genesis_complete",
        companion=comp_name,
        commitments=len(genesis.seed_commitments),
    )
    return genesis
