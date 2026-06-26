"""Mem0 configuration. Spec §P2.1."""

from __future__ import annotations

import os
from urllib.parse import urlparse


def _parse_db_url() -> dict[str, str | int]:
    """Parse DATABASE_URL into pgvector connection params."""
    url = os.environ.get("DATABASE_URL", "")
    # Strip async driver prefix so urlparse handles it
    cleaned = url.replace("postgresql+asyncpg://", "postgresql://")
    parsed = urlparse(cleaned)
    return {
        "user": parsed.username or "postgres",
        "password": parsed.password or "postgres",
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 5432,
        "dbname": (parsed.path or "/maya").lstrip("/"),
    }


def build_mem0_config(
    companion_name: str | None = None,
    user_name: str | None = None,
    relationship_stage: str = "getting to know each other",
    days_known: int = 0,
) -> dict:
    """Build Mem0 config: pgvector + OpenAI gpt-4o-mini + text-embedding-3-small.

    When `companion_name` and `user_name` are supplied (Phase 3), the default
    Mem0 extraction/update prompts are replaced with the companion-aware
    versions from Appendix A. Called with no args it behaves exactly as before.
    """
    db = _parse_db_url()
    config: dict = {
        "vector_store": {
            "provider": "pgvector",
            "config": {
                "collection_name": "maya_memories",
                "embedding_model_dims": 1536,
                **db,
            },
        },
        "llm": {
            "provider": "openai",
            "config": {"model": "gpt-4o-mini", "temperature": 0.1},
        },
        "embedder": {
            "provider": "openai",
            "config": {"model": "text-embedding-3-small"},
        },
        "version": "v1.1",
    }
    if companion_name and user_name:
        from maya.memory.prompts import render_extraction_prompt, render_update_prompt

        config["custom_fact_extraction_prompt"] = render_extraction_prompt(
            companion_name, user_name, relationship_stage, days_known
        )
        config["custom_update_memory_prompt"] = render_update_prompt(
            companion_name, user_name
        )
    return config
