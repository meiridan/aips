"""add memories table

Revision ID: 0002_memories
Revises: 0001_initial
Create Date: 2026-05-30

"""

from alembic import op

revision = "0002_memories"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE memories (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            companion_id UUID NOT NULL REFERENCES companions(id) ON DELETE CASCADE,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            text TEXT NOT NULL,
            source_message_id UUID REFERENCES messages(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        """
    )

    op.execute(
        """
        CREATE INDEX idx_memories_companion_user
            ON memories(companion_id, user_id);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS memories;")
