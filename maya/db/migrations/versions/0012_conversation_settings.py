"""conversations.settings: per-room controls picked in the UI

Revision ID: 0012_conversation_settings
Revises: 0011_conversations
Create Date: 2026-09-13

The group room's reply length and talk mode (free / moderated). Kept apart from
`dynamics`, which is prompt content rather than a user choice.

"""

from alembic import op

revision = "0012_conversation_settings"
down_revision = "0011_conversations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE conversations ADD COLUMN settings JSONB NOT NULL DEFAULT '{}'")


def downgrade() -> None:
    op.execute("ALTER TABLE conversations DROP COLUMN settings")
