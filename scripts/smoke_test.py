"""Verify all external services are reachable. Exit non-zero on any failure."""
import asyncio
import sys

import truststore
truststore.inject_into_ssl()

from maya.config import get_settings

settings = get_settings()


async def check_database():
    from sqlalchemy import text
    from maya.db.session import get_engine
    engine = get_engine()
    async with engine.connect() as conn:
        assert (await conn.execute(text("SELECT 1"))).scalar() == 1
        ext = await conn.execute(text("SELECT 1 FROM pg_extension WHERE extname='vector'"))
        assert ext.scalar() == 1, "pgvector not installed"
    print("✓ Database (Neon) + pgvector OK")


async def check_redis():
    import httpx
    # Use Upstash REST API over HTTPS (port 443) — works through Zscaler.
    # Redis protocol (port 6380) is blocked by corporate TLS inspection proxies.
    rest_url = settings.upstash_redis_rest_url
    rest_token = settings.upstash_redis_rest_token
    if not rest_url or not rest_token:
        raise RuntimeError("UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN not set")
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{rest_url}/ping",
            headers={"Authorization": f"Bearer {rest_token}"},
        )
        resp.raise_for_status()
        assert resp.json()["result"] == "PONG"
    print("✓ Redis (Upstash) OK")


def check_llm():
    import litellm
    resp = litellm.completion(
        model="xai/grok-3",
        messages=[{"role": "user", "content": "Say ok"}],
        max_tokens=5,
    )
    assert resp.choices[0].message.content
    print("✓ Grok (xAI) OK")


def check_embeddings():
    import litellm
    resp = litellm.embedding(model="text-embedding-3-small", input=["test"])
    assert len(resp.data[0]["embedding"]) == 1536
    print("✓ OpenAI embeddings OK")


async def main():
    try:
        await check_database()
        await check_redis()
        check_llm()
        check_embeddings()
        print("\n🎉 All systems go.")
    except Exception as e:
        print(f"\n❌ Smoke test failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
