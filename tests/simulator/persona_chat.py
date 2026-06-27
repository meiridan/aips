"""Persona-driven message generator (§P4.2, Appendix I).

An LLM speaks *as the user* (never as Maya), driven by a `Persona`. The runner
feeds Maya's last reply + a time context; this returns the persona's next text
(or the literal "[skip]" when they'd realistically go silent).
"""

from __future__ import annotations

from tests.simulator.personas import Persona

# Appendix I — verbatim placeholders filled by `build_prompt`.
PERSONA_GENERATION_PROMPT = """You are simulating {persona_name}, a real person texting an AI companion \
named Maya. You are NOT Maya. You are the user.

WHO YOU ARE:
{persona_description}

YOUR COMMUNICATION STYLE: {communication_style}
YOUR RELATIONSHIP GOAL: {relationship_goal}

CURRENT CONTEXT:
- Day {current_day} of knowing Maya
- {time_context}
- Conversation so far ({n} messages): {conversation_so_far}
- Last thing Maya said: "{last_maya_response}"

SECRETS YOU HAVEN'T REVEALED YET (reveal slowly, only when trust builds):
{secrets_unrevealed}

YOUR TRIGGERS (things that upset you): {triggers}

GENERATE YOUR NEXT MESSAGE:
- Stay in character as {persona_name}
- Match your communication style
- Realistic length (mostly 1-2 sentences, occasionally longer)
- Don't reveal secrets in the first 3 days unless Maya earns trust
- React naturally to what Maya just said — agreement, disagreement, deflection, etc.
- Sometimes change the subject. Sometimes go silent (return "[skip]" 10% of the time).
- DON'T be a perfect interlocutor. Be a real person — sometimes distracted, \
sometimes vulnerable, sometimes guarded.

Return ONLY the message text. No quotes, no explanation. If skipping, \
return exactly "[skip]"."""

SKIP_TOKEN = "[skip]"


class PersonaSimulator:
    """Generates messages from a persona's perspective using an LLM."""

    def __init__(self, persona: Persona, llm):  # llm: LLMService | None
        self.persona = persona
        self.llm = llm
        self.simulated_day = 0
        self.conversation_so_far: list[dict] = []
        self.tracked_revealed_secrets: list[str] = []

    def format_history(self) -> str:
        if not self.conversation_so_far:
            return "(no messages yet)"
        who = {"user": self.persona.name, "assistant": "Maya"}
        return "\n".join(
            f"{who.get(m['role'], m['role'])}: {m['content']}"
            for m in self.conversation_so_far
        )

    def _unrevealed_secrets(self) -> list[str]:
        return [s for s in self.persona.secrets if s not in self.tracked_revealed_secrets]

    def build_prompt(self, last_maya_response: str | None, time_context: str) -> str:
        unrevealed = self._unrevealed_secrets()
        return PERSONA_GENERATION_PROMPT.format(
            persona_name=self.persona.name,
            persona_description=self.persona.description,
            communication_style=self.persona.communication_style,
            relationship_goal=self.persona.relationship_goal,
            current_day=self.simulated_day,
            time_context=time_context,
            n=len(self.conversation_so_far),
            conversation_so_far=self.format_history(),
            last_maya_response=last_maya_response or "(start of conversation)",
            secrets_unrevealed=(
                "\n".join(f"- {s}" for s in unrevealed) if unrevealed else "(none left)"
            ),
            triggers=", ".join(self.persona.triggers),
        )

    async def generate_next_message(
        self, last_maya_response: str | None, time_context: str
    ) -> str:
        """One LLM turn as the persona. Returns the message text or "[skip]"."""
        prompt = self.build_prompt(last_maya_response, time_context)
        message = await self.llm.chat(
            messages=[{"role": "user", "content": prompt}],
            model_tier="cheap",  # generating, not character-acting
            temperature=0.9,  # we want variety
            purpose="persona_sim",
        )
        return message.strip()
