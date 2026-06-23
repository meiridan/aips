"""Maya CLI (Typer). Commands: seed, chat, state, history, reset.

Active context comes from MAYA_USER_ID / MAYA_COMPANION_ID env vars
(printed by `maya seed`), overridable via flags.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import typer
from sqlalchemy import delete, func, select

from maya.config import get_settings
from maya.conversation.orchestrator import Orchestrator
from maya.db.models import Companion, Message, User
from maya.db.session import dispose_engine, get_sessionmaker
from maya.logging import configure_logging

app = typer.Typer(add_completion=False, help="Maya Core CLI")


def _resolve(opt: str | None, env: str) -> uuid.UUID:
    raw = opt or os.getenv(env)
    if not raw:
        typer.secho(
            f"No {env} set. Run `maya seed` first, then export it.", fg="red"
        )
        raise typer.Exit(code=1)
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise typer.BadParameter(f"Invalid UUID for {env}: {raw}") from exc


@app.callback()
def _main() -> None:
    configure_logging(get_settings().litellm_log)


@app.command()
def seed(
    user_name: str = typer.Option(..., "--user-name"),
    user_description: str = typer.Option(None, "--user-description"),
    companion_name: str = typer.Option("Maya", "--companion-name"),
    template_id: str = typer.Option("flirt", "--template-id"),
) -> None:
    """Create a test user + companion."""

    async def _run() -> tuple[uuid.UUID, uuid.UUID]:
        sm = get_sessionmaker()
        async with sm() as session:
            user = User(name=user_name, description=user_description)
            session.add(user)
            await session.flush()
            companion = Companion(
                user_id=user.id, name=companion_name, template_id=template_id
            )
            session.add(companion)
            await session.commit()
            return user.id, companion.id

    user_id, companion_id = asyncio.run(_run())
    typer.echo(f"Created user {user_id}  companion {companion_id}")
    typer.echo(
        f"Set as active: export MAYA_USER_ID={user_id} "
        f"MAYA_COMPANION_ID={companion_id}"
    )
    asyncio.run(dispose_engine())


@app.command()
def chat(
    user_id: str = typer.Option(None, "--user-id"),
    companion_id: str = typer.Option(None, "--companion-id"),
) -> None:
    """Interactive chat REPL."""
    uid = _resolve(user_id, "MAYA_USER_ID")
    cid = _resolve(companion_id, "MAYA_COMPANION_ID")
    orch = Orchestrator()

    typer.echo("[Maya] Hi! I'm Maya. What's on your mind?  (Ctrl-D or 'quit' to exit)")

    async def _turn(text: str) -> str:
        return await orch.handle_message(uid, cid, text)

    try:
        while True:
            try:
                line = input("> ").strip()
            except EOFError:
                typer.echo("")
                break
            if line.lower() in {"quit", "exit"}:
                break
            if not line:
                continue
            reply = asyncio.run(_turn(line))
            typer.echo(f"[Maya] {reply}")
    finally:
        asyncio.run(dispose_engine())


@app.command()
def state(
    companion_id: str = typer.Option(None, "--companion-id"),
) -> None:
    """Dump companion state (grows over phases)."""
    cid = _resolve(companion_id, "MAYA_COMPANION_ID")

    async def _run() -> tuple[Companion | None, int]:
        sm = get_sessionmaker()
        async with sm() as session:
            comp = await session.get(Companion, cid)
            count = await session.scalar(
                select(func.count())
                .select_from(Message)
                .where(Message.companion_id == cid)
            )
            return comp, count or 0

    comp, count = asyncio.run(_run())
    if comp is None:
        typer.secho("Companion not found.", fg="red")
        raise typer.Exit(code=1)
    typer.echo(f"Companion: {comp.name} (template: {comp.template_id})")
    typer.echo(f"Messages exchanged: {count}")
    typer.echo("[no emotional/relationship state in Phase 1]")
    asyncio.run(dispose_engine())


@app.command()
def history(
    limit: int = typer.Option(50, "--limit"),
    companion_id: str = typer.Option(None, "--companion-id"),
) -> None:
    """Print recent messages (chronological)."""
    cid = _resolve(companion_id, "MAYA_COMPANION_ID")

    async def _run() -> list[Message]:
        sm = get_sessionmaker()
        async with sm() as session:
            stmt = (
                select(Message)
                .where(Message.companion_id == cid)
                .order_by(Message.created_at.desc())
                .limit(limit)
            )
            rows = list((await session.scalars(stmt)).all())
            rows.reverse()
            return rows

    rows = asyncio.run(_run())
    for m in rows:
        who = "You" if m.role == "user" else ("Maya" if m.role == "assistant" else m.role)
        typer.echo(f"[{who}] {m.content}")
    asyncio.run(dispose_engine())


@app.command()
def reset(
    companion_id: str = typer.Option(None, "--companion-id"),
    memory: bool = typer.Option(False, "--memory", help="Also wipe long-term memories."),
    memory_only: bool = typer.Option(
        False, "--memory-only", help="Only wipe memories; keep messages."
    ),
) -> None:
    """Wipe messages (and optionally memories). Keeps user/companion."""
    cid = _resolve(companion_id, "MAYA_COMPANION_ID")
    uid = _resolve(None, "MAYA_USER_ID")

    async def _run() -> tuple[int, int]:
        deleted_msgs = 0
        if not memory_only:
            sm = get_sessionmaker()
            async with sm() as session:
                result = await session.execute(
                    delete(Message).where(Message.companion_id == cid)
                )
                await session.commit()
                deleted_msgs = result.rowcount or 0

        deleted_mem = 0
        if memory or memory_only:
            from maya.memory.service import MemoryService

            svc = MemoryService()
            deleted_mem = await svc.delete_all(uid, cid)
        return deleted_msgs, deleted_mem

    deleted_msgs, deleted_mem = asyncio.run(_run())
    if not memory_only:
        typer.echo(f"Deleted {deleted_msgs} messages.")
    if memory or memory_only:
        typer.echo(
            f"Wiped memory store for this user/companion (status: {deleted_mem})."
        )
    asyncio.run(dispose_engine())


memory_app = typer.Typer(help="Inspect long-term memory.")
app.add_typer(memory_app, name="memory")


@memory_app.command("list")
def memory_list(
    user_id: str = typer.Option(None, "--user-id"),
    companion_id: str = typer.Option(None, "--companion-id"),
) -> None:
    """List all memories for the active user/companion (P2.4)."""
    uid = _resolve(user_id, "MAYA_USER_ID")
    cid = _resolve(companion_id, "MAYA_COMPANION_ID")

    async def _run() -> list[dict]:
        from maya.memory.service import MemoryService

        return await MemoryService().get_all(uid, cid)

    items = asyncio.run(_run())
    if not items:
        typer.echo("(no memories yet)")
    for i, m in enumerate(items, 1):
        typer.echo(f"[{i}] {m['text']}")
    asyncio.run(dispose_engine())


@memory_app.command("search")
def memory_search(
    query: str = typer.Argument(..., help="Search query."),
    user_id: str = typer.Option(None, "--user-id"),
    companion_id: str = typer.Option(None, "--companion-id"),
    limit: int = typer.Option(10, "--limit"),
) -> None:
    """Semantic search over memories (P2.4)."""
    uid = _resolve(user_id, "MAYA_USER_ID")
    cid = _resolve(companion_id, "MAYA_COMPANION_ID")

    async def _run() -> list[dict]:
        from maya.memory.service import MemoryService

        return await MemoryService().search_relevant(query, uid, cid, limit)

    items = asyncio.run(_run())
    if not items:
        typer.echo("(no matches)")
    for i, m in enumerate(items, 1):
        score = m.get("score")
        score_str = f" (score: {score:.2f})" if isinstance(score, (int, float)) else ""
        typer.echo(f"[{i}] {m['text']}{score_str}")
    asyncio.run(dispose_engine())


@app.command()
def costs(
    last: str = typer.Option("24h", "--last", help="Time window: e.g. 1h, 24h, 7d."),
) -> None:
    """Show LLM costs for the last N hours/days (P2.6)."""
    import re

    m = re.fullmatch(r"(\d+)([hd])", last.lower())
    if not m:
        typer.secho("Bad --last format. Use e.g. 24h or 7d.", fg="red")
        raise typer.Exit(code=1)
    n, unit = int(m.group(1)), m.group(2)
    interval = f"{n} hours" if unit == "h" else f"{n} days"

    async def _run() -> dict:
        from sqlalchemy import text as _text

        sm = get_sessionmaker()
        async with sm() as session:
            total = await session.scalar(
                _text(
                    "SELECT COALESCE(SUM(cost_usd), 0) FROM llm_calls "
                    f"WHERE timestamp >= NOW() - INTERVAL '{interval}'"
                )
            )
            by_tier_rows = (
                await session.execute(
                    _text(
                        "SELECT tier, COALESCE(SUM(cost_usd),0), COUNT(*) "
                        "FROM llm_calls "
                        f"WHERE timestamp >= NOW() - INTERVAL '{interval}' "
                        "GROUP BY tier ORDER BY 2 DESC"
                    )
                )
            ).all()
            by_purpose_rows = (
                await session.execute(
                    _text(
                        "SELECT purpose, COALESCE(SUM(cost_usd),0), COUNT(*) "
                        "FROM llm_calls "
                        f"WHERE timestamp >= NOW() - INTERVAL '{interval}' "
                        "GROUP BY purpose ORDER BY 2 DESC"
                    )
                )
            ).all()
            return {
                "total": float(total or 0),
                "by_tier": [(r[0], float(r[1]), r[2]) for r in by_tier_rows],
                "by_purpose": [(r[0] or "(none)", float(r[1]), r[2]) for r in by_purpose_rows],
            }

    data = asyncio.run(_run())
    typer.echo(f"Total (last {last}): ${data['total']:.4f}")
    if data["by_tier"]:
        typer.echo("By tier:")
        for tier, cost, n in data["by_tier"]:
            typer.echo(f"  {tier}: ${cost:.4f}  ({n} calls)")
    if data["by_purpose"]:
        typer.echo("By purpose:")
        for purpose, cost, n in data["by_purpose"]:
            typer.echo(f"  {purpose}: ${cost:.4f}  ({n} calls)")
    asyncio.run(dispose_engine())


@app.command()
def web(
    port: int = typer.Option(8000, "--port"),
    host: str = typer.Option("0.0.0.0", "--host"),
) -> None:
    """Start the web UI server."""
    import uvicorn
    from maya.web import app as web_app
    
    typer.echo(f"🚀 Starting Maya Web UI on http://{host}:{port}")
    typer.echo("   Open http://localhost:8000 in your browser")
    
    uvicorn.run(web_app, host=host, port=port)


if __name__ == "__main__":
    app()
