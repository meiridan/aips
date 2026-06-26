"""phase 3 state tables: emotional, relationship, events, commitments (P3.1)

Revision ID: 0004_phase3_state
Revises: 0003_llm_calls
Create Date: 2026-06-26

"""

from alembic import op

revision = "0004_phase3_state"
down_revision = "0003_llm_calls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE companions
            ADD COLUMN personality JSONB NOT NULL DEFAULT '{}',
            ADD COLUMN backstory   TEXT  NOT NULL DEFAULT '';
        """
    )
    op.execute(
        """
        CREATE TABLE emotional_state (
            companion_id UUID PRIMARY KEY REFERENCES companions(id) ON DELETE CASCADE,
            valence FLOAT NOT NULL DEFAULT 0.0 CHECK (valence BETWEEN -1 AND 1),
            arousal FLOAT NOT NULL DEFAULT 0.5 CHECK (arousal BETWEEN 0 AND 1),
            dominance FLOAT NOT NULL DEFAULT 0.5 CHECK (dominance BETWEEN 0 AND 1),
            feelings JSONB NOT NULL DEFAULT '{}',
            last_updated TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute(
        """
        CREATE TABLE relationship_state (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            companion_id UUID NOT NULL REFERENCES companions(id) ON DELETE CASCADE,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE (companion_id, user_id),
            stage TEXT NOT NULL DEFAULT 'strangers',
            intimacy_level INT NOT NULL DEFAULT 1 CHECK (intimacy_level BETWEEN 0 AND 10),
            trust_level INT NOT NULL DEFAULT 1 CHECK (trust_level BETWEEN 0 AND 10),
            days_known INT NOT NULL DEFAULT 0,
            total_interactions INT NOT NULL DEFAULT 0,
            last_interaction_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        """
    )
    op.execute(
        """
        CREATE TABLE relationship_events (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            companion_id UUID NOT NULL REFERENCES companions(id) ON DELETE CASCADE,
            event_type TEXT NOT NULL,
            summary TEXT NOT NULL,
            impact JSONB DEFAULT '{}',
            occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute(
        "CREATE INDEX idx_rel_events_companion "
        "ON relationship_events(companion_id, occurred_at DESC);"
    )
    op.execute(
        """
        CREATE TABLE companion_commitments (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            companion_id UUID NOT NULL REFERENCES companions(id) ON DELETE CASCADE,
            content TEXT NOT NULL,
            commitment_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            importance FLOAT NOT NULL DEFAULT 0.5,
            source_message_id UUID REFERENCES messages(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute(
        "CREATE INDEX idx_commitments_companion_active "
        "ON companion_commitments(companion_id) WHERE status = 'active';"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS companion_commitments;")
    op.execute("DROP TABLE IF EXISTS relationship_events;")
    op.execute("DROP TABLE IF EXISTS relationship_state;")
    op.execute("DROP TABLE IF EXISTS emotional_state;")
    op.execute(
        "ALTER TABLE companions DROP COLUMN IF EXISTS backstory, "
        "DROP COLUMN IF EXISTS personality;"
    )
