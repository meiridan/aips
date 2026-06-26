"""Maya CLI (Typer). Commands: seed, chat, state, history, reset.

Active context comes from MAYA_USER_ID / MAYA_COMPANION_ID env vars
(printed by `maya seed`), overridable via flags.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC

import typer
from sqlalchemy import delete, func, select

from maya.config import get_settings
from maya.conversation.orchestrator import Orchestrator
from maya.db.models import Companion, Message, User
from maya.db.session import dispose_engine, get_sessionmaker
from maya.logging import configure_logging

app = typer.Typer(add_completion=False, help="Maya Core CLI")


def _run_with_dispose(factory):
    """Run an async factory and dispose the engine in the SAME event loop.

    Disposing from a second asyncio.run() loop (the old pattern) attaches the
    engine's connections to a dead loop and raises "Event loop is closed" /
    "attached to a different loop" on teardown.
    """

    async def _main():
        try:
            return await factory()
        finally:
            await dispose_engine()

    return asyncio.run(_main())


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
    genesis: bool = typer.Option(
        True, "--genesis/--no-genesis", help="Run the genesis LLM call (P3.3)."
    ),
) -> None:
    """Create a test user + companion, then bring the companion to life (genesis)."""

    async def _run() -> tuple[uuid.UUID, uuid.UUID, str | None]:
        from maya.companions.genesis import run_genesis

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
            uid, cid = user.id, companion.id

        first_message = None
        if genesis:
            result = await run_genesis(cid, sessionmaker=sm)
            first_message = result.first_message
        return uid, cid, first_message

    user_id, companion_id, first_message = _run_with_dispose(_run)
    typer.echo(f"Created user {user_id}  companion {companion_id}")
    if first_message:
        typer.echo("")
        typer.secho(f"[{companion_name}] {first_message}", fg="magenta")
        typer.echo("")
    typer.echo(
        f"Set as active: export MAYA_USER_ID={user_id} "
        f"MAYA_COMPANION_ID={companion_id}"
    )


@app.command()
def chat(
    user_id: str = typer.Option(None, "--user-id"),
    companion_id: str = typer.Option(None, "--companion-id"),
) -> None:
    """Interactive chat REPL."""
    uid = _resolve(user_id, "MAYA_USER_ID")
    cid = _resolve(companion_id, "MAYA_COMPANION_ID")

    typer.echo("[Maya] Hi! I'm Maya. What's on your mind?  (Ctrl-D or 'quit' to exit)")

    async def _repl() -> None:
        # Whole REPL runs in ONE event loop so the shared async engine's
        # connections stay bound to a single loop (per-turn asyncio.run() left
        # connections attached to dead loops → teardown crashes).
        orch = Orchestrator()
        try:
            while True:
                try:
                    line = (await asyncio.to_thread(input, "> ")).strip()
                except EOFError:
                    typer.echo("")
                    break
                if line.lower() in {"quit", "exit"}:
                    break
                if not line:
                    continue
                typer.echo("[Maya] ", nl=False)
                async for piece in orch.stream_message(uid, cid, line):
                    typer.echo(piece, nl=False)
                typer.echo("")
        finally:
            await dispose_engine()

    asyncio.run(_repl())


@app.command()
def state(
    companion_id: str = typer.Option(None, "--companion-id"),
    user_id: str = typer.Option(None, "--user-id"),
) -> None:
    """Rich Phase-3 snapshot: feelings, stage, intimacy/trust, events, commitments."""
    cid = _resolve(companion_id, "MAYA_COMPANION_ID")
    uid = _resolve(user_id, "MAYA_USER_ID")

    async def _run() -> dict | None:
        from datetime import datetime

        from sqlalchemy import select as _select

        from maya.companions.commitments import CommitmentService
        from maya.companions.templates import get_template
        from maya.db.models import RelationshipEvent
        from maya.emotional.service import EmotionalService
        from maya.relationship.service import RelationshipService

        sm = get_sessionmaker()
        async with sm() as session:
            comp = await session.get(Companion, cid)
            if comp is None:
                return None
            count = await session.scalar(
                _select(func.count()).select_from(Message).where(Message.companion_id == cid)
            )
            events = (
                await session.scalars(
                    _select(RelationshipEvent)
                    .where(RelationshipEvent.companion_id == cid)
                    .order_by(RelationshipEvent.occurred_at.desc())
                    .limit(5)
                )
            ).all()
            events = [(e.occurred_at, e.event_type, e.summary) for e in events]

        baseline = get_template(comp.template_id).baseline_emotional
        emo = await EmotionalService(sm).get(cid, baseline=baseline)
        rel = await RelationshipService(sm).get(cid, uid)
        commits = await CommitmentService(sm).get_recent(cid, limit=5)

        last_ago = None
        if rel.last_interaction_at is not None:
            lia = rel.last_interaction_at
            if lia.tzinfo is None:
                lia = lia.replace(tzinfo=UTC)
            mins = int((datetime.now(UTC) - lia).total_seconds() // 60)
            last_ago = mins

        return {
            "name": comp.name,
            "template": comp.template_id,
            "count": count or 0,
            "feelings": emo.feelings,
            "valence": emo.valence,
            "arousal": emo.arousal,
            "stage": rel.stage,
            "intimacy": rel.intimacy_level,
            "trust": rel.trust_level,
            "days": rel.days_known,
            "interactions": rel.total_interactions,
            "events": events,
            "commitments": [(c.commitment_type, c.content, c.importance) for c in commits],
            "last_ago": last_ago,
        }

    data = _run_with_dispose(_run)
    if data is None:
        typer.secho("Companion not found.", fg="red")
        raise typer.Exit(code=1)

    typer.echo(f"═══ {data['name']} ({data['template']}) ═══")
    typer.echo(
        f"Day {data['days']} | Stage: {data['stage']} | "
        f"{data['interactions']} interactions | {data['count']} messages"
    )
    typer.echo("")
    typer.echo("Current feelings:")
    if data["feelings"]:
        for name, val in sorted(data["feelings"].items(), key=lambda kv: -kv[1]):
            typer.echo(f"  {name}: {val:.2f}")
    else:
        typer.echo("  (neutral)")
    typer.echo(f"Valence: {data['valence']:.2f} | Arousal: {data['arousal']:.2f}")
    typer.echo("")
    typer.echo(f"Intimacy: {data['intimacy']}/10 | Trust: {data['trust']}/10")
    typer.echo("")
    typer.echo("Recent significant events:")
    if data["events"]:
        for occurred, etype, summary in data["events"]:
            day = str(occurred)[:10]
            typer.echo(f"  - {day}: {etype} (\"{summary}\")")
    else:
        typer.echo("  (none yet)")
    typer.echo("")
    typer.echo("Active commitments (5 most important):")
    if data["commitments"]:
        for ctype, content, imp in data["commitments"]:
            typer.echo(f"  [{ctype}] {content} (importance: {imp:.2f})")
    else:
        typer.echo("  (none yet)")
    if data["last_ago"] is not None:
        typer.echo("")
        typer.echo(f"Last interaction: {data['last_ago']} minutes ago")


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

    rows = _run_with_dispose(_run)
    for m in rows:
        who = "You" if m.role == "user" else ("Maya" if m.role == "assistant" else m.role)
        typer.echo(f"[{who}] {m.content}")


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

    deleted_msgs, deleted_mem = _run_with_dispose(_run)
    if not memory_only:
        typer.echo(f"Deleted {deleted_msgs} messages.")
    if memory or memory_only:
        typer.echo(
            f"Wiped memory store for this user/companion (status: {deleted_mem})."
        )


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

    items = _run_with_dispose(_run)
    if not items:
        typer.echo("(no memories yet)")
    for m in items:
        short_id = str(m["id"])[:8]
        typer.echo(f"[{short_id}] {m['text']}")


@memory_app.command("delete")
def memory_delete(
    memory_id: str = typer.Argument(..., help="Memory id (or unique prefix) from `memory list`."),
    user_id: str = typer.Option(None, "--user-id"),
    companion_id: str = typer.Option(None, "--companion-id"),
) -> None:
    """Delete a single memory by id (scoped to the active user/companion)."""
    uid = _resolve(user_id, "MAYA_USER_ID")
    cid = _resolve(companion_id, "MAYA_COMPANION_ID")

    async def _run() -> int:
        from maya.memory.service import MemoryService

        return await MemoryService().delete_by_id(memory_id, uid, cid)

    deleted = _run_with_dispose(_run)
    if deleted == 0:
        typer.secho(f"No memory matched id '{memory_id}'.", fg="yellow")
    elif deleted == 1:
        typer.secho(f"Deleted 1 memory ({memory_id}).", fg="green")
    else:
        typer.secho(
            f"Deleted {deleted} memories — prefix '{memory_id}' was ambiguous.",
            fg="yellow",
        )


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

    items = _run_with_dispose(_run)
    if not items:
        typer.echo("(no matches)")
    for i, m in enumerate(items, 1):
        score = m.get("score")
        score_str = f" (score: {score:.2f})" if isinstance(score, (int, float)) else ""
        typer.echo(f"[{i}] {m['text']}{score_str}")


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

    data = _run_with_dispose(_run)
    typer.echo(f"Total (last {last}): ${data['total']:.4f}")
    if data["by_tier"]:
        typer.echo("By tier:")
        for tier, cost, n in data["by_tier"]:
            typer.echo(f"  {tier}: ${cost:.4f}  ({n} calls)")
    if data["by_purpose"]:
        typer.echo("By purpose:")
        for purpose, cost, n in data["by_purpose"]:
            typer.echo(f"  {purpose}: ${cost:.4f}  ({n} calls)")


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
