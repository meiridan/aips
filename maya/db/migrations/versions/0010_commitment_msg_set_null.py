"""commitment.source_message_id: ON DELETE SET NULL

Revision ID: 0010_commitment_msg_set_null
Revises: 0009_auth_and_billing
Create Date: 2026-08-30

`companion_commitments.source_message_id` was created with the default NO
ACTION, so any DELETE over `messages` for a companion who had a commitment
harvested failed with a ForeignKeyViolationError — which is every wizard/preset
re-creation (`reset=true`) and every `maya reset`. A commitment is meant to
outlive the turn it came from, so the reference is cleared rather than blocking
the delete, matching `memories.source_message_id`.

"""

from alembic import op

revision = "0010_commitment_msg_set_null"
down_revision = "0009_auth_and_billing"
branch_labels = None
depends_on = None

CONSTRAINT = "companion_commitments_source_message_id_fkey"


def upgrade() -> None:
    op.execute(f"ALTER TABLE companion_commitments DROP CONSTRAINT IF EXISTS {CONSTRAINT}")
    op.execute(
        f"ALTER TABLE companion_commitments ADD CONSTRAINT {CONSTRAINT} "
        "FOREIGN KEY (source_message_id) REFERENCES messages (id) ON DELETE SET NULL"
    )


def downgrade() -> None:
    op.execute(f"ALTER TABLE companion_commitments DROP CONSTRAINT IF EXISTS {CONSTRAINT}")
    op.execute(
        f"ALTER TABLE companion_commitments ADD CONSTRAINT {CONSTRAINT} "
        "FOREIGN KEY (source_message_id) REFERENCES messages (id)"
    )
