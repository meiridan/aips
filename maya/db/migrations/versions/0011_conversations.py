"""conversations + members, messages.conversation_id, companions.slot

Revision ID: 0011_conversations
Revises: 0010_commitment_msg_set_null
Create Date: 2026-09-13

Group chat (a second companion, Lila, in a room with the account's own
companion) needs a transcript that is not "all messages of one companion".

- `conversations` / `conversation_members`: a solo chat is a one-member room.
- `messages.conversation_id`: every transcript read moves here. Backfilled by
  giving each existing companion a solo conversation.
- `messages.companion_id` becomes nullable: a group user turn has no single
  addressee.
- `companions.slot`: "primary" for the account's own companion, a partner slot
  (e.g. "lila") for group members. Unique per account.

The backfilled solo conversation reuses its companion's id. That is only a
convenient way to join old messages to their new room in plain SQL; nothing
relies on the two ids matching, and rooms created later get fresh ids.

"""

from alembic import op

revision = "0011_conversations"
down_revision = "0010_commitment_msg_set_null"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # One statement per execute — asyncpg rejects multi-command strings.
    op.execute(
        "CREATE TABLE conversations ("
        "id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
        "user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
        "kind TEXT NOT NULL, "
        "title TEXT, "
        "dynamics JSONB NOT NULL DEFAULT '{}', "
        "created_at TIMESTAMPTZ DEFAULT now(), "
        "CONSTRAINT conversations_kind_check CHECK (kind IN ('solo', 'group')))"
    )
    op.execute("CREATE INDEX idx_conversations_user ON conversations (user_id, kind)")
    op.execute(
        "CREATE TABLE conversation_members ("
        "conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE, "
        "companion_id UUID NOT NULL REFERENCES companions(id) ON DELETE CASCADE, "
        "position INTEGER NOT NULL DEFAULT 0, "
        "joined_at TIMESTAMPTZ DEFAULT now(), "
        "PRIMARY KEY (conversation_id, companion_id))"
    )
    op.execute(
        "CREATE INDEX idx_conversation_members_companion ON conversation_members (companion_id)"
    )

    op.execute("ALTER TABLE companions ADD COLUMN slot TEXT NOT NULL DEFAULT 'primary'")
    # Accounts that predate multi-user may own several rows. The oldest stays
    # primary — the same row resolve_for_user already picked — and the rest get
    # a unique legacy slot so the index below can be built.
    op.execute(
        "UPDATE companions c SET slot = 'legacy-' || c.id::text "
        "FROM (SELECT id, row_number() OVER (PARTITION BY user_id ORDER BY created_at, id) AS rn "
        "FROM companions) r "
        "WHERE r.id = c.id AND r.rn > 1"
    )
    op.execute("CREATE UNIQUE INDEX ix_companions_user_slot ON companions (user_id, slot)")

    op.execute(
        "INSERT INTO conversations (id, user_id, kind, created_at) "
        "SELECT id, user_id, 'solo', created_at FROM companions"
    )
    op.execute(
        "INSERT INTO conversation_members (conversation_id, companion_id) "
        "SELECT id, id FROM companions"
    )

    op.execute(
        "ALTER TABLE messages ADD COLUMN conversation_id UUID "
        "REFERENCES conversations(id) ON DELETE CASCADE"
    )
    op.execute("UPDATE messages SET conversation_id = companion_id")
    op.execute("ALTER TABLE messages ALTER COLUMN conversation_id SET NOT NULL")
    op.execute("ALTER TABLE messages ALTER COLUMN companion_id DROP NOT NULL")
    op.execute(
        "CREATE INDEX idx_messages_conversation_created ON messages (conversation_id, created_at)"
    )


def downgrade() -> None:
    # Group user turns have no companion and cannot survive NOT NULL.
    op.execute("DELETE FROM messages WHERE companion_id IS NULL")
    op.execute("DROP INDEX IF EXISTS idx_messages_conversation_created")
    op.execute("ALTER TABLE messages ALTER COLUMN companion_id SET NOT NULL")
    op.execute("ALTER TABLE messages DROP COLUMN conversation_id")
    op.execute("DROP INDEX IF EXISTS ix_companions_user_slot")
    op.execute("ALTER TABLE companions DROP COLUMN slot")
    op.execute("DROP TABLE conversation_members")
    op.execute("DROP TABLE conversations")
