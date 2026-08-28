"""creation-wizard output on companions: persona_spec, avatar_path, locale, onboarded_at

Revision ID: 0008_persona_spec
Revises: 0007_response_length
Create Date: 2026-08-28

"""

from alembic import op

revision = "0008_persona_spec"
down_revision = "0007_response_length"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE companions "
        "ADD COLUMN persona_spec JSONB NOT NULL DEFAULT '{}'::jsonb, "
        "ADD COLUMN avatar_path TEXT, "
        "ADD COLUMN locale TEXT NOT NULL DEFAULT 'he', "
        "ADD COLUMN onboarded_at TIMESTAMPTZ"
    )
    # Companions that predate the wizard already have a live persona — treat them
    # as onboarded so existing installs don't get bounced into the wizard.
    op.execute("UPDATE companions SET onboarded_at = created_at WHERE backstory <> ''")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE companions "
        "DROP COLUMN persona_spec, "
        "DROP COLUMN avatar_path, "
        "DROP COLUMN locale, "
        "DROP COLUMN onboarded_at"
    )
