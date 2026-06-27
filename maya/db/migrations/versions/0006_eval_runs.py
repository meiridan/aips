"""eval regression tracking: eval_runs

Revision ID: 0006_eval_runs
Revises: 0005_telegram_chat_id
Create Date: 2026-06-27

"""

from alembic import op

revision = "0006_eval_runs"
down_revision = "0005_telegram_chat_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # One statement per execute (asyncpg prepared-statement path — matches 0004/0005).
    op.execute(
        """
        CREATE TABLE eval_runs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            git_sha TEXT NOT NULL,
            persona TEXT NOT NULL,
            days INT NOT NULL,
            seed INT NOT NULL,
            scores JSONB NOT NULL,
            failure_modes JSONB DEFAULT '[]',
            standout_moments JSONB DEFAULT '[]',
            transcript_path TEXT,
            cost_usd NUMERIC(10, 4),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_eval_runs_persona_created "
        "ON eval_runs (persona, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_eval_runs_persona_created")
    op.execute("DROP TABLE IF EXISTS eval_runs")
