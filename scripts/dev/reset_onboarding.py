"""Send the app back to the creation wizard without destroying anything yet.

Clears `companions.onboarded_at`, which is the only flag the SPA reads to decide
wizard-vs-chat. History is deliberately left in place: `create_companion` wipes it
when the wizard is actually submitted, so the data dies by the user's action, not
by running this.

    uv run python scripts/dev/reset_onboarding.py
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from maya import runtime_cache
from maya.db.models import Companion, Message
from maya.db.session import dispose_engine, get_sessionmaker


async def main() -> None:
    sm = get_sessionmaker()
    async with sm() as session:
        companions = (await session.execute(select(Companion))).scalars().all()
        if not companions:
            print("No companion yet — the wizard already shows on first load.")
            return
        for comp in companions:
            messages = len(
                (
                    await session.execute(
                        select(Message).where(Message.companion_id == comp.id)
                    )
                )
                .scalars()
                .all()
            )
            was = comp.onboarded_at
            comp.onboarded_at = None
            runtime_cache.invalidate_companion(comp.id)
            print(
                f"  {comp.name!r}: onboarded_at {was} -> None "
                f"({messages} message(s) kept until you submit the wizard)"
            )
        await session.commit()
    runtime_cache.clear()
    print("\nReload the app — it opens on the creation flow.")


async def _run() -> None:
    # Dispose inside the same loop that opened the pool; a second asyncio.run()
    # tears down connections attached to an already-closed loop.
    try:
        await main()
    finally:
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(_run())
