"""initial schema: extensions + users, companions, messages

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-30

"""

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS vector;')
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";')

    op.execute(
        """
        CREATE TABLE users (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name TEXT NOT NULL,
            description TEXT,
            timezone TEXT DEFAULT 'Asia/Jerusalem',
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        """
    )

    op.execute(
        """
        CREATE TABLE companions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL DEFAULT 'Maya',
            template_id TEXT NOT NULL DEFAULT 'flirt',
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        """
    )

    op.execute(
        """
        CREATE TABLE messages (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            companion_id UUID NOT NULL REFERENCES companions(id) ON DELETE CASCADE,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
            content TEXT NOT NULL,
            metadata JSONB DEFAULT '{}',
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        """
    )

    op.execute(
        """
        CREATE INDEX idx_messages_companion_created
            ON messages(companion_id, created_at DESC);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS messages;")
    op.execute("DROP TABLE IF EXISTS companions;")
    op.execute("DROP TABLE IF EXISTS users;")
