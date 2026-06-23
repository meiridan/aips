#!/usr/bin/env python3
"""Print the asyncpg-formatted DATABASE_URL for SQLAlchemy's async engine.

Neon hands back `postgresql://...?channel_binding=require&sslmode=require`, which
SQLAlchemy routes to the (sync) psycopg driver and asyncpg rejects the query
params. This converts it to `postgresql+asyncpg://...?ssl=require`.

Reads DATABASE_URL from .deploy.generated.env (or the environment as fallback).
"""
import os
import re
import sys


def load_url() -> str:
    try:
        with open(".deploy.generated.env") as f:
            m = re.search(r"DATABASE_URL='?([^'\n]+)'?", f.read())
            if m:
                return m.group(1)
    except FileNotFoundError:
        pass
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("DATABASE_URL not found", file=sys.stderr)
        sys.exit(1)
    return url


def to_asyncpg(url: str) -> str:
    base = url.split("?")[0].replace("postgresql://", "postgresql+asyncpg://")
    if base.startswith("postgresql+asyncpg://"):
        return f"{base}?ssl=require"
    return f"{base.replace('postgresql+asyncpg://', 'postgresql+asyncpg://')}?ssl=require"


if __name__ == "__main__":
    print(to_asyncpg(load_url()))
