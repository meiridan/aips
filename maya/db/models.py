"""SQLAlchemy 2.0 models for Phase 1 tables (users, companions, messages)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        # Partial so the pre-auth rows (and Google-only accounts) that leave
        # these NULL don't collide with each other.
        Index(
            "ix_users_email_normalized",
            "email_normalized",
            unique=True,
            postgresql_where=text("email_normalized IS NOT NULL"),
        ),
        Index(
            "ix_users_google_sub",
            "google_sub",
            unique=True,
            postgresql_where=text("google_sub IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    # Set when the user reaches Maya via Telegram; maps a chat to this user.
    telegram_chat_id: Mapped[int | None] = mapped_column(
        BigInteger, unique=True, index=True, nullable=True
    )
    # ── account fields (§0009) ──────────────────────────────────────────────
    # All nullable: rows predating auth have none, and a Google-only account
    # never gets a password. Uniqueness is enforced by partial indexes on the
    # normalized email and the Google subject, not by these columns.
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    # lower(trim(email)) — the column every lookup and the unique index use.
    email_normalized: Mapped[str | None] = mapped_column(Text, nullable=True)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    google_sub: Mapped[str | None] = mapped_column(Text, nullable=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str] = mapped_column(Text, server_default="Asia/Jerusalem")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    companions: Mapped[list[Companion]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Companion(Base):
    __tablename__ = "companions"
    __table_args__ = (
        # One companion per role per account: the account's own ("primary") and
        # each group-chat partner (e.g. "lila") — see maya.conversation.rooms.
        Index("ix_companions_user_slot", "user_id", "slot", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    slot: Mapped[str] = mapped_column(Text, nullable=False, server_default="primary")
    name: Mapped[str] = mapped_column(Text, nullable=False, server_default="Maya")
    template_id: Mapped[str] = mapped_column(Text, nullable=False, server_default="flirt")
    # Phase 3: personality blob + generated backstory (filled by genesis).
    personality: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    backstory: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    # Reply-length preference: 1=short(~100w) 2=medium(~300w) 3=long(~1000w).
    response_length: Mapped[int] = mapped_column(Integer, nullable=False, server_default="2")
    # Creation-wizard output. `persona_spec` is the raw PersonaSpec dump (so the
    # wizard can reopen prefilled); `onboarded_at` is the gate the SPA reads to
    # decide wizard-vs-chat; `locale` drives the reply-language directive.
    persona_spec: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    avatar_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    locale: Mapped[str] = mapped_column(Text, nullable=False, server_default="he")
    onboarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(back_populates="companions")
    messages: Mapped[list[Message]] = relationship(
        back_populates="companion", cascade="all, delete-orphan"
    )


class Conversation(Base):
    """A transcript: one companion's 1:1 chat ("solo") or a room of several ("group").

    Per-companion state (memories, emotions, relationship, commitments) is NOT
    scoped to a conversation — Maya is the same person in both rooms; only what
    she has seen said differs.
    """

    __tablename__ = "conversations"
    __table_args__ = (
        CheckConstraint("kind IN ('solo', 'group')", name="conversations_kind_check"),
        Index("idx_conversations_user", "user_id", "kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    # Group rooms: how the members relate to each other, fed to every prompt.
    dynamics: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    # Group rooms: controls the user picked (maya/conversation/group_settings.py).
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ConversationMember(Base):
    __tablename__ = "conversation_members"
    __table_args__ = (Index("idx_conversation_members_companion", "companion_id"),)

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    companion_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant', 'system')", name="messages_role_check"),
        Index("idx_messages_companion_created", "companion_id", "created_at"),
        Index("idx_messages_conversation_created", "conversation_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    # Every transcript read goes through this, never companion_id: Maya's group
    # replies carry her companion_id too and must not leak into her solo chat.
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    # The speaker for an assistant turn, the addressee for a solo user turn, and
    # NULL for a group user turn (addressees then live in metadata.addressed).
    companion_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companions.id", ondelete="CASCADE"),
        nullable=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # NOTE: DB column is "metadata"; attribute renamed because Base.metadata is reserved.
    extra: Mapped[dict] = mapped_column("metadata", JSONB, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    companion: Mapped[Companion | None] = relationship(back_populates="messages")


class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    companion_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companions.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LLMCall(Base):
    __tablename__ = "llm_calls"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    model: Mapped[str] = mapped_column(Text, nullable=False)
    tier: Mapped[str] = mapped_column(Text, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[float | None] = mapped_column(Numeric(10, 6))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    purpose: Mapped[str | None] = mapped_column(Text)


# ───────────────────────── Phase 3: state models (§P3.1) ─────────────────────────


class EmotionalState(Base):
    __tablename__ = "emotional_state"
    __table_args__ = (
        CheckConstraint("valence BETWEEN -1 AND 1", name="emotional_valence_check"),
        CheckConstraint("arousal BETWEEN 0 AND 1", name="emotional_arousal_check"),
        CheckConstraint("dominance BETWEEN 0 AND 1", name="emotional_dominance_check"),
    )

    companion_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    valence: Mapped[float] = mapped_column(Float, nullable=False, server_default="0.0")
    arousal: Mapped[float] = mapped_column(Float, nullable=False, server_default="0.5")
    dominance: Mapped[float] = mapped_column(Float, nullable=False, server_default="0.5")
    feelings: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RelationshipState(Base):
    __tablename__ = "relationship_state"
    __table_args__ = (
        UniqueConstraint("companion_id", "user_id", name="relationship_companion_user_uq"),
        CheckConstraint("intimacy_level BETWEEN 0 AND 10", name="relationship_intimacy_check"),
        CheckConstraint("trust_level BETWEEN 0 AND 10", name="relationship_trust_check"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    companion_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companions.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    stage: Mapped[str] = mapped_column(Text, nullable=False, server_default="strangers")
    intimacy_level: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    trust_level: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    days_known: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    total_interactions: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_interaction_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RelationshipEvent(Base):
    __tablename__ = "relationship_events"
    __table_args__ = (
        Index(
            "idx_rel_events_companion",
            "companion_id",
            "occurred_at",
            postgresql_ops={"occurred_at": "DESC"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    companion_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companions.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    impact: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CompanionCommitment(Base):
    __tablename__ = "companion_commitments"
    __table_args__ = (
        Index(
            "idx_commitments_companion_active",
            "companion_id",
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    companion_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companions.id", ondelete="CASCADE"),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    commitment_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    importance: Mapped[float] = mapped_column(Float, nullable=False, server_default="0.5")
    # SET NULL, like Memory.source_message_id: a commitment outlives the turn it
    # came from, and without it any DELETE over `messages` (a reset, `maya
    # reset`) fails on this constraint instead.
    source_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# ───────────────────────── Phase 4: eval regression tracking (§P4.7) ──────────


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    git_sha: Mapped[str] = mapped_column(Text, nullable=False)
    persona: Mapped[str] = mapped_column(Text, nullable=False)
    days: Mapped[int] = mapped_column(Integer, nullable=False)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    scores: Mapped[dict] = mapped_column(JSONB, nullable=False)
    failure_modes: Mapped[dict] = mapped_column(JSONB, server_default="[]")
    standout_moments: Mapped[dict] = mapped_column(JSONB, server_default="[]")
    transcript_path: Mapped[str | None] = mapped_column(Text)
    cost_usd: Mapped[float | None] = mapped_column(Numeric(10, 4))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# ───────────────────── auth + billing (§0009) ────────────────────────────────


class UserSession(Base):
    """A logged-in browser session.

    Named `UserSession` rather than `Session` because every module here already
    deals in SQLAlchemy `AsyncSession` objects called `session`.

    Only the SHA-256 of the cookie value is stored, so the table is useless to
    anyone who reads it. Server-side (rather than a signed token) because a
    password reset has to revoke every outstanding session.
    """

    __tablename__ = "sessions"
    __table_args__ = (
        Index("idx_sessions_user", "user_id"),
        Index("idx_sessions_expires", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(Text)


class PasswordResetToken(Base):
    """A single-use, short-lived password-reset grant.

    Hashed like a session token; `used_at` is what makes it single-use.
    """

    __tablename__ = "password_reset_tokens"
    __table_args__ = (Index("idx_reset_tokens_user", "user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Subscription(Base):
    """One row per user. The only thing entitlement checks are allowed to read.

    Written exclusively by the Stripe webhook — never from a client request, so
    a user cannot talk themselves into a plan.
    """

    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    plan_id: Mapped[str] = mapped_column(Text, nullable=False, server_default="free")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="inactive")
    stripe_customer_id: Mapped[str | None] = mapped_column(Text, unique=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(Text, unique=True)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_at_period_end: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class StripeEvent(Base):
    """Webhook idempotency guard — Stripe retries, and a replayed
    `subscription.updated` must not be applied twice."""

    __tablename__ = "stripe_events"

    event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
