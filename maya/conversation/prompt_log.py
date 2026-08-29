"""Living prompt log — every assembled prompt, as it is sent, in one file.

`show-prompt` renders what the prompt WOULD be for a hypothetical message.
This records what it actually WAS, turn after turn, alongside the reply it
produced. Tail it while chatting (`maya prompt-log -f`) and a contradiction
between the persona, the commitments and the moment guidance is visible at the
moment it changes her behaviour, instead of being reconstructed afterwards.

Off by default in production: set MAYA_PROMPT_LOG to a path to enable, or to
one of off/0/false/no to force it off. `run_local.sh` turns it on for local
runs. Writes are best-effort — a logging failure never breaks a turn.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from maya.logging import get_logger

log = get_logger("maya.prompt_log")

ENV_VAR = "MAYA_PROMPT_LOG"
DEFAULT_PATH = "logs/prompts.log"
_DISABLED = {"", "off", "0", "false", "no"}

_WIDE = "═" * 78
_THIN = "─" * 78


def log_path() -> Path | None:
    """The configured log file, or None when the log is switched off."""
    raw = os.environ.get(ENV_VAR)
    if raw is None:
        return None
    if raw.strip().lower() in _DISABLED:
        return None
    return Path(raw.strip()).expanduser()


def read_path() -> Path:
    """Where a reader should look, whether or not this shell enables writing.

    Writing is opt-in via the env var, and `run_local.sh` sets it on the server
    process — not in the terminal you tail from. A reader that demanded the same
    env var would report "log is off" while the server was busily writing it.
    """
    return log_path() or Path(DEFAULT_PATH)


def _append(text: str) -> None:
    """Append to the log, swallowing any IO error — this is never load-bearing."""
    path = log_path()
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(text)
    except OSError as exc:  # noqa: BLE001 - a broken log must not break a turn
        log.warning("prompt_log_write_failed", path=str(path), error=str(exc))


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


def record_prompt(
    *,
    turn_id: str,
    companion_name: str,
    prompt: list[dict],
    tokens: int | None = None,
) -> None:
    """Write the full assembled prompt — system block and every chat turn."""
    if log_path() is None:
        return

    system = next((m["content"] for m in prompt if m.get("role") == "system"), "")
    turns = [m for m in prompt if m.get("role") != "system"]
    head = f"{_now()} · turn {turn_id} · {companion_name}"
    if tokens is not None:
        head += f" · {tokens} tokens"

    parts = [
        f"\n{_WIDE}\n{head}\n{_WIDE}\n",
        f"{_THIN}\nSYSTEM\n{_THIN}\n{system}\n",
        f"{_THIN}\nCHAT TURNS ({len(turns)})\n{_THIN}\n",
    ]
    parts += [f"[{m.get('role')}] {m.get('content', '')}\n" for m in turns]
    _append("".join(parts))


def record_reply(*, turn_id: str, reply: str) -> None:
    """Write the reply that prompt produced, so cause and effect sit together."""
    if log_path() is None:
        return
    _append(f"{_THIN}\nREPLY · turn {turn_id}\n{_THIN}\n{reply}\n")
