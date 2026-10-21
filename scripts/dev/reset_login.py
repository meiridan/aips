"""Strip login details off accounts so the login screen starts from scratch.

Clears the credential columns on `users` (email, email_normalized,
password_hash, google_sub, email_verified_at, last_login_at) and deletes every
row in `sessions` and `password_reset_tokens`. The user row itself survives,
along with its companion, messages and memories — so the conversation is still
there, and `uv run maya claim-account --email <e>` re-attaches credentials to
it instead of a signup creating a second, empty companion.

    uv run python scripts/dev/reset_login.py                # every account
    uv run python scripts/dev/reset_login.py --email a@b.c  # one account
    uv run python scripts/dev/reset_login.py --sessions-only # log out, keep passwords
    uv run python scripts/dev/reset_login.py --yes          # skip the prompt

Note this also unhooks the `dev@local.test` autologin account's credentials;
DEV_AUTOLOGIN recreates it on the next unauthenticated request.
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import delete, func, select

from maya import runtime_cache
from maya.db.models import PasswordResetToken, User, UserSession
from maya.db.session import dispose_engine, get_sessionmaker

_CREDENTIAL_COLUMNS = (
    "email",
    "email_normalized",
    "password_hash",
    "google_sub",
    "email_verified_at",
    "last_login_at",
)


def _describe(user: User) -> str:
    label = user.email or (f"google:{user.google_sub}" if user.google_sub else "no credentials")
    return f"{user.name!r} <{label}>"


async def main(email: str | None, sessions_only: bool, assume_yes: bool) -> None:
    sm = get_sessionmaker()
    async with sm() as session:
        stmt = select(User)
        if email is not None:
            stmt = stmt.where(User.email_normalized == email.strip().lower())
        users = (await session.execute(stmt)).scalars().all()

        if email is not None and not users:
            print(f"No account with email {email!r} — nothing to do.")
            return
        if not users:
            print("No users at all — nothing to do.")
            return

        user_ids = [u.id for u in users]
        sessions = (
            await session.scalar(
                select(func.count())
                .select_from(UserSession)
                .where(UserSession.user_id.in_(user_ids))
            )
        ) or 0

        print(f"{len(users)} account(s), {sessions} live session row(s):")
        for user in users:
            print(f"  {_describe(user)}")
        if sessions_only:
            print("\nWill delete the session rows only — passwords stay.")
        else:
            print("\nWill delete the session rows AND blank out: " + ", ".join(_CREDENTIAL_COLUMNS))
            print("Companions, messages and memories are kept.")

        if not assume_yes:
            # to_thread so the blocking read doesn't stall the loop holding the pool.
            answer = await asyncio.to_thread(input, "Proceed? [y/N] ")
            if answer.strip().lower() not in {"y", "yes"}:
                print("Aborted — nothing changed.")
                return

        await session.execute(delete(UserSession).where(UserSession.user_id.in_(user_ids)))
        await session.execute(
            delete(PasswordResetToken).where(PasswordResetToken.user_id.in_(user_ids))
        )
        if not sessions_only:
            for user in users:
                for column in _CREDENTIAL_COLUMNS:
                    setattr(user, column, None)
        await session.commit()

    runtime_cache.clear()
    if sessions_only:
        print("\nDone — every session revoked. Sign in again with the same password.")
    else:
        print(
            "\nDone — credentials gone. Sign up again, or run "
            "`uv run maya claim-account --email <e>` to re-attach them to the existing row."
        )


async def _run(args: argparse.Namespace) -> None:
    # Dispose inside the same loop that opened the pool; a second asyncio.run()
    # tears down connections attached to an already-closed loop.
    try:
        await main(args.email, args.sessions_only, args.yes)
    finally:
        await dispose_engine()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", help="only this account (default: every account)")
    parser.add_argument(
        "--sessions-only",
        action="store_true",
        help="revoke sessions but keep passwords / Google links",
    )
    parser.add_argument("--yes", "-y", action="store_true", help="skip the confirmation prompt")
    asyncio.run(_run(parser.parse_args()))
