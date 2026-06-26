"""telegram chat mapping: users.telegram_chat_id

Revision ID: 0005_telegram_chat_id
Revises: 0004_phase3_state
Create Date: 2026-06-26

"""

from alembic import op

revision = "0005_telegram_chat_id"
down_revision = "0004_phase3_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # asyncpg's prepared-statement path rejects multiple commands per execute,
    # so issue each DDL statement separately (matches 0004's style).
    op.execute("ALTER TABLE users ADD COLUMN telegram_chat_id BIGINT")
    op.execute(
        "CREATE UNIQUE INDEX ix_users_telegram_chat_id ON users (telegram_chat_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_users_telegram_chat_id")
    op.execute("ALTER TABLE users DROP COLUMN telegram_chat_id")
