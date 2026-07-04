"""companion reply-length preference: companions.response_length

Revision ID: 0007_response_length
Revises: 0006_eval_runs
Create Date: 2026-07-04

"""

from alembic import op

revision = "0007_response_length"
down_revision = "0006_eval_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE companions ADD COLUMN response_length INTEGER NOT NULL DEFAULT 2"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE companions DROP COLUMN response_length")
