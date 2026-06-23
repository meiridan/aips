"""add llm_calls table for cost tracking (P2.6)

Revision ID: 0003_llm_calls
Revises: 0002_memories
Create Date: 2026-05-31

"""

from alembic import op

revision = "0003_llm_calls"
down_revision = "0002_memories"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE llm_calls (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            timestamp TIMESTAMPTZ DEFAULT NOW(),
            model TEXT NOT NULL,
            tier TEXT NOT NULL,
            input_tokens INT,
            output_tokens INT,
            cost_usd NUMERIC(10, 6),
            latency_ms INT,
            success BOOLEAN NOT NULL DEFAULT TRUE,
            purpose TEXT
        );
        """
    )
    op.execute(
        "CREATE INDEX idx_llm_calls_timestamp ON llm_calls(timestamp DESC);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS llm_calls;")
