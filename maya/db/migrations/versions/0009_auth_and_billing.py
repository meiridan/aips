"""accounts + sessions + password resets + subscriptions

Revision ID: 0009_auth_and_billing
Revises: 0008_persona_spec
Create Date: 2026-08-29

Turns `users` into a real account row (email/password/Google) and adds the
tables login and billing need. Existing rows are left untouched: the live
companion is claimed by an account via `maya claim-account`, not by this
migration, which cannot know which email should own her.

"""

from alembic import op

revision = "0009_auth_and_billing"
down_revision = "0008_persona_spec"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # asyncpg's prepared-statement path rejects multiple commands per execute,
    # so issue each DDL statement separately (matches 0004/0005's style).
    op.execute(
        "ALTER TABLE users "
        "ADD COLUMN email TEXT, "
        "ADD COLUMN email_normalized TEXT, "
        "ADD COLUMN password_hash TEXT, "
        "ADD COLUMN google_sub TEXT, "
        "ADD COLUMN email_verified_at TIMESTAMPTZ, "
        "ADD COLUMN last_login_at TIMESTAMPTZ"
    )
    # Partial uniqueness: pre-auth rows (and Google-only accounts) keep NULLs.
    op.execute(
        "CREATE UNIQUE INDEX ix_users_email_normalized ON users (email_normalized) "
        "WHERE email_normalized IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX ix_users_google_sub ON users (google_sub) WHERE google_sub IS NOT NULL"
    )

    # Opaque server-side sessions. Only the SHA-256 of the cookie value is
    # stored, so a database leak does not hand over live sessions.
    op.execute(
        "CREATE TABLE sessions ("
        "id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
        "user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
        "token_hash TEXT NOT NULL UNIQUE, "
        "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
        "last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
        "expires_at TIMESTAMPTZ NOT NULL, "
        "revoked_at TIMESTAMPTZ, "
        "user_agent TEXT, "
        "ip TEXT)"
    )
    op.execute("CREATE INDEX idx_sessions_user ON sessions (user_id)")
    op.execute("CREATE INDEX idx_sessions_expires ON sessions (expires_at)")

    # Reset tokens: hashed like sessions, single-use via used_at, short TTL.
    op.execute(
        "CREATE TABLE password_reset_tokens ("
        "id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
        "user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
        "token_hash TEXT NOT NULL UNIQUE, "
        "expires_at TIMESTAMPTZ NOT NULL, "
        "used_at TIMESTAMPTZ, "
        "created_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    )
    op.execute("CREATE INDEX idx_reset_tokens_user ON password_reset_tokens (user_id)")

    # One subscription row per user; the plan/status here is the only thing
    # entitlement checks read (never anything client-supplied).
    op.execute(
        "CREATE TABLE subscriptions ("
        "id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
        "user_id UUID NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE, "
        "plan_id TEXT NOT NULL DEFAULT 'free', "
        "status TEXT NOT NULL DEFAULT 'inactive', "
        "stripe_customer_id TEXT UNIQUE, "
        "stripe_subscription_id TEXT UNIQUE, "
        "current_period_end TIMESTAMPTZ, "
        "cancel_at_period_end BOOLEAN NOT NULL DEFAULT false, "
        "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
        "updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    )

    # Stripe retries webhooks; this is the idempotency guard so a replayed
    # subscription.updated cannot be applied twice.
    op.execute(
        "CREATE TABLE stripe_events ("
        "event_id TEXT PRIMARY KEY, "
        "received_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS stripe_events")
    op.execute("DROP TABLE IF EXISTS subscriptions")
    op.execute("DROP TABLE IF EXISTS password_reset_tokens")
    op.execute("DROP TABLE IF EXISTS sessions")
    op.execute("DROP INDEX IF EXISTS ix_users_google_sub")
    op.execute("DROP INDEX IF EXISTS ix_users_email_normalized")
    op.execute(
        "ALTER TABLE users "
        "DROP COLUMN email, "
        "DROP COLUMN email_normalized, "
        "DROP COLUMN password_hash, "
        "DROP COLUMN google_sub, "
        "DROP COLUMN email_verified_at, "
        "DROP COLUMN last_login_at"
    )
