#!/usr/bin/env python3
"""Enable the pgvector extension on the provisioned Neon database."""
import os
import sys
import asyncio
import truststore
truststore.inject_into_ssl()
import asyncpg
from dotenv import load_dotenv
load_dotenv(".deploy.generated.env", override=True)


async def main():
    raw_url = os.environ["DATABASE_URL"]
    # asyncpg needs plain postgresql:// without sslmode param
    url = (
        raw_url
        .replace("postgresql+asyncpg://", "postgresql://")
        .replace("?sslmode=require", "")
        .replace("&sslmode=require", "")
    )
    conn = await asyncpg.connect(url, ssl=True)
    try:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        row = await conn.fetchrow("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
        assert row is not None, "pgvector failed to install"
        print("  ✓ pgvector extension enabled")
    finally:
        await conn.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"  ❌ pgvector setup failed: {e}")
        sys.exit(1)
