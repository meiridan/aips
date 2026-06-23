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


def build_mem0_config() -> dict:
    """Build Mem0 config: pgvector + OpenAI gpt-4o-mini + text-embedding-3-small."""
    db = _parse_db_url()
    return {
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
