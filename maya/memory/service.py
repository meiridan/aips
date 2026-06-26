"""Memory service: real Mem0 + pgvector + OpenAI implementation. Spec §P2.1.

Wraps the synchronous Mem0 client with async helpers and a thin DTO layer
the orchestrator can rely on.

NOTE: Mem0's built-in search has bugs (ignores limit, skips newer memories,
returns degenerate scores for non-English queries). We bypass it with a
direct pgvector cosine-distance query using litellm embeddings.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any

# Silence Mem0 / PostHog telemetry (noisy SSL errors otherwise)
os.environ.setdefault("MEM0_TELEMETRY", "False")
os.environ.setdefault("POSTHOG_DISABLED", "1")

import litellm
from mem0 import Memory  # noqa: E402
from sqlalchemy import text

from maya.db.session import get_sessionmaker  # noqa: E402
from maya.llm.service import LLMService  # noqa: E402
from maya.logging import get_logger  # noqa: E402
from maya.memory.config import build_mem0_config  # noqa: E402

log = get_logger("maya.memory")

_EMBED_MODEL = "text-embedding-3-small"
_COLLECTION = "maya_memories"


def _scope(user_id: uuid.UUID, companion_id: uuid.UUID) -> dict[str, str]:
    """Mem0 namespacing: per (user, companion) pair."""
    return {"user_id": str(user_id), "agent_id": str(companion_id)}


async def _embed(text_: str) -> list[float]:
    """Generate embedding via litellm (OpenAI text-embedding-3-small)."""
    resp = await litellm.aembedding(
        model=f"openai/{_EMBED_MODEL}", input=[text_]
    )
    return resp.data[0]["embedding"]


class MemoryService:
    """Long-term memory backed by Mem0 + pgvector + OpenAI embeddings."""

    def __init__(
        self,
        llm: LLMService | None = None,
        sessionmaker: Any = None,
        client: Memory | None = None,
        companion_name: str | None = None,
        user_name: str | None = None,
        relationship_stage: str = "getting to know each other",
        days_known: int = 0,
    ):
        self.llm = llm
        self._sessionmaker = sessionmaker or get_sessionmaker()
        # When companion/user context is given, Mem0 uses the Phase-3
        # companion-aware extraction prompt (Appendix A); otherwise the default.
        self._client = client or Memory.from_config(
            build_mem0_config(
                companion_name=companion_name,
                user_name=user_name,
                relationship_stage=relationship_stage,
                days_known=days_known,
            )
        )

    # ── Public async API ─────────────────────────────────────────────────

    async def extract_and_store(
        self,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        user_message: str,
        assistant_message: str,
    ) -> list[str]:
        """Extract + dedupe + store facts **about the user** from this turn.

        Only the user's own message is sent to Mem0. The assistant (companion)
        message is deliberately excluded: Maya role-plays a persona and discloses
        invented self-facts ("I'm 45, divorced, 3 kids…"). Sending those under the
        user's memory scope made Mem0 attribute Maya's biography to the user —
        e.g. her children's names showing up as the user's. The companion's own
        self-consistency is a separate store (Phase 3 commitments), not user memory.

        `assistant_message` is kept in the signature for callers/back-compat but
        is intentionally not extracted.
        """
        messages = [
            {"role": "user", "content": user_message},
        ]
        try:
            result = await asyncio.to_thread(
                self._client.add,
                messages,
                **_scope(user_id, companion_id),
            )
            facts = [
                r.get("memory", "")
                for r in (result or {}).get("results", [])
                if r.get("event") in ("ADD", "UPDATE")
            ]
            log.info(
                "memory_extracted",
                user_id=str(user_id),
                companion_id=str(companion_id),
                count=len(facts),
            )
            return facts
        except Exception as exc:  # noqa: BLE001
            log.error("memory_extraction_error", error=str(exc))
            return []

    async def search_relevant(
        self,
        query: str,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Semantic search via direct pgvector cosine query.

        Bypasses Mem0's built-in search which has known bugs: ignores the
        limit parameter, silently drops newer memories, and returns
        degenerate 1.0 scores for non-English queries (HNSW returns
        arbitrary order when query embedding has high cosine sim with all
        stored vectors).
        """
        try:
            vec = await _embed(query)
            vec_literal = "[" + ",".join(str(v) for v in vec) + "]"
            sql = text(
                f"""
                SELECT
                    id::text,
                    payload->>'data'                         AS memory,
                    payload->>'created_at'                   AS created_at,
                    1 - (vector <=> '{vec_literal}'::vector) AS score
                FROM {_COLLECTION}
                WHERE payload->>'user_id'  = :uid
                  AND payload->>'agent_id' = :aid
                ORDER BY vector <=> '{vec_literal}'::vector
                LIMIT :lim
                """
            )
            async with self._sessionmaker() as session:
                rows = (
                    await session.execute(sql, {"uid": str(user_id), "aid": str(companion_id), "lim": limit})
                ).fetchall()
            return [
                {
                    "id": r.id,
                    "text": r.memory or "",
                    "score": float(r.score),
                    "created_at": r.created_at,
                }
                for r in rows
            ]
        except Exception as exc:  # noqa: BLE001
            log.error("memory_search_error", error=str(exc))
            return []

    async def get_all(
        self,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        """All memories for a (user, companion) pair, chronological."""
        try:
            sql = text(
                f"""
                SELECT
                    id::text,
                    payload->>'data'       AS memory,
                    payload->>'created_at' AS created_at
                FROM {_COLLECTION}
                WHERE payload->>'user_id'  = :uid
                  AND payload->>'agent_id' = :aid
                ORDER BY payload->>'created_at'
                """
            )
            async with self._sessionmaker() as session:
                rows = (
                    await session.execute(sql, {"uid": str(user_id), "aid": str(companion_id)})
                ).fetchall()
            return [
                {"id": r.id, "text": r.memory or "", "created_at": r.created_at}
                for r in rows
            ]
        except Exception as exc:  # noqa: BLE001
            log.error("memory_get_all_error", error=str(exc))
            return []

    async def delete_all(
        self,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
    ) -> int:
        """Wipe all memories for a (user, companion) pair."""
        try:
            await asyncio.to_thread(
                self._client.delete_all,
                **_scope(user_id, companion_id),
            )
            return 1
        except Exception as exc:  # noqa: BLE001
            log.error("memory_delete_error", error=str(exc))
            return 0

    async def delete_by_id(
        self,
        memory_id: str,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
    ) -> int:
        """Delete a single memory by id, scoped to (user, companion) for safety.

        Accepts a full id or a unique id prefix. Returns the number of rows
        deleted (0 if no match, >1 only if an ambiguous prefix matched several).
        """
        try:
            sql = text(
                f"""
                DELETE FROM {_COLLECTION}
                WHERE id::text LIKE :idp
                  AND payload->>'user_id'  = :uid
                  AND payload->>'agent_id' = :aid
                """
            )
            async with self._sessionmaker() as session:
                result = await session.execute(
                    sql,
                    {"idp": f"{memory_id}%", "uid": str(user_id), "aid": str(companion_id)},
                )
                await session.commit()
                return result.rowcount or 0
        except Exception as exc:  # noqa: BLE001
            log.error("memory_delete_by_id_error", error=str(exc))
            return 0
