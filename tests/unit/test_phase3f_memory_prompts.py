"""Phase 3f — companion-aware memory prompts test plan (pure).

Verifies the Appendix-A extraction/update prompts render correctly and that
build_mem0_config injects them only when companion context is supplied (so the
Phase-1/2 no-arg behavior is preserved).
"""

from __future__ import annotations

import pytest


def test_extraction_prompt_renders_vars():
    from maya.memory.prompts import render_extraction_prompt

    p = render_extraction_prompt("Maya", "Idan", "flirting", 7)
    assert "Maya" in p and "Idan" in p
    assert "flirting" in p and "day 7" in p
    assert "{companion_name}" not in p and "{user_name}" not in p


def test_extraction_prompt_is_companion_flavored():
    from maya.memory.prompts import render_extraction_prompt

    p = render_extraction_prompt("Maya", "Idan").lower()
    # richer-than-productivity signals
    for needle in ["emotional", "milestone", "first person", "dreams", "inside"]:
        assert needle in p


def test_extraction_prompt_excludes_companion_facts():
    """Leak-prevention intent: never store facts about the companion herself."""
    from maya.memory.prompts import render_extraction_prompt

    p = render_extraction_prompt("Maya", "Idan").lower()
    assert "facts about you" in p or "about him" in p


def test_update_prompt_renders():
    from maya.memory.prompts import render_update_prompt

    p = render_update_prompt("Maya", "Idan")
    assert "Maya" in p and "Idan" in p
    assert "newer" in p.lower()  # newer-wins conflict rule


# ───────────────────────── config injection ───────────────────────────────


def test_config_no_context_omits_custom_prompts(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h:5432/maya")
    from maya.memory.config import build_mem0_config

    cfg = build_mem0_config()
    assert "custom_fact_extraction_prompt" not in cfg
    assert "custom_update_memory_prompt" not in cfg


def test_config_with_context_injects_custom_prompts(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h:5432/maya")
    from maya.memory.config import build_mem0_config

    cfg = build_mem0_config("Maya", "Idan", "dating", 14)
    assert "Maya" in cfg["custom_fact_extraction_prompt"]
    assert "dating" in cfg["custom_fact_extraction_prompt"]
    assert "day 14" in cfg["custom_fact_extraction_prompt"]
    assert "Maya" in cfg["custom_update_memory_prompt"]


def test_config_partial_context_omits(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h:5432/maya")
    from maya.memory.config import build_mem0_config

    # only companion_name → not enough → omit (need both)
    cfg = build_mem0_config(companion_name="Maya")
    assert "custom_fact_extraction_prompt" not in cfg


@pytest.mark.parametrize("key", [
    "vector_store", "llm", "embedder", "version",
])
def test_config_base_keys_preserved(monkeypatch, key):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h:5432/maya")
    from maya.memory.config import build_mem0_config

    assert key in build_mem0_config("Maya", "Idan")
