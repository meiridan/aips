"""Deterministic units of the persona message generator (§P4.2).

The LLM call itself is exercised by the smoke run; here we pin the prompt
construction and secret-revelation bookkeeping, which must be reproducible.
"""

from __future__ import annotations

from tests.simulator.persona_chat import PersonaSimulator
from tests.simulator.personas import PERSONAS


def _sim() -> PersonaSimulator:
    return PersonaSimulator(PERSONAS["lonely_dev"], llm=None)


def test_prompt_embeds_persona_and_context():
    sim = _sim()
    sim.simulated_day = 3
    prompt = sim.build_prompt(last_maya_response="how was your day?",
                              time_context="Day 3, evening, after work")
    assert "David" in prompt
    assert "Day 3" in prompt
    assert "evening, after work" in prompt
    assert "how was your day?" in prompt
    assert "dismissiveness" in prompt  # a trigger


def test_unrevealed_secrets_excludes_tracked():
    sim = _sim()
    first_secret = PERSONAS["lonely_dev"].secrets[0]
    assert first_secret in sim.build_prompt(None, "Day 0, morning")
    sim.tracked_revealed_secrets.append(first_secret)
    assert first_secret not in sim.build_prompt(None, "Day 0, morning")


def test_format_history_reflects_conversation():
    sim = _sim()
    assert sim.format_history() == "(no messages yet)"
    sim.conversation_so_far.append({"role": "user", "content": "hey"})
    sim.conversation_so_far.append({"role": "assistant", "content": "hi there"})
    history = sim.format_history()
    assert "hey" in history and "hi there" in history


def test_start_of_conversation_placeholder():
    sim = _sim()
    prompt = sim.build_prompt(last_maya_response=None, time_context="Day 0, morning")
    assert "(start of conversation)" in prompt
